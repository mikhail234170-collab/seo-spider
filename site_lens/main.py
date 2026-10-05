"""FastAPI + HTMX application entrypoint."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from site_lens.config import settings
from site_lens.crawler import run_crawl
from site_lens.db import create_crawl, get_conn, get_crawl, get_issues, get_pages, init_db, list_crawls
from site_lens.export import export_csv, export_html_report, safe_filename
from site_lens.validation import StartCrawlForm

settings.ensure_data_dir()
init_db(settings.db_path)

app = FastAPI(title="Site Lens", description="Local SEO Spider")
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

_running_tasks: dict[int, asyncio.Task] = {}


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _rows_dict(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    with get_conn(settings.db_path) as conn:
        crawls = _rows_dict(list_crawls(conn))
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "crawls": crawls,
            "defaults": {
                "max_urls": settings.default_max_urls,
                "rate": settings.default_rate_per_sec,
            },
        },
    )


@app.post("/crawl/start", response_class=HTMLResponse)
async def start_crawl(
    request: Request,
    seed_url: str = Form(...),
    max_urls: int = Form(100),
    rate_per_sec: float = Form(2.0),
    permission_ack: str | None = Form(None),
) -> HTMLResponse:
    try:
        form = StartCrawlForm(
            seed_url=seed_url,
            max_urls=max_urls,
            rate_per_sec=rate_per_sec,
            permission_ack=permission_ack == "on",
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "partials/crawl_form_error.html",
            {"errors": [e["msg"] for e in exc.errors()]},
            status_code=400,
        )

    with get_conn(settings.db_path) as conn:
        crawl_id = create_crawl(
            conn,
            form.seed_url,
            form.max_urls,
            form.rate_per_sec,
            form.permission_ack,
        )

    task = asyncio.create_task(run_crawl(crawl_id, form.seed_url, form.max_urls, form.rate_per_sec))
    _running_tasks[crawl_id] = task

    def _done(t: asyncio.Task, cid: int = crawl_id) -> None:
        _running_tasks.pop(cid, None)

    task.add_done_callback(_done)

    return templates.TemplateResponse(
        request,
        "partials/crawl_started.html",
        {"crawl_id": crawl_id, "seed_url": form.seed_url},
    )


@app.get("/crawl/{crawl_id}/status", response_class=HTMLResponse)
async def crawl_status(request: Request, crawl_id: int) -> HTMLResponse:
    with get_conn(settings.db_path) as conn:
        crawl = get_crawl(conn, crawl_id)
    if not crawl:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"message": "Crawl not found.", "recoverable": True},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "partials/crawl_status.html",
        {"crawl": _row_dict(crawl)},
    )


@app.get("/crawl/{crawl_id}", response_class=HTMLResponse)
async def crawl_detail(request: Request, crawl_id: int) -> HTMLResponse:
    with get_conn(settings.db_path) as conn:
        crawl = get_crawl(conn, crawl_id)
        if not crawl:
            raise HTTPException(status_code=404, detail="Crawl not found")
        pages = get_pages(conn, crawl_id)
    return templates.TemplateResponse(
        request,
        "crawl_detail.html",
        {
            "crawl": _row_dict(crawl),
            "pages": _rows_dict(pages),
        },
    )


@app.get("/crawl/{crawl_id}/issues", response_class=HTMLResponse)
async def issues_partial(request: Request, crawl_id: int) -> HTMLResponse:
    with get_conn(settings.db_path) as conn:
        crawl = get_crawl(conn, crawl_id)
        issues = get_issues(conn, crawl_id)
    if not crawl:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"message": "Crawl not found.", "recoverable": True},
            status_code=404,
        )
    parsed_issues = []
    for i in issues:
        ev = json.loads(i["evidence_json"])
        parsed_issues.append({**_row_dict(i), "evidence": ev})
    return templates.TemplateResponse(
        request,
        "partials/issues_list.html",
        {"crawl": _row_dict(crawl), "issues": parsed_issues},
    )


@app.post("/crawl/{crawl_id}/export", response_class=HTMLResponse)
async def export_crawl(request: Request, crawl_id: int) -> HTMLResponse:
    export_dir = settings.data_dir / "exports" / safe_filename(f"crawl_{crawl_id}")
    try:
        with get_conn(settings.db_path) as conn:
            crawl = get_crawl(conn, crawl_id)
            if not crawl:
                raise HTTPException(status_code=404, detail="Crawl not found")
            if crawl["status"] != "completed":
                return templates.TemplateResponse(
                    request,
                    "partials/error.html",
                    {
                        "message": "Export is available when the crawl has completed.",
                        "recoverable": True,
                    },
                    status_code=409,
                )
            pages_csv, issues_csv = export_csv(conn, crawl_id, export_dir)
            html_report = export_html_report(conn, crawl_id, export_dir)
    except OSError as exc:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {
                "message": f"Could not write export files: {exc}",
                "recoverable": True,
            },
            status_code=500,
        )

    return templates.TemplateResponse(
        request,
        "partials/export_done.html",
        {
            "crawl_id": crawl_id,
            "paths": {
                "pages_csv": str(pages_csv),
                "issues_csv": str(issues_csv),
                "html_report": str(html_report),
            },
        },
    )


@app.get("/crawl/{crawl_id}/download/{file_type}")
async def download_export(crawl_id: int, file_type: str) -> FileResponse:
    allowed = {"pages", "issues", "report"}
    if file_type not in allowed:
        raise HTTPException(status_code=400, detail="Invalid export type")
    export_dir = settings.data_dir / "exports" / safe_filename(f"crawl_{crawl_id}")
    mapping = {
        "pages": export_dir / f"crawl_{crawl_id}_pages.csv",
        "issues": export_dir / f"crawl_{crawl_id}_issues.csv",
        "report": export_dir / f"crawl_{crawl_id}_report.html",
    }
    path = mapping[file_type]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found. Run export first.")
    media = "text/csv" if file_type != "report" else "text/html"
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
