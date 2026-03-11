import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

BASE_URL = "https://api.rentcast.io/v1"

DEFAULT_ZIPS = ["85119", "85120", "85207", "85208", "85209"]
DEFAULT_PROPERTY_TYPES = ["Single Family"]
DEFAULT_BEDROOMS = "3"
DEFAULT_BATHROOMS = ""
DEFAULT_OUT_PATH = "output/rent_comps_3br_sfh_townhouse.csv"
AHWATUKEE_ZIPS = ["85044", "85045", "85048"]
SALES_OUT_PATH = "Ahwatukee_SFH_Sales_Last12Months_3-4Beds.xlsx"
DEFAULT_SALES_BEDROOMS = ["3", "4"]
SALES_LOOKBACK_DAYS = 365
PAGE_SIZE = 500


def rc_get_response(path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """RentCast GET that returns the full Response object."""
    api_key = os.getenv("RENTCAST_API_KEY")
    if not api_key:
        raise RuntimeError("Missing RENTCAST_API_KEY in .env")

    headers = {
        "accept": "application/json",
        "X-Api-Key": api_key,
    }

    url = f"{BASE_URL}{path}"
    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code >= 400:
        raise RuntimeError(f"Request failed: {response.status_code} {response.text}")

    return response


def rc_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """RentCast GET with API key + basic error handling."""
    return rc_get_response(path, params=params).json()


def first_present(record: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def parse_iso_date(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed


def fetch_paginated_records(
    path: str,
    params: Dict[str, Any],
    page_size: int = PAGE_SIZE,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    offset = 0

    while True:
        request_params = dict(params)
        request_params.update(
            {
                "limit": page_size,
                "offset": offset,
                "includeTotalCount": "true",
            }
        )
        response = rc_get_response(path, params=request_params)
        payload = response.json()

        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected response from {path}: expected list")

        records.extend(payload)

        total_count_header = response.headers.get("X-Total-Count") or response.headers.get("x-total-count")
        if total_count_header and total_count_header.isdigit():
            total_count = int(total_count_header)
            if len(records) >= total_count:
                break

        if len(payload) < page_size:
            break

        offset += page_size

    return records


def run_ahwatukee_sfh_sales_last_12_months(
    target_zips: Optional[List[str]] = None,
    target_bedrooms: Optional[List[str]] = None,
    lookback_days: int = SALES_LOOKBACK_DAYS,
    out_path: str = SALES_OUT_PATH,
) -> pd.DataFrame:
    load_dotenv()
    target_zips = target_zips or AHWATUKEE_ZIPS
    target_bedrooms = target_bedrooms or DEFAULT_SALES_BEDROOMS

    min_days = 1
    max_days = max(1, int(lookback_days))
    cutoff_date = datetime.utcnow() - timedelta(days=max_days)

    all_records: List[Dict[str, Any]] = []
    for zip_code in target_zips:
        for bedrooms in target_bedrooms:
            params = {
                "zipCode": zip_code,
                "propertyType": "Single Family",
                "bedrooms": bedrooms,
                "saleDateRange": f"{min_days}-{max_days}",
            }
            all_records.extend(fetch_paginated_records("/properties", params))

    rows: List[Dict[str, Any]] = []
    seen = set()
    for record in all_records:
        sale_date = parse_iso_date(
            first_present(record, "lastSaleDate", "lastSoldDate", "saleDate", "soldDate")
        )
        if sale_date is None or sale_date.to_pydatetime().replace(tzinfo=None) < cutoff_date:
            continue

        address = first_present(record, "formattedAddress", "address", "addressLine1")
        sale_price = first_present(record, "lastSalePrice", "lastSoldPrice", "salePrice", "price")

        if not address or not sale_price:
            continue

        dedupe_key = str(first_present(record, "id") or "").strip().lower()
        if not dedupe_key:
            dedupe_key = str(address).strip().lower()

        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        rows.append(
            {
                "Bedrooms": first_present(record, "bedrooms", "beds"),
                "Bathrooms": first_present(record, "bathrooms", "baths"),
                "Square Footage": first_present(record, "squareFootage", "sqft"),
                "Address": address,
                "Sale Price": sale_price,
            }
        )

    df = pd.DataFrame(
        rows,
        columns=["Bedrooms", "Bathrooms", "Square Footage", "Address", "Sale Price"],
    )
    df.to_excel(out_path, index=False)
    print(f"Saved: {out_path} ({len(df)} rows)")
    return df


def safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def property_lookup_by_address(address: str) -> Optional[Dict[str, Any]]:
    """
    Uses /properties endpoint to fetch features like garageSpaces and pool.
    /properties returns a list; take the first match.
    """
    data = rc_get("/properties", params={"address": address, "limit": 1})
    if isinstance(data, list) and len(data) > 0:
        return data[0]
    return None


def extract_fields(listing: Dict[str, Any], prop: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # Listing fields
    formatted_address = listing.get("formattedAddress")
    year_built = listing.get("yearBuilt")
    sqft = listing.get("squareFootage")
    beds = listing.get("bedrooms")
    baths = listing.get("bathrooms")
    asking_rent = listing.get("price")
    lot_size = listing.get("lotSize")

    # Enrichment from property record schema (features.*)
    garage_spaces = None
    pool = None

    if prop:
        features = prop.get("features") or {}
        garage_spaces = features.get("garageSpaces")
        pool = features.get("pool")

        # If listing lotSize missing, fill from property record
        if lot_size in (None, 0):
            lot_size = prop.get("lotSize")

    rent_per_sqft = None
    if asking_rent and sqft:
        rent_per_sqft = round(float(asking_rent) / float(sqft), 4)

    # Furnished: not always in schema; keep unknown for MVP
    furnished = "Unknown"

    return {
        "address": formatted_address,
        "year_built": year_built,
        "home_sqft": sqft,
        "bedrooms": beds,
        "bathrooms": baths,
        "garage_spaces": garage_spaces,
        "asking_rent": asking_rent,
        "rent_per_sqft": rent_per_sqft,
        "furnished": furnished,
        "pool": pool,
        "lot_sqft": lot_size,
        "status": listing.get("status"),
        "days_on_market": listing.get("daysOnMarket"),
        "last_seen_date": listing.get("lastSeenDate"),
        "listing_id": listing.get("id"),
        "zipCode": listing.get("zipCode"),
        "city": listing.get("city"),
        "state": listing.get("state"),
        "propertyType": listing.get("propertyType"),
    }


def run_comps(
    target_zips: Optional[List[str]] = None,
    target_property_types: Optional[List[str]] = None,
    target_bedrooms: str = DEFAULT_BEDROOMS,
    max_enrich: int = 15,
    out_path: str = DEFAULT_OUT_PATH,
) -> pd.DataFrame:
    load_dotenv()
    os.makedirs("output", exist_ok=True)

    # Target search criteria
    target_zips = target_zips or DEFAULT_ZIPS
    target_property_types = target_property_types or DEFAULT_PROPERTY_TYPES

    all_listings: List[Dict[str, Any]] = []

    for z in target_zips:
        for pt in target_property_types:
            listings = rc_get(
                "/listings/rental/long-term",
                params={
                    "zipCode": z,
                    "status": "Active",
                    "propertyType": pt,
                    "bedrooms": target_bedrooms,
                    "limit": 500,
                    "offset": 0,
                },
            )
            if isinstance(listings, list):
                all_listings.extend(listings)

    # De-duplicate by listing id
    seen = set()
    deduped = []
    for item in all_listings:
        lid = item.get("id")
        if lid and lid in seen:
            continue
        if lid:
            seen.add(lid)
        deduped.append(item)

    listings = deduped
    print(f"Pulled {len(listings)} listings across target ZIPs")

    # If still 0, save an empty file and exit gracefully
    if not listings:
        df = pd.DataFrame([])
        df.to_csv(out_path, index=False)
        print(f"Saved: {out_path} (0 rows)")
        return df

    # ✅ Enrich only first N rows to avoid blowing up API request count
    max_enrich = min(len(listings), max_enrich)
    rows: List[Dict[str, Any]] = []

    for i, listing in enumerate(listings):
        addr = listing.get("formattedAddress")
        prop = None

        if addr and i < max_enrich:
            try:
                prop = property_lookup_by_address(addr)
                time.sleep(0.15)  # gentle pacing
            except Exception:
                prop = None

        rows.append(extract_fields(listing, prop))

    df = pd.DataFrame(rows)

    # Save output
    df.to_csv(out_path, index=False)
    print(f"Saved: {out_path} ({len(df)} rows)")
    return df


def run_mls_active_listings(
    target_zips: Optional[List[str]] = None,
    target_property_types: Optional[List[str]] = None,
    target_bedrooms: Optional[str] = DEFAULT_BEDROOMS,
    target_bathrooms: Optional[str] = DEFAULT_BATHROOMS,
    out_path: str = "output/rentcast_mls_listings.csv",
) -> pd.DataFrame:
    """Fetch active long-term rental listings and export the rent comps format."""
    load_dotenv()
    os.makedirs("output", exist_ok=True)

    target_zips = target_zips or DEFAULT_ZIPS
    target_property_types = target_property_types or DEFAULT_PROPERTY_TYPES
    target_bedrooms = str(target_bedrooms).strip() if target_bedrooms is not None else ""
    target_bathrooms = str(target_bathrooms).strip() if target_bathrooms is not None else ""

    all_records: List[Dict[str, Any]] = []
    for zip_code in target_zips:
        for property_type in target_property_types:
            params = {
                "zipCode": zip_code,
                "status": "Active",
                "propertyType": property_type,
                "limit": PAGE_SIZE,
            }
            if target_bedrooms:
                params["bedrooms"] = target_bedrooms
            if target_bathrooms:
                params["bathrooms"] = target_bathrooms

            all_records.extend(fetch_paginated_records("/listings/rental/long-term", params=params))

    deduped_records = []
    seen = set()
    for record in all_records:
        listing_id = record.get("id")
        if listing_id and listing_id in seen:
            continue
        if listing_id:
            seen.add(listing_id)
        deduped_records.append(record)

    if not deduped_records:
        df = pd.DataFrame(
            columns=[
                "address",
                "year_built",
                "home_sqft",
                "bedrooms",
                "bathrooms",
                "garage_spaces",
                "asking_rent",
                "rent_per_sqft",
                "furnished",
                "pool",
                "lot_sqft",
                "status",
                "days_on_market",
                "last_seen_date",
                "listing_id",
                "zipCode",
                "city",
                "state",
                "propertyType",
            ]
        )
        df.to_csv(out_path, index=False)
        print(f"Saved: {out_path} (0 rows)")
        return df

    # Keep enrichment bounded to avoid too many lookup calls.
    max_enrich = min(len(deduped_records), 15)
    rows: List[Dict[str, Any]] = []
    for idx, record in enumerate(deduped_records):
        address = first_present(record, "formattedAddress", "address", "addressLine1")
        if not address:
            continue

        prop = None
        if idx < max_enrich:
            try:
                prop = property_lookup_by_address(address)
            except Exception:
                prop = None

        row = extract_fields(record, prop)
        if not row.get("asking_rent"):
            row["asking_rent"] = first_present(record, "price", "askingPrice")
        if row["rent_per_sqft"] is None and row["asking_rent"] and row["home_sqft"]:
            try:
                row["rent_per_sqft"] = round(float(row["asking_rent"]) / float(row["home_sqft"]), 4)
            except Exception:
                pass

        if not row.get("address"):
            row["address"] = address

        rows.append(row)

    columns = [
        "address",
        "year_built",
        "home_sqft",
        "bedrooms",
        "bathrooms",
        "garage_spaces",
        "asking_rent",
        "rent_per_sqft",
        "furnished",
        "pool",
        "lot_sqft",
        "status",
        "days_on_market",
        "last_seen_date",
        "listing_id",
        "zipCode",
        "city",
        "state",
        "propertyType",
    ]
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        df.to_csv(out_path, index=False)
        print(f"Saved: {out_path} ({len(df)} rows)")
        return df

    df.to_csv(out_path, index=False)
    print(f"Saved: {out_path} ({len(df)} rows)")
    return df


def run_sales_properties_last_12_months(
    target_zips: Optional[List[str]] = None,
    target_property_types: Optional[List[str]] = None,
    target_bedrooms: Optional[str] = DEFAULT_BEDROOMS,
    target_bathrooms: Optional[str] = DEFAULT_BATHROOMS,
    lookback_days: int = SALES_LOOKBACK_DAYS,
    out_path: str = SALES_OUT_PATH,
) -> pd.DataFrame:
    """Fetch sold/last-sale properties and normalize output to the standard sales columns."""
    load_dotenv()
    os.makedirs("output", exist_ok=True)

    target_zips = target_zips or AHWATUKEE_ZIPS
    target_property_types = target_property_types or ["Single Family"]
    target_bedrooms = str(target_bedrooms).strip() if target_bedrooms is not None else ""
    target_bathrooms = str(target_bathrooms).strip() if target_bathrooms is not None else ""
    min_days = 1
    max_days = max(1, int(lookback_days))
    cutoff_date = datetime.utcnow() - timedelta(days=max_days)

    all_records: List[Dict[str, Any]] = []
    for zip_code in target_zips:
        for property_type in target_property_types:
            params = {
                "zipCode": zip_code,
                "propertyType": property_type,
                "saleDateRange": f"{min_days}-{max_days}",
            }
            if target_bedrooms:
                params["bedrooms"] = target_bedrooms
            if target_bathrooms:
                params["bathrooms"] = target_bathrooms

            all_records.extend(fetch_paginated_records("/properties", params=params))

    rows: List[Dict[str, Any]] = []
    seen = set()
    for record in all_records:
        sale_date = parse_iso_date(
            first_present(record, "lastSaleDate", "lastSoldDate", "saleDate", "soldDate")
        )
        if sale_date is None or sale_date.to_pydatetime().replace(tzinfo=None) < cutoff_date:
            continue

        listing_id = record.get("id")
        if listing_id and listing_id in seen:
            continue
        if listing_id:
            seen.add(listing_id)

        address = first_present(record, "formattedAddress", "address", "addressLine1")
        sale_price = first_present(record, "lastSalePrice", "lastSoldPrice", "salePrice", "price")
        if not address or sale_price is None:
            continue

        rows.append(
            {
                "Bedrooms": first_present(record, "bedrooms", "beds"),
                "Bathrooms": first_present(record, "bathrooms", "baths"),
                "Square Footage": first_present(record, "squareFootage", "sqft"),
                "Address": address,
                "Sale Price": sale_price,
            }
        )

    df = pd.DataFrame(
        rows,
        columns=["Bedrooms", "Bathrooms", "Square Footage", "Address", "Sale Price"],
    )
    df.to_csv(out_path, index=False)
    print(f"Saved: {out_path} ({len(df)} rows)")
    return df


def main():
    df = run_ahwatukee_sfh_sales_last_12_months()
    print(f"Rows: {len(df)}")


if __name__ == "__main__":
    main()
