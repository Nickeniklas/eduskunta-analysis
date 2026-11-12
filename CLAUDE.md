# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small pipeline that downloads Finnish Parliament (Eduskunta) voting
data from the open data API and analyses voting behaviour:

1. `fetch_votes.py` — pulls `SaliDBAanestys` (vote events) and
   `SaliDBAanestysEdustaja` (per-MP ballots) from
   `https://avoindata.eduskunta.fi/api/v1` and caches them as TEXT columns in a
   local SQLite DB (`votes.db`).
2. `build_clean.py` — rebuilds `ballots_clean` in `votes.db`, a normalised
   one-row-per-(person, vote) table with numeric ballots and lowercased
   party codes (see "Cleaned ballot table" below).
3. `term_matrix.py` — the main analysis entry point. Reads `ballots_clean`
   (not the raw tables) for a single parliamentary term and produces:
   - `agreement_{term}.csv`: MP x MP pairwise voting-agreement matrix.
   - `lookup_{term}.csv`: `person_id` → `name`, `party`, `cluster` (KMeans
     label) for that term.
   - `mp_map_{term}.png`: a 2D projection (UMAP if installed, else PCA) of
     the agreement matrix, coloured by party.
   - printed summary stats: MPs kept/dropped, within- vs cross-party mean
     agreement per party, and each cluster's party composition.
4. `pairs_report.py` — readable reports from `term_matrix.py`'s CSV outputs
   (no DB access). Default run writes `cross_party_{term}.csv` (highest
   agreement across party lines) and `dissenters_{term}.csv` (lowest
   agreement within a party). `--mp` prints one MP's closest/furthest
   voting allies (accepts a person_id or a partial, case-insensitive name);
   `--cluster N` lists a KMeans cluster's members by name.

   Rebel/surprise detection (party-line-breaking MPs, closest votes) is not
   built yet: it will be part of `longitudinal.py`, computed per vote from
   `ballots_clean`. A tied party vote (equal yes and no among a party's
   members) means "no party line" — the removed legacy script broke ties
   alphabetically, which wrongly made `no` the line and every `yes` voter a
   rebel.

Data is CC BY 4.0 (credit: Eduskunta / Parliament of Finland).

## Status

- **Pipeline**: `fetch_votes.py` → `build_clean.py` → `term_matrix.py` →
  `pairs_report.py` is the current (and only) pipeline.
- **Local `votes.db`** (last synced and rebuilt 2026-11-06, re-checked
  2026-11-09): `SaliDBAanestys` 43,595 rows, `SaliDBAanestysEdustaja`
  8,675,295 rows; `ballots_clean` 4,331,180 rows, 714 persons, 21,765 votes,
  latest vote 2026-10-23, 0 duplicate (person, vote) pairs, 12,575 rows
  remapped by `party_map`. The vote-table unique index is already on
  `(AanestysId, KieliId)`. `_sync_state.rows` for `SaliDBAanestys` still
  reads 43,603 (pre-dedup); harmless, see "Sync is resumable".
- **Outputs**: `term_matrix.py` has been run for all eight terms
  (`outputs/1995-99` … `outputs/2023-27`), after the `party_map` rebuild.
  No `pairs_report.py` outputs are on disk; run it per term as needed.
- **Next planned build**: `longitudinal.py` (cross-term comparison from the
  per-term CSVs), not started; plan and open decisions are in
  `docs/PROJECT_CONTEXT.md` under "Open items".
- **`TERMS`** covers 1995-99 through 2023-27; add a ninth row to `TERMS` in
  `build_clean.py` once the 2027 election result is known.
- No test suite, linter, build step, CI, deployment, or scheduled jobs. Syncs
  are run by hand.

Session history: docs/STATUS_LOG.md (read when needed)

## Setup

```bash
# Create and activate a virtualenv (Windows / PowerShell)
python -m venv venv
./venv/Scripts/Activate.ps1

# Create and activate a virtualenv (bash / Git Bash)
python -m venv venv
source venv/Scripts/activate

# Install dependencies
pip install -r requirements.txt
```

## Commands

```bash
# Discover available API tables (sanity check / debugging)
python fetch_votes.py --list

# Inspect a table's real column names + one sample row
python fetch_votes.py --peek SaliDBAanestysEdustaja
python fetch_votes.py --peek SaliDBAanestys

# Sync into votes.db — RESUMABLE (paginates at 100 rows/page, ~0.3s between pages)
python fetch_votes.py --sync
python fetch_votes.py --sync --db custom.db

# Incremental refresh: pull whatever the API has added since the last sync.
# Ignores the `done` flag in _sync_state (which otherwise makes --sync skip
# completed tables) and rewinds 2 pages as a safety overlap.
# Re-run build_clean.py afterwards.
python fetch_votes.py --sync --update

# Wipe cached vote tables and do a full re-pull from scratch
python fetch_votes.py --sync --reset

# Rebuild the cleaned ballots_clean table (requires votes.db from --sync)
python build_clean.py
python build_clean.py --db custom.db

# Run the term-scoped analysis (requires ballots_clean from build_clean.py)
python term_matrix.py --term 2019-23
python term_matrix.py --term 2019-23 --db custom.db --min-ballots 100 --min-shared 50

# Readable reports from the term outputs (requires term_matrix.py run first)
python pairs_report.py --term 2019-23                  # cross-party + dissenter CSVs
python pairs_report.py --term 2019-23 --top 30         # print more rows
python pairs_report.py --term 2019-23 --mp "Valtonen"  # one MP's allies (name or person_id)
python pairs_report.py --term 2019-23 --cluster 2      # members of KMeans cluster 2
```

### Dependencies

Listed in `requirements.txt`, pinned to exact versions: `pandas numpy
scikit-learn matplotlib umap-learn pytest` (the code is version-sensitive,
see the `stack()` gotcha below). `umap-learn` is optional — used for a nicer 2D projection if installed, falls
back to PCA otherwise. `fetch_votes.py` only uses the standard library.

## Architecture notes

- **Schema tolerance**: `fetch_votes.py` stores every API column as TEXT
  verbatim (`_ensure_table`/`_flush`), so the cache schema always matches
  whatever the API returned when the table was created. Downstream, only
  `build_clean.py` names raw columns; if the Eduskunta API renames one, fix
  it there.
- **Sync is resumable**: `--sync` resumes from where it left off — it counts
  cached rows, computes the start page, and inserts against a unique index on
  each table's natural key (`KEY_COLS`) so re-fetching an incomplete page is
  harmless: `INSERT OR IGNORE` for the ballot table (`EdustajaId, AanestysId`),
  `INSERT OR REPLACE` for the vote table (`AanestysId, KieliId`), so API edits
  to a vote row in the `--update` overlap overwrite the cached copy. Progress is
  checkpointed to a `_sync_state` table after every 1 000-row buffer flush.
  Once a table finishes it is flagged `done` and skipped by later `--sync`
  runs; `--update` ignores that flag and starts from
  `max(0, have // PER_PAGE - 2)` so the last couple of pages are re-fetched
  as an overlap (the unique index makes the duplicates no-ops).
  Only the live row count drives the resume page; `_sync_state.rows` is
  informational and can lag it.
  Pass `--reset` to wipe and start clean. `fetch_votes.py` has no `--since`.
- **`--update` assumes the API appends at the tail**: new rows arrive at the
  end of each table rather than reordering existing pages; `--update`'s page
  arithmetic depends on this. Confirmed on real data (see the log).
- **NULLs in a UNIQUE index gotcha**: SQLite treats NULLs as distinct from
  each other in a UNIQUE index, so a key with a NULL part never conflicts and
  `INSERT OR IGNORE` lets exact duplicates straight through. Key columns in
  `KEY_COLS` must never be nullable. (This is why the vote table is keyed on
  `(AanestysId, KieliId)`, not on every column.)
- **Changing `KEY_COLS` doesn't migrate an existing DB**: `_ensure_table`
  uses `CREATE UNIQUE INDEX IF NOT EXISTS` under a fixed name
  (`ux_{table}`), so an existing `votes.db` keeps its old index. Migrate by
  hand — delete exact-duplicate rows keeping the lowest rowid (compare with
  `IS` so NULL matches NULL), drop `ux_{table}`, recreate it on the new key —
  or run `--sync --reset`.
- **Ballot encoding in `term_matrix.py`**: from `ballots_clean.ballot`,
  absent is `NULL` (excluded from shared votes), while abstain (`0`) is a
  cast ballot and two abstentions count as agreement.
- **"Party line" definition** (for the planned rebel detection): the party
  line on a vote is the majority choice of that party's `yes`/`no` votes on
  that vote — not the government/opposition whip position. A tie means no
  party line (nobody is a rebel on that vote).
- **API politeness**: `fetch_votes.py` enforces `PER_PAGE = 100` (API hard
  cap) and sleeps `SLEEP = 0.3s` between pages, with exponential backoff on
  HTTP 429. Don't remove these when editing the fetch loop.
- **Pipeline order**: `fetch_votes.py` → `build_clean.py` → `term_matrix.py`
  → `pairs_report.py`.
  `build_clean.py` must be re-run after every `fetch_votes.py --sync` that
  pulls new rows, since it rebuilds `ballots_clean` from scratch
  (`DROP TABLE IF EXISTS` + full `CREATE TABLE ... AS SELECT`);
  `term_matrix.py` reads only `ballots_clean` + `terms`, not the raw tables,
  so it also needs `build_clean.py` to have been run at least once.
  `pairs_report.py` reads only `agreement_{term}.csv` + `lookup_{term}.csv`
  from `outputs/{term}/` (no DB), so `term_matrix.py` must have been run
  for that term first.
- **`term_matrix.py`'s vectorized agreement**: `pairwise_agreement()` builds
  one MP x vote pivot (`NaN` = absent) and computes, for each ballot value
  `v` in `{1, -1, 0}`, an indicator matrix `(X == v)` (NaN-safe since
  `NaN == v` is `False`); `equal_votes` is the sum over `v` of
  `indicator @ indicator.T`, `shared_votes` is `voted @ voted.T`, and
  `agreement = equal_votes / shared_votes` with pairs below `--min-shared`
  set to `NaN`. No Python-level loop over MP pairs.
- **Cluster labels are per-run**: `term_matrix.py` KMeans-clusters the 2D
  projection and writes the label into `lookup_{term}.csv`'s `cluster`
  column. The numbers are arbitrary and can shuffle between runs (KMeans is
  seeded, but any change to the data or projection renumbers them) — never
  hardcode "cluster 2 = greens"; identify clusters by the party-composition
  printout of the run that produced the CSV.
- **pandas `stack()` gotcha**: newer pandas keeps NaN rows in `stack()` by
  default (the old dropna behaviour changed). `pairs_report.py` relies on an
  explicit `.dropna()` after masking the matrix's lower triangle — removing
  it silently reintroduces every masked cell as a NaN row and inflates the
  pair count. Keep the explicit `.dropna()` in any similar melt.
- **Layering rule**: raw API tables are never cleaned in analysis code.
  All normalization (trimming, casing, value mapping) happens in
  build_clean.py, once. Analysis scripts read ballots_clean and must
  assume its values are already clean — if a value turns out dirty,
  fix build_clean.py and rebuild, never work around it downstream.
- **Output location convention**: `term_matrix.py` and `pairs_report.py`
  write/read their term-scoped artifacts (`agreement_{term}.csv`,
  `lookup_{term}.csv`, `mp_map_{term}.png`, `cross_party_{term}.csv`,
  `dissenters_{term}.csv`) under `outputs/{term}/`, via the `output_path()` /
  `output_dir()` helpers in `paths.py`. That's the one place the convention
  lives — to change where outputs go, edit `paths.py`, not the scripts that
  call it.

## Cleaned ballot table (`ballots_clean`)

`build_clean.py` joins the two raw API tables into a single clean table.
Facts about the source data that the cleaning step relies on:

- **Raw tables are language-doubled**: both `SaliDBAanestys` and
  `SaliDBAanestysEdustaja` contain a full duplicate row set per language
  (`KieliId`: `'1'` = Finnish, `'2'` = Swedish). Any query against these raw
  tables must join to `SaliDBAanestys` and filter `KieliId = '1'`, or it will
  double-count votes and mix Finnish/Swedish choice strings.
- **Raw text values are fixed-width, space-padded**: e.g.
  `EdustajaAanestys` stores `'Jaa                 '`, not `'Jaa'`. Any exact
  string match against raw columns needs `TRIM()` first — this is why
  `build_clean.py`'s `CASE` wraps the column in `TRIM(...)`.
- **`EdustajaId` is not a person key** — it's a per-row/per-term ID. The
  real person identifier is `EdustajaHenkiloNumero`. Across the dataset
  there are 714 distinct persons, with no namesake collisions (no two
  different `EdustajaHenkiloNumero` share a name), but ~19 persons have 2
  different name spellings on record (marriage/legal name changes, e.g.
  Elina Lepomäki → Elina Valtonen).
- **Vote date** comes from `IstuntoPvm` (session date) on `SaliDBAanestys`.
  It is Finnish local midnight, but the raw timestamp is not consistently
  `00:00:00`: up to 2017 it mostly is, while from 2018 on (and sporadically
  2009-15) the API serialises it as UTC, i.e. `22:00:00` (EET, winter) or
  `21:00:00` (EEST, summer) on the *previous* day. Taking `date()` of the raw
  value therefore puts ~7,800 votes one day early. `build_clean.py` stores
  `vote_date = date(IstuntoPvm, '+3 hours')`, a plain local `YYYY-MM-DD`
  with no time part. Raw-table queries still see the unshifted timestamps.
- **Finnish `Tyhjää` = Swedish `Avstår` + `Blank` combined**: Swedish
  distinguishes two abstention types where Finnish only has one, which is
  part of why cleaning/analysis works from the Finnish-language rows only.
- **`ballots_clean` encoding**: one row per (person, vote); `party` is the
  canonical lowercased party code and `party_raw` the code as recorded (see
  `party` vs `party_raw` below); `ballot` is `1` (Jaa/yes), `-1` (Ei/no), `0` (Tyhjää/abstain),
  or `NULL` (Poissa/absent); only Finnish-language, non-annulled
  (`AanestysMitatoity = '0'`) votes are included. Indexed on `person_id` and
  `vote_id`. `BUILD_SQL` joins ballots to a `SELECT DISTINCT AanestysId,
  IstuntoPvm, KieliId, AanestysMitatoity` subquery rather than the raw vote
  table, so a duplicated raw vote row can't fan out ballots; `build_clean.py`
  prints the number of duplicate (person_id, vote_id) pairs after every
  rebuild, and it must be 0.
- **`ballots_clean.party` is trimmed at the source**: `build_clean.py`'s
  `BUILD_SQL` wraps `EdustajaRyhmaLyhenne` in `LOWER(TRIM(...))`, so
  `party` values are already clean (e.g. `'kok'`, not `'kok       '`).
  Analysis code must not strip or re-case it (see the layering rule under
  Architecture notes).
- **`party` vs `party_raw`, and `PARTY_MAP`**:
  `party_raw = LOWER(TRIM(EdustajaRyhmaLyhenne))` is the code exactly as the
  API recorded it at the time of the vote. `party = COALESCE(canonical_code,
  party_raw)` via a `LEFT JOIN` to the `party_map` table, which
  `build_clean.py` (re)writes from its hardcoded `PARTY_MAP` list (next to
  `TERMS`) *before* building `ballots_clean`. Current mappings:
  `skl→kd`, `uv→sin`, `si→sin`, `hh→liik`. **Renames only**: a mapping is
  for the same parliamentary group appearing under an older or interim code.
  Splits (a group breaking away from its party) and one-MP groups keep their
  own codes — never map them into a parent party. Analysis code uses
  `party`; `party_raw` is there for auditing or for anything that needs the
  historical label. Any change to `PARTY_MAP` changes `term_matrix.py`
  outputs for the affected terms: rebuild, then re-run those terms.
- **`terms` table**: `build_clean.py` also (re)builds a small `terms`
  reference table (`term`, `start_date`, `end_date`) hardcoded as the `TERMS`
  list in that script — one row per Finnish parliamentary term, covering
  1995-99 through 2023-27. A ninth row will be needed once the 2027 election
  result is known; update `TERMS` in `build_clean.py` when it is. Join on
  `date(vote_date) BETWEEN start_date AND end_date`. `vote_date` is already a
  plain `YYYY-MM-DD`, so the `date()` is now a harmless no-op (existing
  queries in `build_clean.py` / `term_matrix.py` keep it). It only matters
  for a timestamp with a time part, e.g. raw `IstuntoPvm`.
