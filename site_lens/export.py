"""CSV and self-contained HTML report export."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite3

from site_lens.db import get_crawl, get_issues, get_pages


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", name.strip())
    return cleaned[:120] or "export"


def export_csv(conn: sqlite3.Connection, crawl_id: int, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_path = out_dir / f"crawl_{crawl_id}_pages.csv"
    issues_path = out_dir / f"crawl_{crawl_id}_issues.csv"

    pages = get_pages(conn, crawl_id)
    with pages_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "url",
                "final_url",
                "status_code",
                "title",
                "meta_description",
                "h1",
                "canonical",
                "meta_robots",
                "link_count",
                "image_count",
                "has_structured_data",
                "render_failed",
                "fetch_error",
            ]
        )
        for p in pages:
            links = json.loads(p["links_json"] or "[]")
            images = json.loads(p["images_json"] or "[]")
            sd = json.loads(p["structured_data_json"] or "[]")
            writer.writerow(
                [
                    p["url"],
                    p["final_url"],
                    p["status_code"],
                    p["title"],
                    p["meta_description"],
                    p["h1"],
                    p["canonical"],
                    p["meta_robots"],
                    len(links),
                    len(images),
                    bool(sd),
                    p["render_failed"],
                    p["fetch_error"],
                ]
            )

    issues = get_issues(conn, crawl_id)
    with issues_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["issue_type", "severity", "title", "remediation", "affected_urls", "evidence_json"])
        for i in issues:
            ev = json.loads(i["evidence_json"])
            writer.writerow(
                [
                    i["issue_type"],
                    i["severity"],
                    i["title"],
                    i["remediation"],
                    ";".join(ev.get("affected_urls", [])),
                    json.dumps(ev, ensure_ascii=False),
                ]
            )

    return pages_path, issues_path


def export_html_report(conn: sqlite3.Connection, crawl_id: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    crawl = get_crawl(conn, crawl_id)
    pages = get_pages(conn, crawl_id)
    issues = get_issues(conn, crawl_id)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    issue_rows = ""
    for i in issues:
        ev = json.loads(i["evidence_json"])
        urls = ev.get("affected_urls", [])
        url_list = "".join(f"<li><code>{u}</code></li>" for u in urls)
        issue_rows += f"""
        <article class="issue severity-{i['severity']}">
          <h3>{i['title']} <span class="badge">{i['severity']}</span></h3>
          <p><strong>Type:</strong> {i['issue_type']}</p>
          <p><strong>Remediation:</strong> {i['remediation']}</p>
          <p><strong>Affected URLs:</strong></p>
          <ul>{url_list or '<li>(none listed)</li>'}</ul>
          <details><summary>Evidence</summary><pre>{json.dumps(ev, indent=2, ensure_ascii=False)}</pre></details>
        </article>
        """

    page_rows = ""
    for p in pages:
        page_rows += f"""
        <tr>
          <td><code>{p['url']}</code></td>
          <td>{p['status_code'] or ''}</td>
          <td>{(p['title'] or '')[:80]}</td>
          <td>{(p['meta_description'] or '')[:80]}</td>
          <td>{p['canonical'] or ''}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Site Lens Audit — Crawl {crawl_id}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 1100px; line-height: 1.5; }}
    .issue {{ border: 1px solid #ddd; padding: 1rem; margin-bottom: 1rem; border-radius: 8px; }}
    .severity-critical, .severity-high {{ border-left: 4px solid #c0392b; }}
    .severity-medium {{ border-left: 4px solid #e67e22; }}
    .severity-low, .severity-info {{ border-left: 4px solid #7f8c8d; }}
    .badge {{ font-size: 0.75rem; background: #eee; padding: 0.2rem 0.5rem; border-radius: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.4rem; text-align: left; vertical-align: top; }}
    th {{ background: #f5f5f5; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>Site Lens — SEO Audit Report</h1>
  <p>Generated: {generated}</p>
  <p>Seed URL: <code>{crawl['seed_url'] if crawl else ''}</code></p>
  <p>Status: {crawl['status'] if crawl else 'unknown'} · Pages: {len(pages)} · Issues: {len(issues)}</p>

  <h2>Issues ({len(issues)})</h2>
  {issue_rows or '<p>No issues recorded.</p>'}

  <h2>Pages ({len(pages)})</h2>
  <table>
    <thead><tr><th>URL</th><th>Status</th><th>Title</th><th>Description</th><th>Canonical</th></tr></thead>
    <tbody>{page_rows}</tbody>
  </table>
</body>
</html>
"""
    path = out_dir / f"crawl_{crawl_id}_report.html"
    path.write_text(html, encoding="utf-8")
    return path
