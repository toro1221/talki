"""Backward-compatible entry point.

Prefer `python -m talki` or the `talki` console script.
"""

from talki.__main__ import main


if __name__ == "__main__":
    main()
