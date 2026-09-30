#!/usr/bin/env python3
"""Fetch release and end-of-life data from endoflife.date (API v1).

    fetch_eol.py [--products kubernetes,istio,...] [-o eol.json] [--offline] [--cache DIR]

Writes {product: {fetchedAt, url, releases: [{name, releaseDate, eolFrom,
isEol, isMaintained, latest, latestDate}]}}. Results are cached for a day;
--offline uses the cache only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _net import DEFAULT_CACHE, fetch  # noqa: E402

API = "https://endoflife.date/api/v1/products/{}"


def product(name: str, cache: pathlib.Path, offline: bool) -> dict:
    body, info = fetch(API.format(name), cache, offline)
    if body is None:
        return {"error": info.get("error"), "url": info["url"]}
    try:
        releases = json.loads(body)["result"]["releases"]
    except (ValueError, KeyError) as exc:
        return {"error": f"unexpected response: {exc}", "url": info["url"]}
    return {
        "url": f"https://endoflife.date/{name}",
        "fetchedAt": info.get("fetchedAt"),
        "fromCache": info["source"] == "cache",
        "releases": [{
            "name": r.get("name"),
            "releaseDate": r.get("releaseDate"),
            "eoasFrom": r.get("eoasFrom"),
            "eolFrom": r.get("eolFrom"),
            "isEol": r.get("isEol"),
            "isMaintained": r.get("isMaintained"),
            "latest": (r.get("latest") or {}).get("name"),
            "latestDate": (r.get("latest") or {}).get("date"),
        } for r in releases],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", default="kubernetes")
    ap.add_argument("-o", "--output", default="-")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    args = ap.parse_args()
    result = {p: product(p, pathlib.Path(args.cache), args.offline)
              for p in [x.strip() for x in args.products.split(",") if x.strip()]}
    out = sys.stdout if args.output == "-" else open(args.output, "w")
    json.dump(result, out, indent=1)
    out.write("\n")
    errors = [p for p, v in result.items() if "error" in v]
    if errors:
        print(f"warning: no data for {', '.join(errors)}", file=sys.stderr)


if __name__ == "__main__":
    main()
