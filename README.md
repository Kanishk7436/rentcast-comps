# RentCast Comp Intelligence

AI-powered real estate comp engine built on the RentCast API — auto-pulls rental estimates, property valuations, and 12-month SFH sales history by zip code, cutting manual property research from hours to seconds with one-click CSV export.

## What It Does

- Query active long-term rental listings by ZIP code, beds, baths, and property type
- Pull rental estimates, AVM valuations, and market stats for any zip code
- Generate 12-month SFH sales history with full property details
- Export any dataset to CSV/XLSX instantly
- Password-protected web UI with HTTP basic auth for team access

## Output Fields

Every export is normalized to:

| Field | Description |
|---|---|
| Bedrooms | Bedroom count |
| Bathrooms | Bathroom count |
| Square Footage | Interior sq ft |
| Address | Full street address |
| Sale / Rent Price | Transaction or listing price |

## Quick Start

1. Copy `.env.example` → `.env` and add your `RENTCAST_API_KEY`
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python app.py`
4. Open `http://localhost:8080`

Set `APP_USERNAME` and `APP_PASSWORD` in `.env` to enable basic auth.

## Deploy on Render

1. Push repo to GitHub
2. In Render: **New +** → **Web Service** → connect repo
3. Render auto-detects config from `render.yaml`
4. Add environment variables:
   - `RENTCAST_API_KEY` — your RentCast API key
   - `APP_USERNAME` / `APP_PASSWORD` — optional basic auth
5. Deploy

## API Cost

Calls scale with the number of ZIPs, property types, and pagination depth. Check your [RentCast plan](https://rentcast.io) for per-call pricing.
