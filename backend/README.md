# INFORVEX backend

Create local configuration from the checked-in example:

```powershell
cd C:\Users\harit\source\repos\INFORVEX\backend
Copy-Item .env.example .env
```

Edit `.env` before starting. The application loads this file automatically.
The example contains separate world, India, business, technology, science,
sports, and entertainment-oriented feeds. Feed URLs are checked independently
on each collection run; a failed feed does not prevent other feeds from
running. Only feeds that successfully respond and parse are reported as
successful.
Then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The core API uses SQLite by default and creates its tables on startup. The
`NEWSSPHERE_FEEDS` setting is a comma-separated list of permitted RSS/Atom
feeds. Kafka and Spark modules are optional and are not imported during API
startup.

On startup, the backend applies only additive compatibility changes to the
existing SQLite schema. Collection liveness and lock columns are added when
needed; articles and collection history are never reset or deleted. Collection
runs finish as `completed`, `completed_with_errors`, or `failed`. The
`GET /api/collection/status` endpoint reports the latest truthful terminal or
active state.

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

The verified suite contains focused isolated tests. It does not require
or modify the development database.

## Six-agent collection workflow

The collection pipeline coordinates six agents. The monitoring API always
exposes all six agents, including an `idle` NLP Agent when analytics execution
has been explicitly disabled:

1. **Orchestration Agent** creates and coordinates each collection run,
   maintains run liveness, and records the final outcome.
2. **Web News Scraping Agent** fetches the configured RSS/Atom feeds, records
   feed-level successes and failures, and reports the retrieved article count.
3. **Database Management Agent** normalizes article URLs, stores new articles,
   and tracks inserted articles and normalized duplicates.
4. **News Segregation Agent** assigns explainable rule-based categories to new
   articles.
5. **Geographical Filtering Agent** applies conservative location enrichment
   from source metadata and supported contextual references.
6. **NLP / News Analytics Agent** analyzes newly stored articles for
   machine-generated sentiment, TF-IDF keywords, and spaCy entities.

The normal workflow runs scraping first, then persistence, segregation,
geographical filtering, and analytics. Analytics is enabled by default. When
`ANALYTICS_ENABLED=false`, the first five agents still run and the analytics
execution is intentionally skipped; the monitoring endpoint continues to
report the six-agent set and shows the analytics agent as `idle`. If analytics
dependencies or the configured spaCy model are unavailable, the analytics
agent reports a failed status and warning while the other completed agents and
their stored articles are preserved.

## Geographic reference and enrichment

The maintained reference in `data/geography.json` contains all ISO 3166-1
country names and only selected first-level administrative areas and districts.
Country names are sourced from ISO 3166 and the downloadable DataHub mirror
listed in the file; the administrative subset is explicitly not comprehensive.
RSS/Atom feed titles, sections, and publisher headquarters are not treated as
event locations. Structured event-location fields are preferred. Text matching
requires an event-context cue such as “in” or “near” and a unique reference
match; otherwise the article remains Unknown.

`POST /api/news/enrich-locations` is a repeatable, protected maintenance
operation. It examines only articles with unknown provenance and updates an
article only when the conservative resolver reaches a supported result. It
does not delete or reset records.
