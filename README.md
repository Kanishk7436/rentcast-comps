# RentCast Rental Comps Extractor

## Summary
This project is a Flask web app that lets users query RentCast long‑term rental listings by ZIP code, bedrooms, bathrooms, and property type. Results are pulled directly from RentCast and exported as CSV from the full MLS payload.

## What It Can Do
- Pull active long‑term rental listings for selected ZIP codes and beds/baths, for **Single Family** only.
- Return full RentCast listing payload fields and preview them in the web UI.
- Allow CSV export of the query output for underwriting and market review.
- Provide a lightweight web interface with employer-ready access controls.

## Output (CSV Fields)
Fields are dynamic and come from the RentCast listing response schema.

## Cost & API Usage
This script consumes RentCast API calls; total cost depends on your plan.

**Approximate calls per run (current setup):**
- Listing calls depend on selected ZIPs, property types, filters, and pagination.

**Fill in pricing:**
- Cost per call: ______
- Estimated cost per run: ______
- Estimated monthly cost: ______

Call volume scales with number of ZIPs, property types, filters, and pagination.

## Deploy on Render

1. Commit and push your project to GitHub.
2. In Render, click **New +** → **Web Service** → **Build and deploy from a Git repository**.
3. Select your repo.
4. Render will detect the service type from `render.yaml` automatically.
5. Add environment variables:
   - `RENTCAST_API_KEY`: your RentCast API key
   - `APP_USERNAME`: optional app login username
   - `APP_PASSWORD`: optional app login password
6. Deploy.

Notes:
- App listens on Render’s dynamic `PORT` automatically.
- The app writes CSVs to `output/` at runtime and serves them for download.
- If CSV download is not working, ensure `output/` exists in the container (it is created at run-time by the app code).

## Quick local run

1. Create `.env` from `.env.example` and add your keys.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Start app:
   - `python app.py`
4. Open `http://localhost:8080`.

If you set `APP_USERNAME` and `APP_PASSWORD`, you'll be prompted for HTTP basic authentication.
