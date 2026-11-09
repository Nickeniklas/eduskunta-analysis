# Status log

Session history for eduskunta-analysis, newest first. CLAUDE.md holds only
the current state; dated status text lives here. Entries below were moved
verbatim out of CLAUDE.md on 2026-11-09 (the heading in parentheses names
the CLAUDE.md section each passage came from).

## 2026-11-06

**Vote-table duplicate rows and key fix** (from Architecture notes, "NULLs in
a UNIQUE index gotcha"):

The vote table
used to be keyed on *every* column; `IstuntoIlmoitettuAlkuaika` is often
NULL, and 4 vote events (8 rows with their Swedish twins, all from the
2009-01-15 session) got cached twice. Every ballot of those votes then fanned
out in `build_clean.py`'s join, giving 796 duplicate (person, vote) pairs in
`ballots_clean`. Fixed 2026-11-06 by keying the vote table on
`(AanestysId, KieliId)` (verified unique and never NULL once exact
duplicates are ignored).

**Vote-table key migration** (from Architecture notes):

- **Vote-table key migration (2026-11-06, one-off, already applied to the
  local `votes.db`)**: deleted the exact-duplicate vote rows keeping the
  lowest rowid (compared with `IS`, so NULL matches NULL), dropped the old
  whole-row `ux_SaliDBAanestys` and recreated it on `(AanestysId, KieliId)`.
  `_ensure_table` uses `CREATE UNIQUE INDEX IF NOT EXISTS` under the same
  index name, so it does **not** migrate an older DB by itself: a `votes.db`
  built before this change needs the same three steps (or a `--reset`).
  Afterwards `SaliDBAanestys` went 43,603 → 43,595 rows; `_sync_state.rows`
  still shows the old count until the next sync rewrites it, which is
  harmless (only the live row count drives the resume page).

**Vote-date fix verification** (from Cleaned ballot table, "Vote date"):

Verified 2026-11-06 against each vote's own
`AanestysAlkuaika`: 7,801 / 7,802 Finnish rows from 2018 on agree (the one
mismatch is a session whose votes ran two days after it opened), and all 28
pre-2018 mismatches are sessions that ran past midnight. The fix moved no
vote across a term boundary.

**Party-code mapping added** (from Cleaned ballot table, "`party` vs
`party_raw`, and `PARTY_MAP`"):

- **`party` vs `party_raw`, and `PARTY_MAP`** (added 2026-11-06):

Verified after the change: row count unchanged
(4,331,180), duplicate pairs 0, `skl`/`uv`/`si`/`hh` absent from `party`
but present in `party_raw` (12,575 rows remapped), `kd` now starts
1996-06-12 (21 MPs) and `sin` 2017-06-14 (21 MPs). Because `uv`/`si` now
merge into `sin`, `term_matrix.py` outputs for 2015-19 (and any 1995-99 /
1999-03 `skl` MPs) change after a rebuild — re-run them.

**Live-data snapshot** (from Cleaned ballot table, intro):

Facts verified against the live data (714 MPs, 4,331,180 ballot rows, 21,765
votes, latest vote 2026-10-23, as of 2026-11-06):

## 2026-07-19

**`--update` verified on real data** (from Architecture notes):

- **`--update` verified on real data (2026-07-19)**: `--sync --update`
  resumed from the tail (vote table page 431, ballot table page 86420),
  fetched +421 vote rows and +18569 ballot rows, and the two-page rewind
  overlap was correctly deduped by INSERT OR IGNORE. `ballots_clean` grew
  4,310,882 → 4,324,812 (+13,930) with older terms unchanged, confirming the
  API appends new rows at the tail rather than reordering — the assumption
  `--update`'s page arithmetic depends on.

## 2026-07-11

Undated in CLAUDE.md; date taken from git commit 6ab643a ("term matrix
feature, the source-level padding fix, and the docs that describe both").

**Party trimming moved to the source** (from Cleaned ballot table,
"`ballots_clean.party` is trimmed at the source"):

Previously `party` was only lowercased, not trimmed, and analysis code
had to strip it locally; that workaround has been removed now that the
fix lives in `build_clean.py` (see the layering rule under Architecture
notes).
