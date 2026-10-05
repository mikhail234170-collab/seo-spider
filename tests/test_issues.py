"""Unit tests for issue detection."""

from site_lens.issues import detect_issues, dedupe_issues, normalize_path_key


def test_normalize_path_key_strips_trailing_slash() -> None:
    assert normalize_path_key("https://example.com/foo/") == normalize_path_key("https://example.com/foo")


def test_duplicate_title_detected() -> None:
    pages = [
        {
            "url": "https://example.com/a",
            "status_code": 200,
            "title": "Same",
            "meta_description": "a",
            "h1": "H",
            "links": [],
            "images": [],
            "redirect_chain": ["https://example.com/a"],
        },
        {
            "url": "https://example.com/b",
            "status_code": 200,
            "title": "Same",
            "meta_description": "b",
            "h1": "H2",
            "links": [],
            "images": [],
            "redirect_chain": ["https://example.com/b"],
        },
    ]
    issues = detect_issues(pages, "https://example.com/")
    types = {i["issue_type"] for i in issues}
    assert "duplicate_title" in types


def test_missing_metadata() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "status_code": 200,
            "title": None,
            "meta_description": None,
            "h1": None,
            "links": [],
            "images": [{"src": "/x.png", "alt": ""}],
            "redirect_chain": ["https://example.com/"],
        }
    ]
    issues = detect_issues(pages, "https://example.com/")
    types = {i["issue_type"] for i in issues}
    assert "missing_title" in types
    assert "missing_meta_description" in types
    assert "missing_h1" in types
    assert "missing_img_alt" in types


def test_dedupe_issues() -> None:
    issue = {
        "issue_type": "x",
        "severity": "low",
        "title": "T",
        "remediation": "R",
        "evidence": {"affected_urls": ["https://a"]},
    }
    assert len(dedupe_issues([issue, issue])) == 1
