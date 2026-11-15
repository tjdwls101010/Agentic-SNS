"""The platform registry and lazy access to its adapters."""
from functools import lru_cache
from importlib import import_module

PLATFORM_PACKAGES = ('x', 'threads', 'reddit', 'facebook', 'naver_blog')


@lru_cache(maxsize=1)
def adapters():
    return tuple(import_module(f'sns.{name}').PLATFORM for name in PLATFORM_PACKAGES)
