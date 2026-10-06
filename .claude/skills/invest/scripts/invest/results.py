"""Results saved under the skill's data/results: one new folder per call, published whole or not at all."""


def publish(receipt, table=None, records=None):
    raise NotImplementedError


def prune(ttl_days):
    raise NotImplementedError
