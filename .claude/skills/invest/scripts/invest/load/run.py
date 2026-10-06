"""The target loop: each target fetched under its own deadline, a rate limit stopping the rest."""


def kinds():
    raise NotImplementedError


def run(key, args):
    raise NotImplementedError
