from scraper.clean import html_to_markdown, slugify


def test_preserves_headings_code_and_links() -> None:
    markdown = html_to_markdown(
        '<h2>Setup</h2><p><a href="/guide">Guide</a></p><pre><code>run()</code></pre>',
        'https://support.optisigns.com/hc/en-us/articles/1',
        'Example',
    )

    assert '## Setup' in markdown
    assert '[Guide](https://support.optisigns.com/guide)' in markdown
    assert 'run()' in markdown
    assert 'Article URL: https://support.optisigns.com/hc/en-us/articles/1' in markdown


def test_strips_unsafe_html() -> None:
    markdown = html_to_markdown(
        '<script>alert(1)</script><a href="javascript:alert(2)">bad</a>',
        'https://support.optisigns.com/article/1',
        'Example',
    )

    assert '<script>' not in markdown
    assert 'javascript:' not in markdown
    assert 'alert(1)' not in markdown
    assert 'alert(2)' not in markdown


def test_slugify_removes_path_traversal_characters() -> None:
    assert slugify('../Unsafe Article!!') == 'unsafe-article'
