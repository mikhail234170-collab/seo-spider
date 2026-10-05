"""Pure issue detection from normalized page records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urlparse


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _issue(
    issue_type: str,
    severity: str,
    title: str,
    remediation: str,
    affected_urls: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "title": title,
        "remediation": remediation,
        "evidence": {
            "affected_urls": affected_urls,
            **evidence,
        },
    }


def detect_issues(pages: list[dict[str, Any]], seed_url: str) -> list[dict[str, Any]]:
    """Analyze crawled pages and return prioritized issues."""
    issues: list[dict[str, Any]] = []
    if not pages:
        return [
            _issue(
                "no_pages",
                "high",
                "No pages were crawled",
                "Check seed URL, robots.txt, and network connectivity; ensure permission acknowledgement.",
                [],
                {"detail": "Crawl produced zero page records."},
            )
        ]

    seed_host = urlparse(seed_url).netloc.lower()
    url_set = {p["url"] for p in pages}
    status_by_key: dict[str, int | None] = {}
    for p in pages:
        status_by_key[normalize_path_key(p["url"])] = p.get("status_code")
    incoming: dict[str, set[str]] = defaultdict(set)

    title_map: dict[str, list[str]] = defaultdict(list)
    desc_map: dict[str, list[str]] = defaultdict(list)
    h1_map: dict[str, list[str]] = defaultdict(list)

    for p in pages:
        url = p["url"]
        for link in p.get("links") or []:
            href = link.get("href")
            if href and urlparse(href).netloc.lower() == seed_host:
                incoming[normalize_path_key(href)].add(url)

        if p.get("title"):
            title_map[p["title"]].append(url)
        if p.get("meta_description"):
            desc_map[p["meta_description"]].append(url)
        if p.get("h1"):
            h1_map[p["h1"]].append(url)

        if p.get("status_code") and p["status_code"] >= 400:
            issues.append(
                _issue(
                    "http_error",
                    "high" if p["status_code"] >= 500 else "medium",
                    f"HTTP {p['status_code']} response",
                    "Fix server errors or update/remove broken URLs.",
                    [url],
                    {"status_code": p["status_code"], "final_url": p.get("final_url")},
                )
            )

        chain = p.get("redirect_chain") or []
        if len(chain) > 1:
            issues.append(
                _issue(
                    "redirect_chain",
                    "medium",
                    "Redirect chain detected",
                    "Point links directly to the final URL; avoid multi-hop redirects.",
                    [url],
                    {"chain": chain},
                )
            )

        if not p.get("title"):
            issues.append(
                _issue(
                    "missing_title",
                    "medium",
                    "Missing page title",
                    "Add a unique, descriptive <title> element.",
                    [url],
                    {},
                )
            )
        if not p.get("meta_description"):
            issues.append(
                _issue(
                    "missing_meta_description",
                    "low",
                    "Missing meta description",
                    "Add a meta description summarizing the page for search snippets.",
                    [url],
                    {},
                )
            )
        if not p.get("h1"):
            issues.append(
                _issue(
                    "missing_h1",
                    "low",
                    "Missing H1 heading",
                    "Add a single primary H1 that describes the page topic.",
                    [url],
                    {},
                )
            )

        robots = (p.get("meta_robots") or "").lower()
        if "noindex" in robots:
            issues.append(
                _issue(
                    "noindex",
                    "info",
                    "Page marked noindex",
                    "Remove noindex if this page should appear in search results.",
                    [url],
                    {"meta_robots": p.get("meta_robots")},
                )
            )

        canonical = p.get("canonical")
        if canonical and normalize_path_key(canonical) != normalize_path_key(url):
            if p.get("final_url") and normalize_path_key(p["final_url"]) == normalize_path_key(url):
                issues.append(
                    _issue(
                        "canonical_mismatch",
                        "medium",
                        "Canonical points elsewhere",
                        "Align canonical URL with the preferred URL or redirect this URL to the canonical.",
                        [url],
                        {"canonical": canonical, "page_url": url},
                    )
                )

        for link in p.get("links") or []:
            href = link.get("href")
            if not href:
                continue
            if urlparse(href).netloc.lower() != seed_host:
                continue
            target_key = normalize_path_key(href)
            target_status = status_by_key.get(target_key)
            if target_status is not None and target_status >= 400:
                issues.append(
                    _issue(
                        "broken_internal_link",
                        "high",
                        "Broken internal link",
                        "Fix or remove links pointing to URLs that return error status codes.",
                        [url],
                        {
                            "link_href": href,
                            "anchor_text": link.get("text"),
                            "target_status": target_status,
                        },
                    )
                )

        for img in p.get("images") or []:
            if img.get("alt") is None or str(img.get("alt")).strip() == "":
                issues.append(
                    _issue(
                        "missing_img_alt",
                        "low",
                        "Image missing alt text",
                        "Add descriptive alt attributes for meaningful images.",
                        [url],
                        {"image_src": img.get("src")},
                    )
                )

        if p.get("render_failed"):
            issues.append(
                _issue(
                    "render_failed",
                    "info",
                    "Rendered text unavailable",
                    "Page still analyzed from HTML; check Playwright install or increase render timeout.",
                    [url],
                    {"fetch_error": p.get("fetch_error")},
                )
            )

    for title, urls in title_map.items():
        if len(urls) > 1:
            issues.append(
                _issue(
                    "duplicate_title",
                    "medium",
                    "Duplicate title tags",
                    "Give each URL a unique title reflecting its content.",
                    urls,
                    {"title": title},
                )
            )

    for desc, urls in desc_map.items():
        if len(urls) > 1:
            issues.append(
                _issue(
                    "duplicate_meta_description",
                    "low",
                    "Duplicate meta descriptions",
                    "Write unique descriptions per URL.",
                    urls,
                    {"meta_description": desc[:200]},
                )
            )

    for h1, urls in h1_map.items():
        if len(urls) > 1:
            issues.append(
                _issue(
                    "duplicate_h1",
                    "low",
                    "Duplicate H1 headings",
                    "Use distinct H1 text where pages differ.",
                    urls,
                    {"h1": h1},
                )
            )

    crawled_keys = {normalize_path_key(p["url"]) for p in pages if p.get("status_code", 0) < 400}
    home_key = normalize_path_key(seed_url)
    for p in pages:
        if p.get("status_code", 0) >= 400:
            continue
        key = normalize_path_key(p["url"])
        if key == home_key:
            continue
        if key not in incoming or not incoming[key]:
            issues.append(
                _issue(
                    "orphan_candidate",
                    "info",
                    "Possible orphan page",
                    "Ensure important pages are linked from navigation or hub pages.",
                    [p["url"]],
                    {"detail": "No in-scope internal links pointed to this URL during crawl."},
                )
            )

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["issue_type"]))
    return dedupe_issues(issues)


def normalize_path_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{parsed.netloc.lower()}{path}"


def dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    out: list[dict[str, Any]] = []
    for issue in issues:
        urls = tuple(sorted(issue["evidence"].get("affected_urls", [])))
        key = (issue["issue_type"], issue["title"], urls)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out
