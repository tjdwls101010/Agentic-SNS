# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["yfinance[repair]==1.7.0", "pandas", "numpy"]
#
# [tool.uv]
# exclude-newer = "2026-09-13T13:10:00Z"
# ///
"""Investment research data. `--help` maps the commands; `<command> --help` documents one."""
import sys

ROOT = "usage: cli.py [--max-chars N] [--ttl-days N] COMMAND ...\n\ncommands:\n"


def main():
    print(ROOT)
    return 0 if "--help" in sys.argv[1:] else 2


if __name__ == "__main__":
    raise SystemExit(main())
