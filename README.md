# RentCast Rental Comps Extractor (3BR SFR & Townhouse)

## Summary
This project produces a standardized rental comps dataset for a defined set of ZIP codes using the RentCast API. It targets active long‑term listings for 3‑bedroom Single Family and Townhouse properties, removes duplicates, and enriches a limited subset with property features. The output is a clean CSV designed for underwriting, market rent checks, and investment memo support.

## What It Can Do
- Pull active 3BR Single Family and Townhouse rentals for selected ZIP codes.
- Deliver a normalized CSV with key underwriting fields (rent, beds/baths, sqft, lot size, year built, days on market).
- Add select property features such as garage spaces and pool where available.
- Provide a lightweight web interface with CSV download when deployed as a site.

## Output (CSV Fields)
Address, City, State, ZIP, Beds, Baths, Square Footage, Lot Size, Asking Rent, Rent per Sqft, Year Built, Garage Spaces, Pool, Status, Days on Market, Last Seen Date.

## Cost & API Usage
This script consumes RentCast API calls; total cost depends on your plan.

**Approximate calls per run (current setup):**
- Listing calls: 5 ZIPs × 2 property types = **10 calls**
- Enrichment calls: up to **15 calls**
- **Estimated total per run: ~25 calls**

**Fill in pricing:**
- Cost per call: ______
- Estimated cost per run: ______
- Estimated monthly cost: ______

Call volume scales with number of ZIPs, property types, and enrichment limit.

## Deploy on Render

1. Commit and push your project to GitHub.
2. In Render, click **New +** → **Web Service** → **Build and deploy from a Git repository**.
3. Select your repo.
4. Render will detect the service type from `render.yaml` automatically.
5. Add environment variables:
   - `RENTCAST_API_KEY`: your RentCast API key
6. Deploy.

Notes:
- App listens on `PORT` (Render injects it), and `render.yaml` sets it to `10000`.
- The app writes CSVs to `output/` at runtime and serves them for download.
- If CSV download is not working, ensure `output/` exists in the container (it is created at run-time by the app code).
