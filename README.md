# INFORVEX

INFORVEX is a local multi-agent news collection, deduplication, geographic
filtering, and transparent rule-based segregation dashboard. It does not

## NLP analytics

The sixth **News Analytics Agent** is enabled by default and runs after
geographical filtering. It analyzes stored articles once and records VADER
sentiment, TF-IDF keywords, and spaCy entities in the additive
`article_analytics` table. Set `ANALYTICS_ENABLED=false` to intentionally skip
analytics execution. The monitoring API still exposes all six agents and shows
the analytics agent as `idle` when it is disabled. Install the English spaCy
model in the backend environment before running analytics:

```powershell
.\.venv\Scripts\python.exe -m spacy download en_core_web_sm
```

The NLP Analytics page reads `/api/analytics/summary`; manual processing uses
`POST /api/analytics/run` and supports `?force=true` for reanalysis. Results
are machine-generated estimates and are never fabricated when no articles have
been analyzed. It does not
create invented news stories or infer an unknown location.

## Windows PowerShell setup

The existing Python environment is reused. Configure the backend from its
`.env.example`:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\backend
Copy-Item .env.example .env
```

Edit `backend\.env` as needed:

```env
DATABASE_URL=sqlite:///C:/Users/harit/source/repos/INFORVEX/backend/newsphere.db
NEWSSPHERE_FEEDS=https://feeds.bbci.co.uk/news/world/rss.xml,https://www.theguardian.com/world/rss,https://www.theguardian.com/business/rss,https://www.theguardian.com/technology/rss,https://www.theguardian.com/science/rss,https://www.theguardian.com/sport/rss,https://www.theguardian.com/film/rss,https://www.thehindu.com/news/national/feeder/default.rss
FRONTEND_ORIGINS=http://localhost:5173,http://localhost:5174
SCHEDULER_ENABLED=false
COLLECTION_INTERVAL_MINUTES=120
LOG_LEVEL=INFO
RAW_DATA_DIRECTORY=C:/Users/harit/source/repos/INFORVEX/backend/data/raw
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
BIGDATA_ENABLED=false
ANALYTICS_ENABLED=true
SPACY_MODEL=en_core_web_sm
```

The application loads `backend\.env` before constructing the database engine,
feed list, CORS origins, and scheduler settings. Keep credentials and private
feed URLs out of source control.

For production, set `DATABASE_URL` to a PostgreSQL connection such as
`postgresql+psycopg://user:password@host:5432/newsphere`, set
`FRONTEND_ORIGINS` to the exact HTTPS frontend origin, and set a random
`ADMIN_API_TOKEN`. Administrative collection and maintenance endpoints accept
that token as `Authorization: Bearer <token>`; leave it empty only for a
trusted local development environment. The frontend uses `VITE_API_URL` when
it is built for a separately hosted API and otherwise uses same-origin
requests; it never assumes a public localhost address.

The configured feeds cover world news, India, business, technology, science,
sports, and entertainment-oriented reporting. Feed URLs remain configuration,
not frontend code. Source names are taken from the parsed feed title and each
configured URL receives its own success, failure, article count, and last
checked status at `/api/sources`. Feed licensing, access terms, and rate
limits remain the operator's responsibility.

## Start the application

Backend terminal:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Production startup should use a process manager and multiple workers only with
the scheduler disabled in all but one dedicated worker. Run database schema
initialization during deployment, terminate HTTPS at the reverse proxy, and
send application logs and `/health` results to the deployment monitor. Do not
expose SQLite over the network. For a local SQLite backup, copy the database
file while the application is stopped (or use SQLite's online backup API);
INFORVEX retains news for 7 days through the backend cleanup job.

Frontend terminal:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\frontend
npm run dev
```

URLs:

- Dashboard: http://localhost:5173
- Health: http://localhost:8000/health
- API docs: http://localhost:8000/docs

## Core workflow

The collection workflow coordinates six agents. The first five execute in every
normal collection run; the News Analytics Agent executes by default unless
analytics has been explicitly disabled:

1. **Orchestration Agent** coordinates the run and receives the final status.
2. **Web News Scraping Agent** fetches configured RSS/Atom feeds with an
   explicit timeout and reports each failed feed.
3. **Database Management Agent** normalizes URLs, uses a URL hash uniqueness
   constraint, and inserts records through transaction savepoints.
4. **News Segregation Agent** assigns explainable keyword categories.
5. **Geographical Filtering Agent** normalizes only location metadata supplied
   by the source; it never invents missing locations.
6. **News Analytics Agent** records machine-generated sentiment, keywords, and
   entities when analytics is enabled and its dependencies and spaCy model are
   available. If `ANALYTICS_ENABLED=false`, it is intentionally skipped while
   remaining visible as `idle` in agent monitoring.

Empty feed configuration is reported as a failed collection with skipped
downstream stages. Partial feed failures produce a `partial` run and preserve
the feed-level error details.

## Geography

Dropdown options come from the maintained offline reference file
`backend\data\geography.json`, not from currently stored articles. The
included dataset contains all ISO 3166-1 country names, plus a deliberately
partial, maintainable set of first-level administrative areas and districts.
It does not claim worldwide district coverage. Article filtering uses the
article's own country/state/district metadata. Unknown metadata remains
`Unknown`.

The dashboard loads countries independently, then states/provinces and
districts hierarchically. The Apply Filters button sends search, category,
source, geography, and date parameters to `/api/news`. Date ranges are
inclusive and use UTC calendar boundaries. The Date field selector can use
either `publication` (the source-provided publication/updated timestamp) or
`collected` (the first-fetched timestamp). Articles without a usable source
date retain a null `publication_time` and are labelled with their collected
time in the UI.

## Tests and build

Run the isolated backend tests:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\backend
.\.venv\Scripts\python.exe -m pytest -v
```

Run backend compilation:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
```

Run frontend lint and production build:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\frontend
npm run lint
npm run build
```

Verification results are intentionally not recorded here; run the commands
above against the current checkout.

## Optional Big Data modules

`backend\app\bigdata\spark_pipeline.py` contains two separate processors:

- `process_jsonl`: functioning standard-library JSONL deduplication and
  aggregation; no Spark installation is required.
- `process_with_pyspark`: lazy optional Spark implementation; it raises a
  clear error when PySpark is not installed and is not imported by the API.

The Kafka producer is an optional interface and is not required by the core
API. No live Kafka broker or Spark runtime was available for verification, so
neither is claimed as tested. The core dashboard does not depend on either
component.

## Known limitations

- The reference geography dataset contains all country names but selected
  administrative areas for India, the United States, the United Kingdom,
  Australia, Canada, Germany, and Japan; it is not a complete worldwide
  district database. The source and last-checked date are recorded in
  `backend\data\geography.json`.
- Location resolution prefers structured event metadata. Text matching is
  accepted only for a unique reference place with an event-context cue;
  mentioned-only places, publisher regions, and feed sections remain Unknown.
- Alembic migrations and live PostgreSQL deployment are not yet implemented.
- SQLAlchemy schema initialization and additive compatibility changes are used
  for this project; a production team should adopt a migration runner before
  making destructive schema changes.
- Live external feed collection, Kafka, PySpark, and Docker infrastructure
  were not part of the automated verification run.
- The test suite is isolated and covers the core behavior, but it is not a
  production-scale load or integration test suite.

See [SOURCES_AND_ATTRIBUTION.md](./SOURCES_AND_ATTRIBUTION.md) for source and
geography attribution notes.

## SQLite backup

Before upgrading or manually editing the local database, make a copy with
PowerShell. This does not alter the live database:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\backend
New-Item -ItemType Directory -Force .\backups
Copy-Item .\newsphere.db ".\backups\newsphere-$(Get-Date -Format yyyyMMdd-HHmmss).db"
```

INFORVEX uses a 7-day news retention policy. The backend cleanup job runs once
every 24 hours; changing the collection interval does not change retention.
