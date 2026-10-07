from types import SimpleNamespace
from unittest.mock import Mock

from scraper.fetch import Article, ZendeskAPIFetcher, select_articles


def article(article_id: int, title: str, page: int) -> Article:
    return Article(article_id, title, '<p>body</p>', f'https://example.test/{article_id}', 'en-us', False, page, 0, '')


def test_fetches_all_pages() -> None:
    first = SimpleNamespace(
        status_code=200,
        headers={},
        json=lambda: {
            'articles': [
                {'id': 1, 'title': 'One', 'body': '<p>one</p>', 'html_url': 'https://example.test/1', 'locale': 'en-us', 'draft': False, 'section_id': 1, 'vote_sum': 0, 'updated_at': ''}
            ],
            'next_page': 'https://example.test/page-2',
        },
        raise_for_status=lambda: None,
    )
    second = SimpleNamespace(
        status_code=200,
        headers={},
        json=lambda: {
            'articles': [
                {'id': 2, 'title': 'Two', 'body': '<p>two</p>', 'html_url': 'https://example.test/2', 'locale': 'en-us', 'draft': False, 'section_id': 2, 'vote_sum': 0, 'updated_at': ''}
            ],
            'next_page': None,
        },
        raise_for_status=lambda: None,
    )
    session = Mock()
    session.get.side_effect = [first, second]

    result = ZendeskAPIFetcher(session=session).fetch_all()

    assert [item.id for item in result] == [1, 2]
    assert session.get.call_count == 2


def test_selects_each_required_keyword() -> None:
    articles = [
        article(1, 'YouTube guide', 1),
        article(2, 'Playlist guide', 2),
    ]

    result = select_articles(
        articles,
        target=2,
        must_include_keywords=('youtube', 'playlist'),
    )

    assert {item.id for item in result} == {1, 2}
