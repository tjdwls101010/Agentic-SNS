"""The five platforms' protection policies as the plan's table states them (decisions S3, S14): the reference rows
the core tests use and each platform adapter's `policy` must equal."""
from sns.limits import LimitPolicy

POLICIES = {
    'x': LimitPolicy(scope='operation', slow='fraction', slow_fraction=0.2, hold_seconds=900,
                     person=('challenge', 'account_locked'), pace=(1.0, 2.0)),
    'reddit': LimitPolicy(scope='bucket', slow='used', hold_seconds=600, person=('challenge',), pace=(1.0, 2.0)),
    'threads': LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    'facebook': LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    'naver_blog': LimitPolicy(scope='account', hold_seconds=1800, person=('network_blocked',), pace=(0.5, 0.8)),
}
