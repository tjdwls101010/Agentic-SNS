from reddit_skill._render import normalize_text, render_item


def test_normalized_text_counts_and_navigation_are_visible():
    assert normalize_text('**Hello**\u200b  &amp;\nworld\n\n> [site](https://example.org) ~~done~~') == 'Hello & world ⏎ site (https://example.org) done'
    output = render_item({'kind': 'comment', 'fullname': 't1_a', 'author': '[deleted]', 'text': '[removed]', 'score_hidden': True, 'url': 'https://www.reddit.com/comments/p/_/a/'}, 1)
    assert '[c1]' in output
    assert 'score=hidden' in output
    assert 'url: "https://www.reddit.com/comments/p/_/a/"' in output
    assert 'flair=' not in output


def test_previously_shown_parent_is_one_line_of_context():
    rendered = render_item({'kind': 'comment', 'fullname': 't1_a', 'author': 'reader', 'text': 'Parent body', 'context': True, 'url': 'https://www.reddit.com/comments/p/_/a/'}, 1)
    assert '\n' not in rendered
    assert '[c1 shown earlier]' in rendered and 'Parent body' in rendered
