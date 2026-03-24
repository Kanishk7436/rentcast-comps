import io
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from flask import Flask, abort, make_response, render_template, request, send_file
from markupsafe import Markup

from main import (
    DEFAULT_BATHROOMS,
    DEFAULT_BEDROOMS,
    DEFAULT_COMP_COUNT,
    DEFAULT_LISTING_CITY,
    DEFAULT_LISTING_LIMIT,
    DEFAULT_LISTING_STATE,
    DEFAULT_MARKET_ZIP,
    DEFAULT_MAX_RADIUS,
    DEFAULT_PROPERTY_TYPE,
    clamp_int,
    clean_optional_text,
    comparables_to_dataframe,
    fetch_listing_search_results,
    fetch_market_stats,
    fetch_property_record,
    fetch_rent_estimate,
    fetch_value_estimate,
    listings_to_dataframe,
    market_history_to_dataframe,
    parse_iso_date,
    select_property_type_snapshot,
    year_value_dict_to_dataframe,
)

app = Flask(__name__)
OUTPUT_DIR = os.path.join(os.getcwd(), "output")
APP_USERNAME = os.getenv("APP_USERNAME", "").strip()
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
PROTECT_APP = bool(APP_USERNAME and APP_PASSWORD)
EXPORTS: dict[str, bytes] = {}
EXPORT_META: dict[str, str] = {}

SECTION_IDS = {
    "property": "property-lab",
    "listings": "listing-radar",
    "market": "zip-pulse",
}


def _unauthorized():
    return make_response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="RentCast Console"'},
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


def default_context() -> Dict[str, Any]:
    return {
        "property_form": {
            "address": "",
            "comp_count": str(DEFAULT_COMP_COUNT),
            "max_radius": str(DEFAULT_MAX_RADIUS),
        },
        "listing_form": {
            "search_scope": "both",
            "zip_code": DEFAULT_MARKET_ZIP,
            "city": DEFAULT_LISTING_CITY,
            "state": DEFAULT_LISTING_STATE,
            "bedrooms": DEFAULT_BEDROOMS,
            "bathrooms": DEFAULT_BATHROOMS,
            "limit": str(DEFAULT_LISTING_LIMIT),
        },
        "market_form": {
            "zip_code": DEFAULT_MARKET_ZIP,
        },
        "results": {
            "property": None,
            "listings": None,
            "market": None,
        },
        "errors": {
            "property": None,
            "listings": None,
            "market": None,
        },
        "focus_section": None,
        "property_type": DEFAULT_PROPERTY_TYPE,
    }


def render_dashboard(**overrides):
    context = default_context()
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(context.get(key), dict):
            merged = dict(context[key])
            merged.update(value)
            context[key] = merged
        else:
            context[key] = value
    return render_template("index.html", **context)


def to_number(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def format_currency(value: Any, decimals: int = 0, suffix: str = "") -> str:
    number = to_number(value)
    if number is None:
        return "-"
    if decimals == 0:
        formatted = f"${number:,.0f}"
    else:
        formatted = f"${number:,.{decimals}f}"
    return f"{formatted}{suffix}"


def format_number(value: Any, decimals: int = 0, suffix: str = "") -> str:
    number = to_number(value)
    if number is None:
        return "-"
    if decimals == 0:
        formatted = f"{number:,.0f}"
    else:
        formatted = f"{number:,.{decimals}f}"
    return f"{formatted}{suffix}"


def format_text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    return text or "-"


def format_bool(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "-"


def format_date(value: Any) -> str:
    parsed = parse_iso_date(value)
    if parsed is not None:
        return parsed.strftime("%b %d, %Y")
    return format_text(value)


def metric(label: str, value: str, hint: Optional[str] = None, tone: str = "neutral") -> Dict[str, str]:
    return {
        "label": label,
        "value": value,
        "hint": hint or "",
        "tone": tone,
    }


def detail_rows(items: List[tuple[str, Any]], formatter=format_text) -> List[Dict[str, str]]:
    rows = []
    for label, value in items:
        if value in (None, "", [], {}):
            continue
        rows.append({"label": label, "value": formatter(value)})
    return rows


def register_download(df: pd.DataFrame, filename: str) -> str:
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    token = uuid.uuid4().hex
    EXPORTS[token] = csv_bytes
    EXPORT_META[token] = filename
    return token


def table_payload(
    df: pd.DataFrame,
    *,
    limit: int = 12,
    formatters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if df is None:
        df = pd.DataFrame()

    preview = df.head(limit).copy()
    formatters = formatters or {}

    for column in preview.columns:
        formatter = formatters.get(column, format_text)
        preview[column] = preview[column].map(formatter)

    return {
        "columns": list(preview.columns),
        "rows": preview.to_dict(orient="records"),
        "row_count": len(df),
        "display_count": min(len(df), limit),
        "empty": df.empty,
    }


def median_display(series: pd.Series, formatter) -> str:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return "-"
    return formatter(numeric.median())


def build_sparkline(values: List[Any], *, stroke: str, fill: str) -> Markup:
    points = [to_number(value) for value in values]
    numeric_points = [value for value in points if value is not None]
    if len(numeric_points) < 2:
        return Markup("")

    width = 220
    height = 64
    padding = 6
    low = min(numeric_points)
    high = max(numeric_points)
    spread = high - low or 1
    step = (width - padding * 2) / max(len(points) - 1, 1)

    line_points = []
    for index, value in enumerate(points):
        if value is None:
            continue
        x = padding + index * step
        y = height - padding - ((value - low) / spread) * (height - padding * 2)
        line_points.append((x, y))

    if len(line_points) < 2:
        return Markup("")

    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in line_points)
    area = " ".join(
        [
            f"{line_points[0][0]:.2f},{height - padding:.2f}",
            *[f"{x:.2f},{y:.2f}" for x, y in line_points],
            f"{line_points[-1][0]:.2f},{height - padding:.2f}",
        ]
    )
    gradient_id = uuid.uuid4().hex
    svg = f"""
    <svg viewBox=\"0 0 {width} {height}\" aria-hidden=\"true\" role=\"img\" class=\"sparkline\">
      <defs>
        <linearGradient id=\"{gradient_id}\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">
          <stop offset=\"0%\" stop-color=\"{fill}\" stop-opacity=\"0.45\" />
          <stop offset=\"100%\" stop-color=\"{fill}\" stop-opacity=\"0\" />
        </linearGradient>
      </defs>
      <polygon points=\"{area}\" fill=\"url(#{gradient_id})\"></polygon>
      <polyline points=\"{line}\" fill=\"none\" stroke=\"{stroke}\" stroke-width=\"3\" stroke-linecap=\"round\" stroke-linejoin=\"round\"></polyline>
    </svg>
    """
    return Markup(svg)


def build_property_result(form: Dict[str, str]) -> Dict[str, Any]:
    address = clean_optional_text(form.get("address"))
    comp_count = clamp_int(form.get("comp_count"), DEFAULT_COMP_COUNT, minimum=1, maximum=25)
    max_radius = clamp_int(form.get("max_radius"), DEFAULT_MAX_RADIUS, minimum=1, maximum=50)

    property_record = fetch_property_record(address)
    if not property_record:
        raise RuntimeError("No property record matched that address.")

    canonical_address = property_record.get("formattedAddress") or address
    value_payload = fetch_value_estimate(canonical_address, comp_count=comp_count, max_radius=max_radius)
    rent_payload = fetch_rent_estimate(canonical_address, comp_count=comp_count, max_radius=max_radius)

    sale_df = comparables_to_dataframe(value_payload.get("comparables") or [], "Sale Price")
    rent_df = comparables_to_dataframe(rent_payload.get("comparables") or [], "Rent")
    tax_assessment_df = year_value_dict_to_dataframe(
        property_record.get("taxAssessments"),
        primary_label="Assessed Value",
        extra_labels={"land": "Land", "improvements": "Improvements"},
    )
    property_tax_df = year_value_dict_to_dataframe(
        property_record.get("propertyTaxes"),
        primary_label="Property Tax",
    )

    features = property_record.get("features") or {}
    owner = property_record.get("owner") or {}
    owner_names = ", ".join(owner.get("names") or [])
    mailing_address = ((owner.get("mailingAddress") or {}).get("formattedAddress"))

    fact_cards = [
        metric("Bedrooms", format_number(property_record.get("bedrooms"))),
        metric("Bathrooms", format_number(property_record.get("bathrooms"), decimals=1)),
        metric("Living Area", format_number(property_record.get("squareFootage"), suffix=" sf")),
        metric("Lot Size", format_number(property_record.get("lotSize"), suffix=" sf")),
        metric("Year Built", format_number(property_record.get("yearBuilt"))),
        metric("Owner Occupied", format_bool(property_record.get("ownerOccupied"))),
    ]

    estimate_cards = [
        {
            "label": "Value Estimate",
            "value": format_currency(value_payload.get("price")),
            "band": f"Range {format_currency(value_payload.get('priceRangeLow'))} to {format_currency(value_payload.get('priceRangeHigh'))}",
            "meta": f"{len(sale_df)} sale comps within {max_radius} miles",
            "tone": "value",
        },
        {
            "label": "Rent Estimate",
            "value": format_currency(rent_payload.get("rent"), suffix="/mo"),
            "band": f"Range {format_currency(rent_payload.get('rentRangeLow'), suffix='/mo')} to {format_currency(rent_payload.get('rentRangeHigh'), suffix='/mo')}",
            "meta": f"{len(rent_df)} rental comps within {max_radius} miles",
            "tone": "rent",
        },
    ]

    detail_groups = [
        {
            "title": "Core Record",
            "items": detail_rows(
                [
                    ("Property Type", property_record.get("propertyType")),
                    ("Subdivision", property_record.get("subdivision")),
                    ("Zoning", property_record.get("zoning")),
                    ("County", property_record.get("county")),
                    ("Assessor ID", property_record.get("assessorID")),
                    ("Legal Description", property_record.get("legalDescription")),
                ]
            ),
        },
        {
            "title": "Features",
            "items": detail_rows(
                [
                    ("Garage", features.get("garage")),
                    ("Garage Spaces", features.get("garageSpaces")),
                    ("Garage Type", features.get("garageType")),
                    ("Cooling", features.get("cooling")),
                    ("Cooling Type", features.get("coolingType")),
                    ("Heating", features.get("heating")),
                    ("Heating Type", features.get("heatingType")),
                    ("Roof Type", features.get("roofType")),
                    ("Exterior Type", features.get("exteriorType")),
                    ("Rooms", features.get("roomCount")),
                    ("Floors", features.get("floorCount")),
                    ("Units", features.get("unitCount")),
                ]
            ),
        },
        {
            "title": "Ownership",
            "items": detail_rows(
                [
                    ("Owner", owner_names),
                    ("Owner Type", owner.get("type")),
                    ("Mailing Address", mailing_address),
                ]
            ),
        },
    ]

    return {
        "address": canonical_address,
        "city_state": ", ".join(
            part for part in [property_record.get("city"), property_record.get("state")] if part
        )
        + (f" {property_record.get('zipCode')}" if property_record.get("zipCode") else ""),
        "comp_count": comp_count,
        "max_radius": max_radius,
        "fact_cards": fact_cards,
        "estimate_cards": estimate_cards,
        "detail_groups": detail_groups,
        "tax_assessments": table_payload(
            tax_assessment_df,
            limit=10,
            formatters={
                "Year": format_number,
                "Assessed Value": format_currency,
                "Land": format_currency,
                "Improvements": format_currency,
            },
        ),
        "property_taxes": table_payload(
            property_tax_df,
            limit=10,
            formatters={
                "Year": format_number,
                "Property Tax": format_currency,
            },
        ),
        "sale_comps": {
            "title": "Sales Comparables",
            "download_token": register_download(
                sale_df,
                f"property_sales_comps_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            ),
            "table": table_payload(
                sale_df,
                limit=10,
                formatters={
                    "Sale Price": format_currency,
                    "Beds": format_number,
                    "Baths": lambda value: format_number(value, decimals=1),
                    "Sq Ft": format_number,
                    "$/Sq Ft": lambda value: format_currency(value, decimals=2),
                    "Distance (mi)": lambda value: format_number(value, decimals=2),
                    "Correlation": lambda value: format_number(to_number(value) * 100 if to_number(value) is not None else None, decimals=1, suffix="%"),
                    "Days on Market": format_number,
                    "Listed Date": format_date,
                    "Last Seen": format_date,
                },
            ),
        },
        "rent_comps": {
            "title": "Rental Comparables",
            "download_token": register_download(
                rent_df,
                f"property_rent_comps_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            ),
            "table": table_payload(
                rent_df,
                limit=10,
                formatters={
                    "Rent": lambda value: format_currency(value, suffix="/mo"),
                    "Beds": format_number,
                    "Baths": lambda value: format_number(value, decimals=1),
                    "Sq Ft": format_number,
                    "$/Sq Ft": lambda value: format_currency(value, decimals=2),
                    "Distance (mi)": lambda value: format_number(value, decimals=2),
                    "Correlation": lambda value: format_number(to_number(value) * 100 if to_number(value) is not None else None, decimals=1, suffix="%"),
                    "Days on Market": format_number,
                    "Listed Date": format_date,
                    "Last Seen": format_date,
                },
            ),
        },
    }


def build_listing_dataset(kind: str, df: pd.DataFrame, limit: int) -> Dict[str, Any]:
    title = "Active Sale Listings" if kind == "sale" else "Active Rental Listings"
    value_label = "List Price" if kind == "sale" else "Rent"
    download_name = f"{kind}_listings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    summary_cards = [
        metric("Matches", format_number(len(df))),
        metric(f"Median {value_label}", median_display(df.get(value_label, pd.Series(dtype=float)), format_currency)),
        metric("Median $/Sq Ft", median_display(df.get("$/Sq Ft", pd.Series(dtype=float)), lambda value: format_currency(value, decimals=2))),
        metric("Median DOM", median_display(df.get("Days on Market", pd.Series(dtype=float)), format_number)),
    ]

    return {
        "title": title,
        "download_token": register_download(df, download_name),
        "summary_cards": summary_cards,
        "table": table_payload(
            df,
            limit=limit,
            formatters={
                value_label: lambda value: format_currency(value, suffix="/mo" if kind == "rental" else ""),
                "Beds": format_number,
                "Baths": lambda value: format_number(value, decimals=1),
                "Sq Ft": format_number,
                "$/Sq Ft": lambda value: format_currency(value, decimals=2),
                "Lot Size": format_number,
                "Days on Market": format_number,
                "Listed Date": format_date,
                "Last Seen": format_date,
            },
        ),
    }


def build_listing_result(form: Dict[str, str]) -> Dict[str, Any]:
    search_scope = clean_optional_text(form.get("search_scope")) or "both"
    if search_scope not in {"sale", "rental", "both"}:
        search_scope = "both"

    zip_code = clean_optional_text(form.get("zip_code"))
    city = clean_optional_text(form.get("city"))
    state = clean_optional_text(form.get("state"))
    bedrooms = clean_optional_text(form.get("bedrooms"))
    bathrooms = clean_optional_text(form.get("bathrooms"))
    limit = clamp_int(form.get("limit"), DEFAULT_LISTING_LIMIT, minimum=1, maximum=50)

    scopes = [search_scope] if search_scope != "both" else ["sale", "rental"]
    datasets = []
    for kind in scopes:
        records = fetch_listing_search_results(
            kind,
            zip_code=zip_code,
            city=city,
            state=state,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            limit=limit,
        )
        value_label = "List Price" if kind == "sale" else "Rent"
        df = listings_to_dataframe(records, value_label)
        datasets.append(build_listing_dataset(kind, df, limit=min(limit, 12)))

    geography = zip_code or ", ".join(part for part in [city, state] if part)
    return {
        "search_scope": search_scope,
        "geography": geography,
        "filters": {
            "bedrooms": bedrooms or "Any",
            "bathrooms": bathrooms or "Any",
            "limit": str(limit),
        },
        "datasets": datasets,
    }


def build_market_panel(
    section: Dict[str, Any],
    *,
    mode: str,
    tone: str,
    fill: str,
) -> Dict[str, Any]:
    snapshot = select_property_type_snapshot(section.get("dataByPropertyType")) or section
    history_df = market_history_to_dataframe(section.get("history"), mode=mode)
    metric_value = "Median Price" if mode == "sale" else "Median Rent"

    if mode == "sale":
        cards = [
            metric("Median Price", format_currency(snapshot.get("medianPrice"))),
            metric("Median $/Sq Ft", format_currency(snapshot.get("medianPricePerSquareFoot"), decimals=2)),
            metric("Median DOM", format_number(snapshot.get("medianDaysOnMarket"))),
            metric("New Listings", format_number(snapshot.get("newListings"))),
            metric("Inventory", format_number(snapshot.get("totalListings"))),
        ]
        formatters = {
            "Median Price": format_currency,
            "Average Price": format_currency,
            "Median $/Sq Ft": lambda value: format_currency(value, decimals=2),
            "Median Days on Market": format_number,
            "New Listings": format_number,
            "Total Listings": format_number,
        }
    else:
        cards = [
            metric("Median Rent", format_currency(snapshot.get("medianRent"), suffix="/mo")),
            metric("Median Rent/Sq Ft", format_currency(snapshot.get("medianRentPerSquareFoot"), decimals=2)),
            metric("Median DOM", format_number(snapshot.get("medianDaysOnMarket"))),
            metric("New Listings", format_number(snapshot.get("newListings"))),
            metric("Inventory", format_number(snapshot.get("totalListings"))),
        ]
        formatters = {
            "Median Rent": lambda value: format_currency(value, suffix="/mo"),
            "Average Rent": lambda value: format_currency(value, suffix="/mo"),
            "Median Rent/Sq Ft": lambda value: format_currency(value, decimals=2),
            "Median Days on Market": format_number,
            "New Listings": format_number,
            "Total Listings": format_number,
        }

    return {
        "title": "For Sale" if mode == "sale" else "For Rent",
        "updated": format_date(section.get("lastUpdatedDate")),
        "cards": cards,
        "trend_chart": build_sparkline(history_df.get(metric_value, pd.Series(dtype=float)).tolist(), stroke=tone, fill=fill),
        "table": table_payload(history_df, limit=12, formatters=formatters),
        "download_token": register_download(
            history_df,
            f"{mode}_market_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        ),
    }


def build_market_result(form: Dict[str, str]) -> Dict[str, Any]:
    zip_code = clean_optional_text(form.get("zip_code"))
    payload = fetch_market_stats(zip_code)

    sale_panel = build_market_panel(
        payload.get("saleData") or {},
        mode="sale",
        tone="#a74d2d",
        fill="#db8b67",
    )
    rent_panel = build_market_panel(
        payload.get("rentalData") or {},
        mode="rental",
        tone="#1f6b62",
        fill="#69a89f",
    )

    return {
        "zip_code": payload.get("zipCode") or zip_code,
        "sale_panel": sale_panel,
        "rent_panel": rent_panel,
    }


@app.get("/")
def index():
    return render_dashboard()


@app.post("/property-intelligence")
def property_intelligence():
    form = {
        "address": request.form.get("address", ""),
        "comp_count": request.form.get("comp_count", str(DEFAULT_COMP_COUNT)),
        "max_radius": request.form.get("max_radius", str(DEFAULT_MAX_RADIUS)),
    }
    try:
        result = build_property_result(form)
        return render_dashboard(
            property_form=form,
            results={"property": result, "listings": None, "market": None},
            focus_section=SECTION_IDS["property"],
        )
    except Exception as exc:
        return render_dashboard(
            property_form=form,
            errors={"property": str(exc), "listings": None, "market": None},
            focus_section=SECTION_IDS["property"],
        )


@app.post("/listing-radar")
def listing_radar():
    form = {
        "search_scope": request.form.get("search_scope", "both"),
        "zip_code": request.form.get("zip_code", ""),
        "city": request.form.get("city", ""),
        "state": request.form.get("state", ""),
        "bedrooms": request.form.get("bedrooms", DEFAULT_BEDROOMS),
        "bathrooms": request.form.get("bathrooms", DEFAULT_BATHROOMS),
        "limit": request.form.get("limit", str(DEFAULT_LISTING_LIMIT)),
    }
    try:
        result = build_listing_result(form)
        return render_dashboard(
            listing_form=form,
            results={"property": None, "listings": result, "market": None},
            focus_section=SECTION_IDS["listings"],
        )
    except Exception as exc:
        return render_dashboard(
            listing_form=form,
            errors={"property": None, "listings": str(exc), "market": None},
            focus_section=SECTION_IDS["listings"],
        )


@app.post("/market-pulse")
def market_pulse():
    form = {
        "zip_code": request.form.get("zip_code", DEFAULT_MARKET_ZIP),
    }
    try:
        result = build_market_result(form)
        return render_dashboard(
            market_form=form,
            results={"property": None, "listings": None, "market": result},
            focus_section=SECTION_IDS["market"],
        )
    except Exception as exc:
        return render_dashboard(
            market_form=form,
            errors={"property": None, "listings": None, "market": str(exc)},
            focus_section=SECTION_IDS["market"],
        )


@app.get("/download/<string:token>")
def download(token: str):
    csv_bytes = EXPORTS.get(token)
    download_name = EXPORT_META.get(token, "rentcast_export.csv")
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
