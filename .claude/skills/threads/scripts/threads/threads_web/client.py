"""The Threads web client: requests made from the skill's own www.threads.com tab, the way the app makes them."""


class Client:
    """One invocation's connection to Threads. browser: the Aside system; guard: account protection; memory: the
    session store."""

    def __init__(self, browser, guard, memory, verbose=False):
        self.browser, self.guard, self.memory, self.verbose = browser, guard, memory, verbose

    def start(self):
        raise NotImplementedError
