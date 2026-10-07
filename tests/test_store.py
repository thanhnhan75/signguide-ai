from scraper.store import ArticleDelta, ArticleState, classify_articles, content_hash


def test_classifies_added_updated_and_skipped_by_article_id() -> None:
    old = ArticleState(
        article_id=2,
        slug='old-title',
        url='https://example.test/old',
        content_hash=content_hash('old'),
        file_id='file-old',
        updated_at='yesterday',
    )
    articles = [
        ArticleDelta('new', 1, 'https://example.test/1', content_hash('new'), 'today'),
        ArticleDelta('renamed', 2, 'https://example.test/new', content_hash('changed'), 'today'),
        ArticleDelta('same', 2, 'https://example.test/same', old.content_hash, 'today'),
    ]

    delta = classify_articles(articles, {'2': old})

    assert [item.article_id for item in delta.added] == [1]
    assert [item.article_id for item in delta.updated] == [2]
    assert [item.article_id for item in delta.skipped] == [2]
    assert delta.updated[0].slug == 'renamed'


def test_content_hash_is_deterministic() -> None:
    assert content_hash('article') == content_hash('article')
    assert content_hash('article') != content_hash('changed')
