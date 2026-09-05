import base64
import json
from pathlib import Path
import pytest
from twitter_skill._errors import TwitterError
from twitter_skill._txid import compute_animation_key, derive, generate


def test_public_ingredients_match_independent_legacy_vector():
    fixture = json.loads((Path(__file__).parent / 'fixtures/transaction.json').read_text())
    key = list(base64.b64decode(fixture['verification']))
    animation = compute_animation_key(key, {int(k): v for k, v in fixture['frames'].items()},
                                      fixture['indices'][0], fixture['indices'][1:])
    assert animation == fixture['animation_key']
    material = {'key_bytes': key, 'animation_key': animation}
    assert generate(fixture['vector_method'], fixture['vector_path'], material=material,
                    now=fixture['vector_now'], rng=lambda *_: fixture['vector_noise']) == fixture['txid']


def test_missing_public_ingredient_reports_which_material_failed():
    with pytest.raises(TwitterError) as exc:
        derive('<html></html>', '')
    assert exc.value.error == 'transaction_unavailable'
    assert 'verification' in exc.value.message
