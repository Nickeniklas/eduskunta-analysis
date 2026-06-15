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

Sync is RESUMABLE: it never wipes existing rows (unless you pass --reset).
On restart it counts the rows already cached for each table, jumps to the
page where it left off, and re-fetches from there. A UNIQUE index plus
INSERT OR IGNORE means re-fetching the page you died on can't create
duplicates, so resuming is always safe.

Usage:
  python fetch_votes.py --list                 # show all tables
  python fetch_votes.py --peek SaliDBAanestys  # print the column names + 1 row
  python fetch_votes.py --sync                 # pull both vote tables into votes.db (resumable)
  python fetch_votes.py --sync --reset         # wipe first, then full re-pull
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

# Natural key per table, used to dedup so a re-fetched page can't double-insert.
# The ballot table has no single id column; one MP + one vote is unique.
# The vote table is tiny, so we just dedup on the whole row (key=None -> all cols).
KEY_COLS = {
    BALLOT_TABLE: ["EdustajaId", "AanestysId"],
    VOTE_TABLE: None,   # None => use every column as the key
}


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


def _fetch_table(table, start_page=0):
    """Generator yielding (columnNames, row, page) for every row, from start_page on."""
    page = start_page
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
            yield cols, row, page
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
    # Unique index on the natural key so INSERT OR IGNORE dedups re-fetched pages.
    key = KEY_COLS.get(table)
    key = key if key else cols           # None => whole-row key
    key_sql = ", ".join(f'"{c}"' for c in key)
    idx = f"ux_{table}"
    con.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "{idx}" ON "{table}" ({key_sql})')


def _ensure_state(con):
    con.execute(
        'CREATE TABLE IF NOT EXISTS "_sync_state" '
        '("table_name" TEXT PRIMARY KEY, "last_page" INTEGER, "rows" INTEGER, "done" INTEGER)'
    )


def _existing_rows(con, table):
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _state_done(con, table):
    row = con.execute(
        'SELECT done FROM "_sync_state" WHERE table_name = ?', (table,)
    ).fetchone()
    return bool(row and row[0])


def sync(reset=False):
    con = sqlite3.connect(DB)
    _ensure_state(con)

    if reset:
        for table in (VOTE_TABLE, BALLOT_TABLE):
            con.execute(f'DROP TABLE IF EXISTS "{table}"')
        con.execute('DELETE FROM "_sync_state"')
        con.commit()
        print("reset: dropped existing vote tables, starting clean")

    for table in (VOTE_TABLE, BALLOT_TABLE):
        if _state_done(con, table) and not reset:
            print(f"{table}: already marked complete, skipping (use --reset to redo)")
            continue

        have = _existing_rows(con, table)
        start_page = have // PER_PAGE       # resume at the page that contains row `have`
        if have:
            print(f"syncing {table} ... resuming from page {start_page} "
                  f"({have} rows already cached)")
        else:
            print(f"syncing {table} ... (fresh)")

        cols = None
        new = 0
        buf = []
        last_page = start_page
        for c, row, page in _fetch_table(table, start_page=start_page):
            if cols is None:
                cols = c
                _ensure_table(con, table, cols)
            vals = row if isinstance(row, list) else [row.get(k) for k in cols]
            buf.append(vals)
            new += 1
            last_page = page
            if len(buf) >= 1000:
                _flush(con, table, cols, buf)
                _checkpoint(con, table, last_page)
                con.commit()
                buf = []
        if buf:
            _flush(con, table, cols, buf)
        _checkpoint(con, table, last_page, done=True)
        con.commit()
        total = _existing_rows(con, table)
        print(f"  {table}: +{new} fetched this run, {total} rows total")
    con.close()
    print(f"done -> {DB}")


def _flush(con, table, cols, buf):
    placeholders = ",".join("?" * len(cols))
    # OR IGNORE: rows already present (same natural key) are silently skipped,
    # so re-fetching the page we died on mid-write is harmless.
    con.executemany(
        f'INSERT OR IGNORE INTO "{table}" VALUES ({placeholders})', buf
    )


def _checkpoint(con, table, last_page, done=False):
    rows = _existing_rows(con, table)
    con.execute(
        'INSERT INTO "_sync_state" (table_name, last_page, rows, done) '
        'VALUES (?, ?, ?, ?) '
        'ON CONFLICT(table_name) DO UPDATE SET last_page=?, rows=?, done=?',
        (table, last_page, rows, int(done), last_page, rows, int(done)),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list all tables")
    ap.add_argument("--peek", metavar="TABLE", help="show columns + first row of a table")
    ap.add_argument("--sync", action="store_true", help="pull vote tables into votes.db (resumable)")
    ap.add_argument("--reset", action="store_true", help="wipe cached vote tables first, then full re-pull")
    ap.add_argument("--db", default=DB, help="sqlite path (default votes.db)")
    args = ap.parse_args()

    globals()["DB"] = args.db

    if args.list:
        list_tables()
    elif args.peek:
        peek(args.peek)
    elif args.sync:
        sync(reset=args.reset)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
