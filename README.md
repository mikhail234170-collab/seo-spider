# Site Lens

**Site Lens** is a personal, local replacement for Screaming Frog SEO Spider. Crawl sites you own, inspect HTML and technical signals, review prioritized issues, and export reproducible audits — all on your machine.

## Stack

- Python 3.12
- FastAPI + HTMX UI
- SQLite (`./data/site_lens.db`)
- Playwright (optional rendered text; falls back to HTML parse on failure)
- httpx + BeautifulSoup for fetching and parsing

## First run (one command)

From the repository root, after cloning:

```bash
make dev
```

`make dev` creates a virtualenv and installs dependencies on first run, then starts the UI at [http://127.0.0.1:8765](http://127.0.0.1:8765).

For rendered-page text (recommended once):

```bash
make playwright-install
```

Copy `.env.example` to `.env` and adjust paths or limits if needed.

## Permissions

You **must** check the ownership/permission acknowledgement before each crawl. Site Lens is built for auditing sites you control or have explicit authorization to test. It does not support unauthorized third-party crawling.

## Architecture

- **`site_lens/main.py`** — FastAPI routes, HTMX partials, export downloads
- **`site_lens/crawler.py`** — async crawl queue, robots.txt, rate limiting, redirects, Playwright render
- **`site_lens/issues.py`** — pure issue detection (duplicates, orphans, broken links, metadata, canonical conflicts)
- **`site_lens/db.py`** — SQLite schema and persistence
- **`site_lens/export.py`** — CSV + self-contained HTML report under `./data/exports/`
- **`templates/`** — HTMX UI (empty, loading, success, recoverable error states)

## Data location & backup

| Item | Path |
|------|------|
| Database | `./data/site_lens.db` |
| Exports | `./data/exports/crawl_<id>/` |

To back up: copy the entire `./data/` directory (or at minimum `site_lens.db` and `exports/`). To reset: stop the app, delete `./data/`, restart.

## Crawl behavior

- Respects `robots.txt`, `nofollow`, canonical tags, redirect chains, and configurable URL cap / rate limit
- Collects status, title, description, headings, canonical, robots meta, links, images, JSON-LD, and rendered text when available
- Issues include affected URLs, evidence, severity, and remediation notes

## Tests

```bash
make test
```

## Out of scope (by design)

- Accounts, billing, telemetry, or hosted control plane
- Crawling without permission
- Web-scale backlink/keyword datasets
- Automated changes to production websites

## License

MIT (personal tool — use responsibly).
