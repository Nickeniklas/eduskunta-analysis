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
  polite sleep between requests). This is a one-time cost since data is cached locally.
- The API is meant for light use; Eduskunta can throttle heavy single users. Correct
  architecture: **batch-pull once into local SQLite, then analyse the local copy.**
  Never hit the live API per page-view.

### KNOWN PAIN POINT (must fix)
The current fetcher does `DELETE FROM table` then refills from page 0 on every sync.
That means **a sync is not resumable** — if it stops partway, the partial data can't be
continued and you start over. After losing a ~2h run this way, the next priority is to
**make the sync resumable / checkpointed** so a stop never costs the whole run.

Note: this project needs **full historic data** (analysis spans the whole record), so
do NOT default to recency filters or partial pulls. Full history is the requirement.

## Current state

- `fetch_votes.py` — pulls the two tables into `votes.db` (SQLite), with pagination and
  basic retry/backoff. Has a `--peek` to confirm real column names, `--list`, `--sync`.
  Schema-tolerant (column names are guessed from candidates).
- `analyse_votes.py` — reads `votes.db`, builds the agreement matrix (yes=+1, no=−1,
  abstain/absent=0 so they don't fake agreement), projects to 2D (UMAP if installed,
  else PCA), clusters (KMeans), colours by party. Outputs `mp_map.png`, `clusters.csv`,
  `rebels.csv`, `surprises.csv`. Also schema-tolerant with `--col-*` overrides.

### Immediate to-do
1. Make `fetch_votes.py` resumable (checkpoint progress; no full wipe on restart). TOP
   priority.
2. Confirm the real column names via `--peek` before trusting the analysis defaults
   (current Finnish column-name guesses: `AanestysId`, `RyhmaLyhenne`,
   `EdustajanAanestys`, etc. — unverified against the live API).

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
