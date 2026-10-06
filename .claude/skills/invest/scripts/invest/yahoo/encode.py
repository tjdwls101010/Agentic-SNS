"""pandas and numpy values turned into the skill's own representation, losslessly, at the edge where the library returns them."""
from collections.abc import KeysView
import datetime as dt
import math

import numpy as np
import pandas as pd


def encode(value):
    if isinstance(value, pd.DataFrame):
        return {"index": encode(value.index.tolist()), "columns": encode(value.columns.tolist()), "data": [[encode(v) for v in row] for row in value.itertuples(index=False, name=None)], "index_names": encode(value.index.names), "column_names": encode(value.columns.names)}
    if isinstance(value, pd.Series):
        return encode(value.to_frame())
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return encode(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.tzinfo):
        return str(value)
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset, KeysView)):
        return [encode(v) for v in sorted(value, key=str)]
    if isinstance(value, (list, tuple, np.ndarray)):
        return [encode(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported output type: {type(value).__name__}")


def label(column):
    return " | ".join(map(str, column)) if isinstance(column, tuple) else str(column)


def table(frame, index=True):
    """(columns, rows, keys) of a DataFrame with its index levels as leading columns, named by the index's own names; `keys` are those leading columns.

    A plain row-number index (an unnamed RangeIndex) carries nothing the rows do not, so it is left out; `index=False` leaves out any index.
    """
    if isinstance(frame, pd.Series):
        frame = frame.to_frame(frame.name if frame.name is not None else "value")
    names = list(frame.index.names)
    keep = index and not (isinstance(frame.index, pd.RangeIndex) and names == [None])
    leading = ([n if n is not None else ("index" if len(names) == 1 else f"index_{i}") for i, n in enumerate(names)] if keep else [])
    columns = leading + [label(c) for c in frame.columns]
    rows = []
    for position, values in zip(frame.index, frame.itertuples(index=False, name=None)):
        levels = (list(position) if isinstance(position, tuple) else [position]) if keep else []
        rows.append([encode(v) for v in levels] + [encode(v) for v in values])
    return columns, rows, leading
