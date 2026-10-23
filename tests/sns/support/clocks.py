"""A clock tests drive: time passes only when something sleeps or the test advances it."""


class FakeClock:
    def __init__(self, start=1_800_000_000.0):
        self.now = start
        self.slept = []

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if seconds > 0:
            self.slept.append(seconds)
            self.now += seconds

    def advance(self, seconds):
        self.now += seconds
