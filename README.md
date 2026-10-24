# Ondergrond NL — worker

Kleine Python-service die adres/coördinaat + gebied omzet in een CAD-klare DXF (RD New, meters) uit PDOK (BGT, BAG, Kadaster).

## Lokaal draaien
```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```
Test:
```bash
curl -X POST http://localhost:8080/generate -H "Content-Type: application/json" \
  -d '{"adres":"Stadhuisplein 2, Lelystad","straal_m":100,"lagen":["bgt_basis","bag_pand","brk_perceel"]}'
```
Het antwoord bevat `url` (24 uur geldig), `objecten`, `lagen` (telling per DXF-laag) en `waarschuwingen`.

## Gratis hosten
Alle opties gebruiken deze Dockerfile zonder aanpassing.

| Optie | Hoe | Opmerking |
|---|---|---|
| Google Cloud Run (europe-west4, NL) | `gcloud run deploy ondergrond-worker --source . --region europe-west4 --allow-unauthenticated --memory 1Gi` | Ruime gratis bundel, geen slaapstand, aanrader |
| Render (Frankfurt) | New Web Service → Docker → deze map | Gratis tier slaapt na 15 min |
| Hugging Face Spaces (Docker) | Space aanmaken, bestanden uploaden | Gratis, slaapt na 48 uur |
| Oracle Always Free (Amsterdam) | VM + `docker build -t ondergrond . && docker run -p 8080:8080 ondergrond` | Echte server, gratis |

Omgevingsvariabelen: `PUBLIC_BASE` (publieke URL van de worker), `FILE_TTL_HOURS` (standaard 24), `RATE_LIMIT_PER_HOUR` (standaard 30), `MAX_RADIUS_M` (standaard 2000).

## Endpoints
- `POST /generate` — zie main.py voor het schema
- `GET /files/{job_id}/{naam}` — download
- `GET /geocode?q=` — PDOK Locatieserver
- `GET /lagen` — beschikbare laaggroepen
- `GET /health`

## Lagen
`layers.py` is de enige plek die bepaalt welke PDOK-collecties worden opgehaald en op welke DXF-laag (naam, kleur, lijntype, arcering) ze landen. Houd `src/config/layers.ts` in de frontend hiermee gelijk.
