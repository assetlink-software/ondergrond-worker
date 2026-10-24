# Ondergrond NL — worker

Kleine Python-service die adres/coördinaat + gebied omzet in een CAD-klare DXF of DWG (RD New, meters) uit PDOK (BGT, BAG, Kadaster).

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
Voeg `"formaat":"dwg"` toe voor een DWG (AutoCAD 2018). Het antwoord bevat `url` (blijft werken: het bestand wordt bij download opnieuw opgebouwd), `objecten`, `lagen` (telling per laag) en `waarschuwingen`.

## Gratis hosten
Alle opties gebruiken deze Dockerfile zonder aanpassing.

| Optie | Hoe | Opmerking |
|---|---|---|
| Google Cloud Run (europe-west4, NL) | `gcloud run deploy ondergrond-worker --source . --region europe-west4 --allow-unauthenticated --memory 1Gi` | Ruime gratis bundel, geen slaapstand, aanrader |
| Render (Frankfurt) | New Web Service → Docker → deze map | Gratis tier slaapt na 15 min |
| Hugging Face Spaces (Docker) | Space aanmaken, bestanden uploaden | Gratis, slaapt na 48 uur |
| Oracle Always Free (Amsterdam) | VM + `docker build -t ondergrond . && docker run -p 8080:8080 ondergrond` | Echte server, gratis |

Omgevingsvariabelen: `PUBLIC_BASE` (publieke URL van de worker), `RATE_LIMIT_PER_HOUR` (standaard 30), `MAX_RADIUS_M` (standaard 2000), `DWG_MAX_DXF_MB` (standaard 25), `DWG_TIMEOUT_S` (standaard 90), `CACHE_MAX_MB` (standaard 120). Geef de service 2 GiB geheugen als je grote DWG's wilt toestaan.

## DWG
DWG wordt gemaakt door `dwg/dxf2dwg.mjs` met [acad-ts](https://github.com/node-projects/acad-ts) (MIT, TypeScript-port van [ACadSharp](https://github.com/DomCR/ACadSharp)), aangeroepen als Node-subproces. Geen ODA- of Autodesk-licentie nodig.
- `dwg/patch-acad.mjs` maakt de DWG-schrijver van acad-ts 3.6.0 lineair i.p.v. kwadratisch (17 MB DXF: 66 s → 7 s, inhoud identiek). Het script stopt met een fout als acad-ts verandert; controleer dan of de fix upstream al zit.
- Versie vastgezet in `dwg/package-lock.json`. Bij een update: test met een echte tekening en open hem in AutoCAD/BricsCAD.

## Endpoints
- `POST /generate` — zie main.py voor het schema
- `GET /dxf/{naam}?q=` en `GET /dwg/{naam}?q=` — download (de `url` uit /generate)
- `GET /geocode?q=` — PDOK Locatieserver
- `GET /lagen` — beschikbare laaggroepen
- `GET /health`

## Lagen
`layers.py` is de enige plek die bepaalt welke PDOK-collecties worden opgehaald en op welke DXF-laag (naam, kleur, lijntype, arcering) ze landen. Houd `src/config/layers.ts` in de frontend hiermee gelijk.
