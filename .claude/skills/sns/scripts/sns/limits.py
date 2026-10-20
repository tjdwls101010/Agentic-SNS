"""What each platform's account protection is made of, as data: the policy a platform hands the protection store, and
a fact a platform's system read from a response's rate-limit headers."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LimitPolicy:
    """One platform's protection policy.

    scope: what a server-announced limit counts — 'operation' (X: each GraphQL operation has its own window),
      'bucket' (Reddit: wiki pages and other .json reads), or 'account' (no announced limit; a 429 holds the account).
    slow: when a scope's next request is spaced out until its reset — 'fraction' (remaining below slow_fraction of the
      limit, X) or 'used' (remaining at or below what was used, Reddit); None for account-scoped platforms.
    hold_seconds: how long a 429 stops requests when the platform gives no reset.
    person: the block reasons only a person can clear (a checkpoint, a challenge, a locked account, a network block).
    pace: the random gap between two requests of one account, in seconds.
    """
    scope: str
    hold_seconds: int
    person: tuple
    pace: tuple
    slow: str | None = None
    slow_fraction: float = 0.2


@dataclass(frozen=True)
class Fact:
    """A scope's state as the response headers stated it: limit, remaining and the epoch it resets at."""
    limit: float
    remaining: float
    reset_at: float
