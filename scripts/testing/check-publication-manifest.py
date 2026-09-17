#!/usr/bin/env python3
"""Validate the release contract used by the stack's manifest-mode portal."""
import json
import re
import sys


def validate(m):
    if not isinstance(m, dict):
        raise ValueError("manifest must be an object")
    release = m.get("releaseId")
    if (type(m.get("schemaVersion")) is not int or m["schemaVersion"] != 1
            or not isinstance(release, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", release)
            or m.get("datasheets") != f"datasheets-{release}.xtf"
            or "catalog" not in m or m["catalog"] not in (None, f"published-catalog-{release}.xtf")
            or m.get("duckdb") != f"catalog-{release}.duckdb"):
        raise ValueError("current.json requires valid release filenames, including duckdb")
    return m


if __name__ == "__main__":
    try:
        validate(json.load(sys.stdin))
    except (ValueError, TypeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
