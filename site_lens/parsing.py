"""HTML parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    netloc = parsed.netloc.lower()
    scheme = parsed.scheme.lower()
    query = parsed.query
    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized += f"?{query}"
    return normalized


def is_same_host(seed: str, url: str) -> bool:
    return urlparse(seed).netloc.lower() == urlparse(url).netloc.lower()


def resolve_link(base_url: str, href: str) -> str | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    return urljoin(base_url, href)


def parse_page_html(html: str, page_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    meta_desc = None
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if desc_tag and desc_tag.get("content"):
        meta_desc = desc_tag["content"].strip()

    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(strip=True) if h1_tag else None

    canonical = None
    canon_tag = soup.find("link", rel=lambda x: x and "canonical" in x.lower())
    if canon_tag and canon_tag.get("href"):
        canonical = urljoin(page_url, canon_tag["href"])

    meta_robots = None
    robots_tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if robots_tag and robots_tag.get("content"):
        meta_robots = robots_tag["content"].strip()

    links: list[dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        href = resolve_link(page_url, a["href"])
        if not href:
            continue
        rel = " ".join(a.get("rel") or []).lower()
        links.append(
            {
                "href": href,
                "text": a.get_text(strip=True)[:200],
                "nofollow": "nofollow" in rel,
            }
        )

    images: list[dict[str, Any]] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        alt = img.get("alt")
        images.append({"src": urljoin(page_url, src), "alt": alt})

    structured: list[Any] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            structured.append(json.loads(raw))
        except json.JSONDecodeError:
            structured.append({"_parse_error": True, "raw": raw[:500]})

    snippet = html[:8000] if html else None
    visible_text = soup.get_text(separator=" ", strip=True)
    visible_text = re.sub(r"\s+", " ", visible_text)[:50000]

    return {
        "title": title,
        "meta_description": meta_desc,
        "h1": h1,
        "canonical": canonical,
        "meta_robots": meta_robots,
        "links": links,
        "images": images,
        "structured_data": structured,
        "raw_html_snippet": snippet,
        "visible_text": visible_text,
    }
