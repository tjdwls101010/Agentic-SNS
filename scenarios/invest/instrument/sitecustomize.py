"""Counts real CLI runs for scenarios/invest/run.py: a Python process started on a cli.py appends its arguments to $INVEST_CALL_LOG; nothing else is touched."""
import json
import os
import sys
import time

if os.environ.get("INVEST_CALL_LOG") and sys.argv and sys.argv[0].endswith("cli.py"):
    with open(os.environ["INVEST_CALL_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": sys.argv[1:], "at": time.time()}) + "\n")
