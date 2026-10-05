import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_url TEXT NOT NULL,
    status TEXT NOT NULL,
    max_urls INTEGER NOT NULL,
    rate_per_sec REAL NOT NULL,
    permission_ack INTEGER NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    pages_crawled INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    final_url TEXT,
    status_code INTEGER,
    content_type TEXT,
    title TEXT,
    meta_description TEXT,
    h1 TEXT,
    canonical TEXT,
    meta_robots TEXT,
    links_json TEXT,
    images_json TEXT,
    structured_data_json TEXT,
    raw_html_snippet TEXT,
    rendered_text TEXT,
    render_failed INTEGER DEFAULT 0,
    redirect_chain_json TEXT,
    is_nofollow INTEGER DEFAULT 0,
    fetch_error TEXT,
    crawled_at TEXT,
    FOREIGN KEY (crawl_id) REFERENCES crawls(id),
    UNIQUE(crawl_id, url)
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_id INTEGER NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    remediation TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    FOREIGN KEY (crawl_id) REFERENCES crawls(id)
);

CREATE INDEX IF NOT EXISTS idx_pages_crawl ON pages(crawl_id);
CREATE INDEX IF NOT EXISTS idx_issues_crawl ON issues(crawl_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_crawl(
    conn: sqlite3.Connection,
    seed_url: str,
    max_urls: int,
    rate_per_sec: float,
    permission_ack: bool,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO crawls (seed_url, status, max_urls, rate_per_sec, permission_ack, created_at)
        VALUES (?, 'pending', ?, ?, ?, ?)
        """,
        (seed_url, max_urls, rate_per_sec, 1 if permission_ack else 0, utc_now()),
    )
    return int(cur.lastrowid)


def update_crawl_status(
    conn: sqlite3.Connection,
    crawl_id: int,
    status: str,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    error_message: str | None = None,
    pages_crawled: int | None = None,
) -> None:
    fields: list[str] = ["status = ?"]
    values: list[Any] = [status]
    if started_at is not None:
        fields.append("started_at = ?")
        values.append(started_at)
    if finished_at is not None:
        fields.append("finished_at = ?")
        values.append(finished_at)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if pages_crawled is not None:
        fields.append("pages_crawled = ?")
        values.append(pages_crawled)
    values.append(crawl_id)
    conn.execute(f"UPDATE crawls SET {', '.join(fields)} WHERE id = ?", values)


def insert_page(conn: sqlite3.Connection, crawl_id: int, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO pages (
            crawl_id, url, final_url, status_code, content_type, title, meta_description,
            h1, canonical, meta_robots, links_json, images_json, structured_data_json,
            raw_html_snippet, rendered_text, render_failed, redirect_chain_json,
            is_nofollow, fetch_error, crawled_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            crawl_id,
            data["url"],
            data.get("final_url"),
            data.get("status_code"),
            data.get("content_type"),
            data.get("title"),
            data.get("meta_description"),
            data.get("h1"),
            data.get("canonical"),
            data.get("meta_robots"),
            json.dumps(data.get("links") or []),
            json.dumps(data.get("images") or []),
            json.dumps(data.get("structured_data") or []),
            data.get("raw_html_snippet"),
            data.get("rendered_text"),
            1 if data.get("render_failed") else 0,
            json.dumps(data.get("redirect_chain") or []),
            1 if data.get("is_nofollow") else 0,
            data.get("fetch_error"),
            data.get("crawled_at") or utc_now(),
        ),
    )


def insert_issues(conn: sqlite3.Connection, crawl_id: int, issues: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM issues WHERE crawl_id = ?", (crawl_id,))
    for issue in issues:
        conn.execute(
            """
            INSERT INTO issues (crawl_id, issue_type, severity, title, remediation, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                crawl_id,
                issue["issue_type"],
                issue["severity"],
                issue["title"],
                issue["remediation"],
                json.dumps(issue["evidence"]),
            ),
        )


def get_crawl(conn: sqlite3.Connection, crawl_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM crawls WHERE id = ?", (crawl_id,)).fetchone()


def list_crawls(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM crawls ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def get_pages(conn: sqlite3.Connection, crawl_id: int) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM pages WHERE crawl_id = ? ORDER BY url", (crawl_id,)).fetchall())


def get_issues(conn: sqlite3.Connection, crawl_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM issues WHERE crawl_id = ? ORDER BY severity, issue_type",
            (crawl_id,),
        ).fetchall()
    )
