#!/usr/bin/env python3
"""
fetch_votes.py

Pulls Finnish Parliament (Eduskunta) voting data from the open API and caches
it locally in SQLite so you can analyse it without hammering their endpoint.

API base: https://avoindata.eduskunta.fi/api/v1
Tables used:
  - SaliDBAanestys          one row per vote event (date, title, tallies)
  - SaliDBAanestysEdustaja  one row per MP per vote (the actual ballot)

Data is CC BY 4.0 (credit: Eduskunta / Parliament of Finland).

Usage:
  python fetch_votes.py --list                 # show all tables + row counts
  python fetch_votes.py --sync                 # pull both vote tables into votes.db
  python fetch_votes.py --sync --since 2023    # only votes from 2023 onward
  python fetch_votes.py --peek SaliDBAanestys  # print the column names + 1 row
"""

import argparse
import sqlite3
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://avoindata.eduskunta.fi/api/v1"
PER_PAGE = 100          # hard cap enforced by the API
SLEEP = 0.3             # be polite: the API is meant for light use
DB = "votes.db"

VOTE_TABLE = "SaliDBAanestys"
BALLOT_TABLE = "SaliDBAanestysEdustaja"


def _get(url, retries=4):
    """GET JSON with simple backoff. Returns parsed dict."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "vote-map/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:          # throttled
                wait = 2 ** attempt
                print(f"  429, backing off {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:         # network blip
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"giving up on {url}: {last}")


def list_tables():
    data = _get(f"{BASE}/tables")
    # the endpoint returns a list of table descriptors; shape can vary, so be defensive
    rows = data if isinstance(data, list) else data.get("tableNames", data.get("data", []))
    for t in rows:
        name = t if isinstance(t, str) else t.get("tableName") or t.get("name")
        print(name)


def peek(table):
    """Fetch one page and show the column layout + first row."""
    data = _get(f"{BASE}/tables/{table}/rows?page=0&perPage=1")
    cols = data.get("columnNames") or data.get("columns") or []
    rows = data.get("rowData") or data.get("rows") or data.get("data") or []
    print(f"columns ({len(cols)}):")
    for c in cols:
        print(f"  - {c}")
    if rows:
        print("\nfirst row:")
        first = rows[0]
        if isinstance(first, list):
            for c, v in zip(cols, first):
                print(f"  {c} = {v}")
        else:
            print(json.dumps(first, ensure_ascii=False, indent=2))


def _fetch_table(table):
    """Generator yielding (columnNames, row) for every row in a table."""
    page = 0
    cols = None
    while True:
        url = f"{BASE}/tables/{table}/rows?page={page}&perPage={PER_PAGE}"
        data = _get(url)
        if cols is None:
            cols = data.get("columnNames") or data.get("columns")
        rows = data.get("rowData") or data.get("rows") or data.get("data") or []
        if not rows:
            break
        for row in rows:
            yield cols, row
        has_more = data.get("hasMore")
        if has_more is False:
            break
        if len(rows) < PER_PAGE:
            break
        page += 1
        time.sleep(SLEEP)
        if page % 20 == 0:
            print(f"  ...{table} page {page}", file=sys.stderr)


def _ensure_table(con, table, cols):
    safe_cols = ", ".join(f'"{c}" TEXT' for c in cols)
    con.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({safe_cols})')


def sync(since=None):
    con = sqlite3.connect(DB)
    for table in (VOTE_TABLE, BALLOT_TABLE):
        print(f"syncing {table} ...")
        cols = None
        count = 0
        buf = []
        for c, row in _fetch_table(table):
            if cols is None:
                cols = c
                _ensure_table(con, table, cols)
                con.execute(f'DELETE FROM "{table}"')   # full refresh; simple + correct
            vals = row if isinstance(row, list) else [row.get(k) for k in cols]
            buf.append(vals)
            count += 1
            if len(buf) >= 1000:
                _flush(con, table, cols, buf)
                buf = []
        if buf:
            _flush(con, table, cols, buf)
        con.commit()
        print(f"  {table}: {count} rows")
    con.close()
    print(f"done -> {DB}")
    if since:
        print(f"(note: --since {since} filtering happens in the analysis step, "
              "all rows are cached)")


def _flush(con, table, cols, buf):
    placeholders = ",".join("?" * len(cols))
    con.executemany(
        f'INSERT INTO "{table}" VALUES ({placeholders})', buf
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list all tables")
    ap.add_argument("--peek", metavar="TABLE", help="show columns + first row of a table")
    ap.add_argument("--sync", action="store_true", help="pull vote tables into votes.db")
    ap.add_argument("--since", help="year hint, kept for the analysis step")
    ap.add_argument("--db", default=DB, help="sqlite path (default votes.db)")
    args = ap.parse_args()

    globals()["DB"] = args.db

    if args.list:
        list_tables()
    elif args.peek:
        peek(args.peek)
    elif args.sync:
        sync(since=args.since)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
