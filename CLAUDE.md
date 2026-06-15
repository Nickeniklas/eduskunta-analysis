# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small two-script pipeline that downloads Finnish Parliament (Eduskunta) voting
data from the open data API and analyses voting behaviour:

1. `fetch_votes.py` — pulls `SaliDBAanestys` (vote events) and
   `SaliDBAanestysEdustaja` (per-MP ballots) from
   `https://avoindata.eduskunta.fi/api/v1` and caches them as TEXT columns in a
   local SQLite DB (`votes.db`).
2. `analyse_votes.py` — reads `votes.db` and produces:
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

# Full sync into votes.db (paginates the API at 100 rows/page, ~0.3s between pages)
python fetch_votes.py --sync
python fetch_votes.py --sync --db custom.db

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
- **Sync is a full refresh**: `--sync` does `DELETE FROM <table>` then
  reinserts everything each run — there's no incremental/delta sync. `--since`
  is currently accepted but not implemented as a real filter (noted as a
  placeholder in both scripts).
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
