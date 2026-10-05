"""End-to-end happy path with a local static HTTP server."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from site_lens.config import settings
from site_lens.crawler import run_crawl
from site_lens.db import get_conn, get_crawl, get_issues, get_pages, init_db
from site_lens.main import app


class SiteHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = b"""<!DOCTYPE html><html><head><title>Home</title>
            <meta name="description" content="Home desc"/>
            </head><body><h1>Welcome</h1>
            <a href="/about">About</a></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/about":
            body = b"""<!DOCTYPE html><html><head><title>About</title></head>
            <body><h1>About us</h1><a href="/">Home</a></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@pytest.fixture
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data)
    init_db(settings.db_path)
    return data


@pytest.fixture
def local_server() -> str:
    server = HTTPServer(("127.0.0.1", 0), SiteHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/"
    server.shutdown()


def test_api_health() -> None:
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"


def test_crawl_happy_path(temp_data_dir: Path, local_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_render(url: str) -> tuple[str | None, bool]:
        return "rendered body text", False

    monkeypatch.setattr("site_lens.crawler.render_page_text", no_render)

    with get_conn(settings.db_path) as conn:
        from site_lens.db import create_crawl

        crawl_id = create_crawl(conn, local_server, 10, 5.0, True)

    asyncio.run(run_crawl(crawl_id, local_server, 10, 5.0))

    with get_conn(settings.db_path) as conn:
        crawl = get_crawl(conn, crawl_id)
        pages = get_pages(conn, crawl_id)
        issues = get_issues(conn, crawl_id)

    assert crawl["status"] == "completed"
    assert len(pages) >= 2
    assert isinstance(issues, list)

    client = TestClient(app)
    resp = client.get(f"/crawl/{crawl_id}")
    assert resp.status_code == 200
    assert b"Welcome" in resp.content or b"Crawl" in resp.content
