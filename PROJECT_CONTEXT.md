# Project context: Eduskunta vote analysis

## What this is

A data project built on the Finnish Parliament (Eduskunta) open data. It pulls the
full parliamentary voting record and analyses it two ways:

1. **Vote similarity map** — an MP-by-MP agreement matrix built from voting records,
   projected to 2D and clustered, to show the *real* voting blocs versus the official
   party/coalition split. The interesting output is cross-party blocs and individual
   MPs who drift from their group.
2. **Surprise / rebel detector** — flags MPs who broke from their party's majority on a
   vote (a rebel/independence ranking) and votes that split unusually close
   (nail-biters).

Both features run off the same two tables, so building one gives the other almost for
free.

## Data source

- API base: `https://avoindata.eduskunta.fi/api/v1`
- Old table-based REST API (returns raw DB tables as JSON/XML). This is the
  developer-friendly one and is the right choice over the newer search/download portal.
- No API key, no auth, no registration.
- Licence: CC BY 4.0 — free to use including commercially, must credit
  "Eduskunta / Parliament of Finland".

### Key tables
- `SaliDBAanestys` — one row per vote event (date, title, tallies). Small.
- `SaliDBAanestysEdustaja` — one row per MP per vote (the actual ballot: jaa / ei /
  tyhjää / poissa). This is the main table for all analysis. Large.

### API mechanics
- Page rows: `/tables/{TableName}/rows?page=0&perPage=100`
- Hard cap of **100 rows per page** — all bulk reads must paginate.
- Filter by exact column match: `&columnName=AanestysId&columnValue=37605`
  (exact match only — there is **no** server-side greater-than / range filter).
- `/tables` lists all tables.

## Scale and the big gotcha

- Voting data goes back to **1976**. The ballot table (`SaliDBAanestysEdustaja`) is
  roughly **3–5 million rows** (≈200 MP rows per vote × tens of thousands of votes).
- A full historic sync is a **multi-hour job** (tens of thousands of pages, with a
  polite sleep between requests). This is a one-time cost since data is cached locally;
  afterwards `--sync --update` tops the cache up with newly published votes in minutes
  (see "Keeping the data current" below).
- The API is meant for light use; Eduskunta can throttle heavy single users. Correct
  architecture: **batch-pull once into local SQLite, then analyse the local copy.**
  Never hit the live API per page-view.

### KNOWN PAIN POINT (RESOLVED)
The original fetcher did `DELETE FROM table` then refilled from page 0 on every sync,
so a sync wasn't resumable — a stop partway meant starting over. After losing a ~2h run
this way, this was fixed: `--sync` now counts cached rows, resumes from the right page,
and uses `INSERT OR IGNORE` + a `_sync_state` checkpoint table so an interrupted sync
picks up where it left off. `--reset` still does the old wipe-and-restart if you want
it. See the "Sync is resumable" note in [CLAUDE.md](CLAUDE.md).

Note: this project needs **full historic data** (analysis spans the whole record), so
do NOT default to recency filters or partial pulls. Full history is the requirement.
(In practice the live API's voting data starts in 1996, not 1976 as originally assumed
here — `votes.db` currently holds the full 1996–2026 record, matching the `terms` table
in `build_clean.py`.)

### Keeping the data current

`--sync` marks each table `done` when it finishes and skips it on later runs, so a
completed cache never refreshes on its own. `python fetch_votes.py --sync --update`
ignores that flag and resumes near the tail, re-fetching two pages of overlap that
`INSERT OR IGNORE` dedups. Then re-run `python build_clean.py` — `ballots_clean` is
rebuilt from scratch, so new raw rows are invisible to analysis until it does.

Verified on real data 2026-07-19: +421 vote rows, +18,569 ballot rows, `ballots_clean`
4,310,882 → 4,324,812, older terms unchanged. That last part matters — it confirms the
API appends at the tail rather than reordering, which is the assumption `--update`'s
page arithmetic rests on. If a future update ever shows older terms shifting, that
assumption has broken and `--sync --reset` is the ground-truth rebuild.

## Current state

The full pipeline described in [README.md](README.md) is built and working, run
end-to-end at least once for term `2019-23`. As of 2026-07-19 the cache holds
4,324,812 cleaned ballot rows across 714 MPs, latest vote 2026-06-22:

- `fetch_votes.py` — resumable sync of the two raw tables into `votes.db`. Has
  `--peek`, `--list`, `--sync` (`--update` for an incremental refresh, `--reset` for a
  full wipe). Schema-tolerant (column names guessed from candidates).
- `build_clean.py` — rebuilds `ballots_clean` (one row per person/vote, Finnish-only,
  trimmed/lowercased/numeric) and the `terms` reference table. All value normalisation
  lives here now (see the "Layering rule" in CLAUDE.md) — analysis scripts assume
  `ballots_clean` is already clean and never clean values themselves.
- `term_matrix.py` — the current main analysis entry point. Per term: MP x MP
  agreement matrix (vectorised, no Python loop over pairs), a lookup CSV
  (name/party/KMeans cluster), and the similarity-map PNG.
- `pairs_report.py` — turns a term's agreement matrix into readable reports:
  top cross-party pairs, within-party dissenters, per-MP ally lookup, cluster
  membership.
- `analyse_votes.py` — the original whole-dataset entry point (reads the raw tables
  directly, not `ballots_clean`). Superseded by the `term_matrix.py` /
  `pairs_report.py` pair for everything except `rebels.csv` / `surprises.csv`
  (party-line-breaking and closest-vote reports), which have no term-scoped
  equivalent yet — kept around for those two reports.

### Open items (not blocking, nothing urgent)
1. Port `rebels.csv` / `surprises.csv` (party-line rebels, closest votes) to the
   term-scoped pipeline, if still wanted — the last reason `analyse_votes.py` is kept.
2. `build_clean.py`'s `TERMS` list needs a ninth row once the 2027 election result is
   known.

## Interpretation caveat

Finland has coalition governments, so government parties vote together by design. The
dominant split in the data will be **government vs opposition**, not left vs right. The
real findings are the deviations: opposition parties occasionally siding with the
government, and individual MPs drifting from their bloc. Don't over-read the obvious
structure as a discovery.

## Prior art (don't rebuild these)

- **Parlamenttisampo.fi** (Aalto SeCo) — big academic linked-data treatment of speeches.
- **Lakitutka** — law-tracking research engine.
- Yle's "Vallan vahtibotti" and robot writer.
- **valtiodata.org** — MP attendance tracking, budget game.
- GitHub wrappers like `codeclown/eduskunta-data`.

Saturated angles: "how did MP X vote", attendance by party. The vote-similarity map and
the rebel/surprise analysis are the underused angles this project targets.

## Owner working context

- Based in Finland. Works across Finnish, Swedish (FinSvenska), and English.
- Comfortable with Python, Claude Code, local tooling.
- This started as an ideation session looking for non-generic Nordic/Finnish daily data
  streams; the Eduskunta voting API was chosen as the most underused accessible source.
