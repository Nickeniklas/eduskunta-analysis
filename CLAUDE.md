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

   `analyse_votes.py` is the older, superseded entry point — it reads the
   raw API tables directly instead of `ballots_clean`, covers the whole
   dataset instead of one term at a time, and additionally produces
   `rebels.csv` / `surprises.csv` (party-line-breaking and closest-vote
   reports that the term-scoped pipeline does not yet have equivalents
   for). Kept for that reason; prefer `term_matrix.py` for anything
   term-scoped.

Data is CC BY 4.0 (credit: Eduskunta / Parliament of Finland).

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

# Inspect a table's real column names + one sample row before relying on
# the column-name guesses in analyse_votes.py
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

# Older, whole-dataset analysis (raw tables, superseded by term_matrix.py
# except for rebels.csv / surprises.csv, which have no term_matrix.py equivalent yet)
python analyse_votes.py
python analyse_votes.py --db custom.db --min-votes 20

# Override guessed column names if the API schema changes (see "Column
# name guessing" below for the full flag list)
python analyse_votes.py --col-mp EdustajaId --col-party RyhmaLyhenne
```

### Dependencies

Listed in `requirements.txt`: `pandas numpy scikit-learn matplotlib umap-learn`.
`umap-learn` is optional — used for a nicer 2D projection if installed, falls
back to PCA otherwise. `fetch_votes.py` only uses the standard library.

There is no test suite, linter, or build step in this repo.

## Architecture notes

- **Schema tolerance**: `fetch_votes.py` stores every API column as TEXT
  verbatim (`_ensure_table`/`_flush`), so the cache schema always matches
  whatever the API currently returns. `analyse_votes.py` does NOT hardcode
  Finnish column names directly — it guesses via `BALLOT_DEFAULTS` /
  `VOTE_DEFAULTS` (lists of candidate names tried in order via `pick()`), and
  every guessable field has a corresponding `--col-*` CLI override. If the
  Eduskunta API renames a column, update the candidate lists or pass the
  override flag rather than rewriting the loader.
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
  Pass `--reset` to wipe and start clean. `--since` exists only on
  `analyse_votes.py`, and only as a placeholder (not implemented as a real
  filter); `fetch_votes.py` has no `--since`.
- **NULLs in a UNIQUE index gotcha**: SQLite treats NULLs as distinct from
  each other in a UNIQUE index, so a key with a NULL part never conflicts and
  `INSERT OR IGNORE` lets exact duplicates straight through. The vote table
  used to be keyed on *every* column; `IstuntoIlmoitettuAlkuaika` is often
  NULL, and 4 vote events (8 rows with their Swedish twins, all from the
  2009-01-15 session) got cached twice. Every ballot of those votes then fanned
  out in `build_clean.py`'s join, giving 796 duplicate (person, vote) pairs in
  `ballots_clean`. Fixed 2026-11-06 by keying the vote table on
  `(AanestysId, KieliId)` (verified unique and never NULL once exact
  duplicates are ignored). Key columns in `KEY_COLS` must never be nullable.
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
- **`--update` verified on real data (2026-07-19)**: `--sync --update`
  resumed from the tail (vote table page 431, ballot table page 86420),
  fetched +421 vote rows and +18569 ballot rows, and the two-page rewind
  overlap was correctly deduped by INSERT OR IGNORE. `ballots_clean` grew
  4,310,882 → 4,324,812 (+13,930) with older terms unchanged, confirming the
  API appends new rows at the tail rather than reordering — the assumption
  `--update`'s page arithmetic depends on.
- **Ballot normalisation**: raw Finnish vote choices (`Jaa`/`Ei`/`Tyhjää`/`Poissa`)
  are normalised via `CHOICE_MAP` to `yes`/`no`/`empty`/`absent`. Anything
  unrecognised defaults to `absent`. Only `yes`/`no` are used for similarity
  encoding (`+1`/`-1`); `empty`/`absent` encode as `0` so non-votes don't fake
  agreement.
- **"Party line" definition**: for `rebels.csv`, the party line on a vote is
  the *mode* (majority choice) of that party's `yes`/`no` votes on that vote —
  not the government/opposition whip position.
- **API politeness**: `fetch_votes.py` enforces `PER_PAGE = 100` (API hard
  cap) and sleeps `SLEEP = 0.3s` between pages, with exponential backoff on
  HTTP 429. Don't remove these when editing the fetch loop.
- **Pipeline order**: `fetch_votes.py` → `build_clean.py` → `term_matrix.py`
  → `pairs_report.py` (or `analyse_votes.py` instead of the last two).
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
  call it. `analyse_votes.py` is the exception: it's not term-scoped, doesn't
  import `paths.py`, and still writes `mp_map.png` / `clusters.csv` /
  `rebels.csv` / `surprises.csv` to the repo root.

## Cleaned ballot table (`ballots_clean`)

`build_clean.py` joins the two raw API tables into a single clean table.
Facts verified against the live data (714 MPs, 4,331,180 ballot rows, 21,765
votes, latest vote 2026-10-23, as of 2026-11-06):

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
  with no time part. Verified 2026-11-06 against each vote's own
  `AanestysAlkuaika`: 7,801 / 7,802 Finnish rows from 2018 on agree (the one
  mismatch is a session whose votes ran two days after it opened), and all 28
  pre-2018 mismatches are sessions that ran past midnight. The fix moved no
  vote across a term boundary. Raw-table queries (including
  `analyse_votes.py`) still see the unshifted timestamps.
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
  Previously `party` was only lowercased, not trimmed, and analysis code
  had to strip it locally; that workaround has been removed now that the
  fix lives in `build_clean.py` (see the layering rule under Architecture
  notes).
- **`party` vs `party_raw`, and `PARTY_MAP`** (added 2026-11-06):
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
  historical label. Verified after the change: row count unchanged
  (4,331,180), duplicate pairs 0, `skl`/`uv`/`si`/`hh` absent from `party`
  but present in `party_raw` (12,575 rows remapped), `kd` now starts
  1996-06-12 (21 MPs) and `sin` 2017-06-14 (21 MPs). Because `uv`/`si` now
  merge into `sin`, `term_matrix.py` outputs for 2015-19 (and any 1995-99 /
  1999-03 `skl` MPs) change after a rebuild — re-run them.
- **`terms` table**: `build_clean.py` also (re)builds a small `terms`
  reference table (`term`, `start_date`, `end_date`) hardcoded as the `TERMS`
  list in that script — one row per Finnish parliamentary term, covering
  1995-99 through 2023-27. A ninth row will be needed once the 2027 election
  result is known; update `TERMS` in `build_clean.py` when it is. Join on
  `date(vote_date) BETWEEN start_date AND end_date`. `vote_date` is already a
  plain `YYYY-MM-DD`, so the `date()` is now a harmless no-op (existing
  queries in `build_clean.py` / `term_matrix.py` keep it). It only matters
  for a timestamp with a time part, e.g. raw `IstuntoPvm`.
