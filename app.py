import os
import io
import uuid
from datetime import datetime
from typing import List

from flask import Flask, abort, make_response, render_template, request, send_file

from main import (
    DEFAULT_BATHROOMS,
    DEFAULT_BEDROOMS,
    DEFAULT_PROPERTY_TYPES,
    DEFAULT_ZIPS,
    run_mls_active_listings,
    run_sales_properties_last_12_months,
)

app = Flask(__name__)
OUTPUT_DIR = os.path.join(os.getcwd(), "output")
APP_USERNAME = os.getenv("APP_USERNAME", "").strip()
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
PROTECT_APP = bool(APP_USERNAME and APP_PASSWORD)
EXPORTS: dict[str, bytes] = {}
EXPORT_META: dict[str, str] = {}


def _unauthorized():
    return make_response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="RentCast Comps"'},
    )


@app.before_request
def protect_app():
    if not PROTECT_APP:
        return None
    if request.endpoint in {"static", "health"}:
        return None

    auth = request.authorization
    if not auth or auth.username != APP_USERNAME or auth.password != APP_PASSWORD:
        return _unauthorized()

    return None


@app.get("/health")
def health():
    return {"status": "ok"}


def parse_list(value: str) -> List[str]:
    if not value:
        return []
    cleaned = value.replace("\n", ",")
    items = [item.strip() for item in cleaned.split(",")]
    return [item for item in items if item]


@app.get("/")
def index():
    return render_template(
        "index.html",
        defaults={
            "zips": ", ".join(DEFAULT_ZIPS),
            "property_types": DEFAULT_PROPERTY_TYPES,
            "bedrooms": DEFAULT_BEDROOMS,
            "bathrooms": DEFAULT_BATHROOMS,
            "query_scope": "sales",
            "lookback_days": "365",
        },
        results=None,
        error=None,
    )


def _build_result_payload(
    df,
    dataset_name: str,
    dataset_label: str,
    query_scope: str,
    zips,
    property_types,
    bedrooms: str,
    bathrooms: str,
    out_path: str,
):
    table_html = df.head(200).to_html(index=False, classes="table")
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    download_token = uuid.uuid4().hex
    EXPORTS[download_token] = csv_bytes
    filename = os.path.basename(out_path).replace(".csv", ".csv")
    EXPORT_META[download_token] = filename

    return {
        "row_count": len(df),
        "filename": os.path.basename(out_path),
        "download_token": download_token,
        "table_html": table_html,
        "zips": ", ".join(zips),
        "property_types": ", ".join(property_types),
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "query_scope": query_scope,
        "dataset_name": dataset_name,
        "dataset_label": dataset_label,
    }


@app.post("/run")
def run():
    try:
        zips = parse_list(request.form.get("zips", "")) or DEFAULT_ZIPS
        property_types = ["Single Family"]
        bedrooms = request.form.get("bedrooms", DEFAULT_BEDROOMS).strip() or DEFAULT_BEDROOMS
        bathrooms = request.form.get("bathrooms", DEFAULT_BATHROOMS).strip() or DEFAULT_BATHROOMS
        query_scope = request.form.get("query_scope", "sales").strip() or "sales"
        lookback_days = request.form.get("lookback_days", "365").strip()
        lookback_days = int(lookback_days) if lookback_days.isdigit() else 365

        selected_scope = {"sales", "listings", "both"}
        if query_scope not in selected_scope:
            query_scope = "sales"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_token = uuid.uuid4().hex[:6]
        results = []
        scopes_to_run = [query_scope] if query_scope != "both" else ["sales", "listings"]

        if "sales" in scopes_to_run:
            out_path = os.path.join("output", f"rentcast_sales_{ts}_{run_token}_sales.csv")
            df_sales = run_sales_properties_last_12_months(
                target_zips=zips,
                target_property_types=property_types,
                target_bedrooms=bedrooms,
                target_bathrooms=bathrooms,
                lookback_days=lookback_days,
                out_path=out_path,
            )
            results.append(
                _build_result_payload(
                    df_sales,
                    "sales",
                    f"Sales (last {lookback_days} days)",
                    query_scope,
                    zips,
                    property_types,
                    bedrooms,
                    bathrooms,
                    out_path,
                )
            )

        if "listings" in scopes_to_run:
            out_path = os.path.join("output", f"rentcast_listings_{ts}_{run_token}_listings.csv")
            df_listings = run_mls_active_listings(
                target_zips=zips,
                target_property_types=property_types,
                target_bedrooms=bedrooms,
                target_bathrooms=bathrooms,
                out_path=out_path,
            )
            results.append(
                _build_result_payload(
                    df_listings,
                    "listings",
                    "Active Rental Listings",
                    query_scope,
                    zips,
                    property_types,
                    bedrooms,
                    bathrooms,
                    out_path,
                )
            )

        return render_template(
            "index.html",
            defaults={
                "zips": ", ".join(zips),
                "property_types": property_types,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "query_scope": query_scope,
                "lookback_days": str(lookback_days),
            },
            results=results,
            error=None,
        )
    except Exception as exc:
        return render_template(
            "index.html",
            defaults={
                "zips": ", ".join(DEFAULT_ZIPS),
                "property_types": DEFAULT_PROPERTY_TYPES,
                "bedrooms": DEFAULT_BEDROOMS,
                "bathrooms": DEFAULT_BATHROOMS,
                "query_scope": "sales",
                "lookback_days": "365",
            },
            results=None,
            error=str(exc),
        )


@app.get("/download/<string:token>")
def download(token: str):
    csv_bytes = EXPORTS.get(token)
    download_name = EXPORT_META.get(token, "rentcast_comps.csv")
    if csv_bytes:
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name=download_name,
        )

    token_filename = os.path.basename(token)
    full_path = os.path.join(OUTPUT_DIR, token_filename)
    if os.path.isfile(full_path):
        with open(full_path, "rb") as f:
            return send_file(
                io.BytesIO(f.read()),
                mimetype="text/csv",
                as_attachment=True,
                download_name=token_filename,
            )

    abort(404)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
