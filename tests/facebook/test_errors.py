from _errors import FacebookError, scrub


def test_scrub_removes_session_fields_and_signed_urls_from_diagnostics():
    data = {'fb_dtsg': 'private', 'nested': [{'Cookie': 'c_user=123; xs=private'}],
            'url': 'https://scontent.example.fbcdn.net/photo.jpg?sig=private',
            'detail': 'lsd=private&ok=1'}
    cleaned = scrub(data)
    assert 'private' not in str(cleaned)
    assert cleaned['url'] == 'https://scontent.example.fbcdn.net/photo.jpg'
    assert data['fb_dtsg'] == 'private'


def test_every_public_exit_has_a_recovery_instruction():
    for code in (2, 3, 4, 5, 6, 7, 8):
        assert FacebookError(code, 'Synthetic failure').fix
