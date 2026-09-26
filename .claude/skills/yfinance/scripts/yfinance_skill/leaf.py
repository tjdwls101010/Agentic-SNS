"""A command bound to the dataset it reads: what the caller can ask (cli.py) joined to what the source returns (yahoo).

Selection, recovery, export and schema read one object for both, so none of them has to know which side owns a fact.
"""


class Leaf:
    def __init__(self, command, dataset):
        self.command, self.dataset = command, dataset
        self.path, self.group, self.name, self.purpose = command.path, command.group, command.name, command.purpose
        self.narrow, self.forbidden, self.coarser = command.narrow, command.forbidden, command.coarser
        self.exportable, self.end_exclusive = command.exportable, command.end_exclusive
        self.limit, self.fields, self.recent = dataset.rows, dataset.fields, dataset.recent
        self.precise, self.sliceable, self.shares_info = dataset.precise, dataset.sliceable, dataset.shares_info
        self.source_time, self.conditions = dataset.source_time, dataset.conditions
        self.units, self.interpretation, self.limits, self.gotchas = dataset.units, dataset.interpretation, dataset.limits, dataset.gotchas

    def limit_keeps(self):
        return "the newest rows of a series the source publishes oldest first" if self.recent else "the first rows in source order"
