import os
import uuid
from datetime import datetime
from typing import List

from flask import Flask, abort, make_response, render_template, request, send_from_directory

from main import (
    DEFAULT_BATHROOMS,
    DEFAULT_BEDROOMS,
    DEFAULT_PROPERTY_TYPES,
    DEFAULT_ZIPS,
    run_mls_active_listings,
)

app = Flask(__name__)
OUTPUT_DIR = os.path.join(os.getcwd(), "output")
APP_USERNAME = os.getenv("APP_USERNAME", "").strip()
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
PROTECT_APP = bool(APP_USERNAME and APP_PASSWORD)


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
        },
        results=None,
        error=None,
    )


@app.post("/run")
def run():
    try:
        zips = parse_list(request.form.get("zips", "")) or DEFAULT_ZIPS
        property_types = request.form.getlist("property_types") or DEFAULT_PROPERTY_TYPES
        bedrooms = request.form.get("bedrooms", DEFAULT_BEDROOMS).strip() or DEFAULT_BEDROOMS
        bathrooms = request.form.get("bathrooms", DEFAULT_BATHROOMS).strip() or DEFAULT_BATHROOMS

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        filename = f"rent_comps_{ts}_{suffix}.csv"
        out_path = os.path.join("output", filename)

        df = run_mls_active_listings(
            target_zips=zips,
            target_property_types=property_types,
            target_bedrooms=bedrooms,
            target_bathrooms=bathrooms,
            out_path=out_path,
        )

        table_html = df.head(200).to_html(index=False, classes="table")

        results = {
            "row_count": len(df),
            "filename": filename,
            "table_html": table_html,
            "zips": ", ".join(zips),
            "property_types": ", ".join(property_types),
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
        }

        return render_template(
            "index.html",
            defaults={
                "zips": ", ".join(zips),
                "property_types": property_types,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
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
            },
            results=None,
            error=str(exc),
        )


@app.get("/download/<path:filename>")
def download(filename: str):
    filename = os.path.basename(filename)
    full_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
