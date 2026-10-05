"""Async site crawler with robots.txt and rate limiting."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from site_lens.config import settings
from site_lens.db import get_conn, insert_issues, insert_page, update_crawl_status, utc_now
from site_lens.issues import detect_issues
from site_lens.parsing import is_same_host, normalize_url, parse_page_html, resolve_link

_playwright_available: bool | None = None


def row_to_page_dict(row: Any) -> dict[str, Any]:
    import json

    return {
        "url": row["url"],
        "final_url": row["final_url"],
        "status_code": row["status_code"],
        "title": row["title"],
        "meta_description": row["meta_description"],
        "h1": row["h1"],
        "canonical": row["canonical"],
        "meta_robots": row["meta_robots"],
        "links": json.loads(row["links_json"] or "[]"),
        "images": json.loads(row["images_json"] or "[]"),
        "structured_data": json.loads(row["structured_data_json"] or "[]"),
        "redirect_chain": json.loads(row["redirect_chain_json"] or "[]"),
        "render_failed": bool(row["render_failed"]),
        "fetch_error": row["fetch_error"],
    }


class RobotsCache:
    def __init__(self) -> None:
        self._parsers: dict[str, RobotFileParser] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            rp = RobotFileParser()
            robots_url = urljoin(origin, "/robots.txt")
            try:
                resp = await client.get(robots_url, timeout=10.0)
                if resp.status_code == 200 and resp.text:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.parse([])
            except httpx.HTTPError:
                rp.parse([])
            self._parsers[origin] = rp
        return self._parsers[origin].can_fetch(user_agent, url)


async def render_page_text(url: str) -> tuple[str | None, bool]:
    global _playwright_available
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        _playwright_available = False
        return None, True

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=settings.render_timeout_ms)
                text = await page.inner_text("body")
                return text[:50000] if text else None, False
            finally:
                await browser.close()
    except Exception:
        _playwright_available = False
        return None, True


async def fetch_with_redirects(
    client: httpx.AsyncClient, url: str, max_redirects: int = 10
) -> tuple[str, list[str], httpx.Response | None, str | None]:
    chain = [url]
    current = url
    for _ in range(max_redirects):
        try:
            resp = await client.get(current, follow_redirects=False)
        except httpx.HTTPError as exc:
            return current, chain, None, str(exc)
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            loc = urljoin(current, resp.headers["location"])
            chain.append(loc)
            current = loc
            continue
        return current, chain, resp, None
    return current, chain, None, "Too many redirects"


async def run_crawl(crawl_id: int, seed_url: str, max_urls: int, rate_per_sec: float) -> None:
    user_agent = "SiteLens/0.1 (+local; respects robots)"
    seed_url = normalize_url(seed_url)
    robots = RobotsCache()
    queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
    await queue.put((seed_url, False))
    seen: set[str] = set()
    rate_delay = 1.0 / max(rate_per_sec, 0.1)
    last_fetch = 0.0

    with get_conn(settings.db_path) as conn:
        update_crawl_status(conn, crawl_id, "running", started_at=utc_now())

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=30.0,
            verify=True,
        ) as client:
            pages_done = 0
            while pages_done < max_urls:
                try:
                    url, parent_nofollow = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                norm = normalize_url(url)
                if norm in seen:
                    continue
                seen.add(norm)

                if not is_same_host(seed_url, norm):
                    continue

                if not await robots.allowed(client, norm, user_agent):
                    with get_conn(settings.db_path) as conn:
                        insert_page(
                            conn,
                            crawl_id,
                            {
                                "url": norm,
                                "status_code": None,
                                "fetch_error": "Blocked by robots.txt",
                                "links": [],
                                "images": [],
                                "structured_data": [],
                                "redirect_chain": [norm],
                                "crawled_at": utc_now(),
                            },
                        )
                    continue

                elapsed = time.monotonic() - last_fetch
                if elapsed < rate_delay:
                    await asyncio.sleep(rate_delay - elapsed)
                last_fetch = time.monotonic()

                final_url, chain, resp, fetch_error = await fetch_with_redirects(client, norm)
                page_data: dict[str, Any] = {
                    "url": norm,
                    "final_url": final_url,
                    "redirect_chain": chain,
                    "links": [],
                    "images": [],
                    "structured_data": [],
                    "crawled_at": utc_now(),
                }

                if fetch_error or resp is None:
                    page_data["fetch_error"] = fetch_error or "Unknown fetch error"
                    with get_conn(settings.db_path) as conn:
                        insert_page(conn, crawl_id, page_data)
                    pages_done += 1
                    with get_conn(settings.db_path) as conn:
                        update_crawl_status(conn, crawl_id, "running", pages_crawled=pages_done)
                    continue

                page_data["status_code"] = resp.status_code
                page_data["content_type"] = resp.headers.get("content-type", "")

                html = ""
                if resp.status_code < 400 and "text/html" in page_data["content_type"]:
                    html = resp.text
                    parsed = parse_page_html(html, final_url)
                    page_data.update(parsed)
                    page_data["rendered_text"] = parsed.pop("visible_text")

                    if not parent_nofollow:
                        for link in parsed.get("links") or []:
                            href = link.get("href")
                            if not href or not is_same_host(seed_url, href):
                                continue
                            child_nofollow = parent_nofollow or link.get("nofollow", False)
                            if child_nofollow:
                                continue
                            nhref = normalize_url(href)
                            if nhref not in seen:
                                await queue.put((nhref, child_nofollow))

                    rendered, render_failed = await render_page_text(final_url)
                    if rendered:
                        page_data["rendered_text"] = rendered
                    page_data["render_failed"] = render_failed
                elif resp.status_code < 400:
                    page_data["render_failed"] = True

                with get_conn(settings.db_path) as conn:
                    insert_page(conn, crawl_id, page_data)
                pages_done += 1
                with get_conn(settings.db_path) as conn:
                    update_crawl_status(conn, crawl_id, "running", pages_crawled=pages_done)

        with get_conn(settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM pages WHERE crawl_id = ?", (crawl_id,)).fetchall()
            page_dicts = [row_to_page_dict(r) for r in rows]
            issues = detect_issues(page_dicts, seed_url)
            insert_issues(conn, crawl_id, issues)
            update_crawl_status(
                conn,
                crawl_id,
                "completed",
                finished_at=utc_now(),
                pages_crawled=len(page_dicts),
            )
    except Exception as exc:
        with get_conn(settings.db_path) as conn:
            update_crawl_status(
                conn,
                crawl_id,
                "failed",
                finished_at=utc_now(),
                error_message=str(exc),
            )
