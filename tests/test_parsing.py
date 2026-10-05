from site_lens.parsing import parse_page_html


def test_parse_page_extracts_title_and_links() -> None:
    html = """
    <html><head>
      <title>Hello</title>
      <meta name="description" content="Desc"/>
      <link rel="canonical" href="/canonical"/>
    </head>
    <body>
      <h1>Main</h1>
      <a href="/next">Next</a>
      <a href="https://other.com" rel="nofollow">Ext</a>
    </body></html>
    """
    data = parse_page_html(html, "https://example.com/page")
    assert data["title"] == "Hello"
    assert data["meta_description"] == "Desc"
    assert data["h1"] == "Main"
    assert data["canonical"] == "https://example.com/canonical"
    assert len(data["links"]) == 2
    assert data["links"][0]["href"] == "https://example.com/next"
