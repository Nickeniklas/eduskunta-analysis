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
3. `analyse_votes.py` — reads `votes.db` and produces:
   - `mp_map.png` + `clusters.csv`: an MP-by-MP voting-similarity map (cosine
     similarity → PCA or UMAP projection → KMeans clusters), coloured by party.
   - `rebels.csv`: MPs ranked by how often they voted against their own
     party's majority ("party line") on a given vote.
   - `surprises.csv`: votes ranked by how close the yes/no split was.

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

# Wipe cached vote tables and do a full re-pull from scratch
python fetch_votes.py --sync --reset

# Rebuild the cleaned ballots_clean table (requires votes.db from --sync)
python build_clean.py
python build_clean.py --db custom.db

# Run the analysis (requires votes.db from --sync)
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
  cached rows, computes the start page, and uses `INSERT OR IGNORE` against a
  unique index so re-fetching an incomplete page is harmless. Progress is
  checkpointed to a `_sync_state` table after every 1 000-row buffer flush.
  Pass `--reset` to wipe and start clean. `--since` is accepted by both scripts
  but not yet implemented as a real filter (placeholder).
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
- **Pipeline order**: `fetch_votes.py` → `build_clean.py` → analysis.
  `build_clean.py` must be re-run after every `fetch_votes.py --sync` that
  pulls new rows, since it rebuilds `ballots_clean` from scratch (`DROP TABLE
  IF EXISTS` + full `CREATE TABLE ... AS SELECT`).

## Cleaned ballot table (`ballots_clean`)

`build_clean.py` joins the two raw API tables into a single clean table.
Facts verified against the live data (714 MPs, ~4.31M ballot rows as of
2026-07-11):

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
- **Vote date** is `IstuntoPvm` on `SaliDBAanestys`, ISO format with a
  `00:00:00` time component (date only, no real time-of-day precision).
- **Finnish `Tyhjää` = Swedish `Avstår` + `Blank` combined**: Swedish
  distinguishes two abstention types where Finnish only has one, which is
  part of why cleaning/analysis works from the Finnish-language rows only.
- **`ballots_clean` encoding**: one row per (person, vote); `party` is
  lowercased; `ballot` is `1` (Jaa/yes), `-1` (Ei/no), `0` (Tyhjää/abstain),
  or `NULL` (Poissa/absent); only Finnish-language, non-annulled
  (`AanestysMitatoity = '0'`) votes are included. Indexed on `person_id` and
  `vote_id`.
