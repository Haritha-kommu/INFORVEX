# Sources and attribution

NewsSphere does not embed news content. Operators configure RSS/Atom feeds in
`NEWSSPHERE_FEEDS` and remain responsible for each source's terms, licensing,
robots policy, and rate limits. The configured examples were independently
requested and parsed successfully on 2026-10-27:

- BBC News World RSS
- The Guardian World, Business, Technology, Science, Sport, and Film RSS feeds
- The Hindu National/India RSS feed

The project stores feed URLs in `backend\.env`, not in frontend code. External
feed availability can change, so every collection run records current
success/failure status rather than assuming a feed remains available.

The geography dropdown reference is the curated offline file
`backend/data/geography.json`. It is a small demonstration dataset, not a
worldwide administrative database. It contains selected India, United States,
and United Kingdom administrative examples and is maintained inside the
project so the UI works without an external geography service. Expand it only
with a separately verified and licensed source. Geographic article metadata is
still source-provided; unresolved values remain `Unknown`.
