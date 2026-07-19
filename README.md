# eduskunta-analysis

Analyses voting behaviour in the Finnish Parliament (Eduskunta) using the
[Eduskunta open data API](https://avoindata.eduskunta.fi/api/v1). Caches the
full voting record (1996–present) locally in SQLite, cleans it into an
analysis-ready table, then per parliamentary term:

- builds an **MP-by-MP voting-agreement matrix** and a 2D **similarity map**
  (who actually votes alike, vs. the official party split),
- finds the **highest cross-party pairs** (MPs who vote alike despite
  different parties) and the **lowest within-party pairs** (internal
  dissenters), and
- lets you query any single MP's closest and furthest **voting allies**.

Data is CC BY 4.0 (credit: Eduskunta / Parliament of Finland).

## Pipeline

```
fetch_votes.py  ->  build_clean.py  ->  term_matrix.py  ->  pairs_report.py
(raw API cache)     (ballots_clean)     (agreement CSVs)    (readable reports)
```

1. `fetch_votes.py` — resumable sync of the two raw API tables
   (`SaliDBAanestys` vote events, `SaliDBAanestysEdustaja` per-MP ballots)
   into `votes.db`. Use `--sync --update` to top up an already-complete
   cache with newly published votes.
2. `build_clean.py` — rebuilds `ballots_clean`: one row per (person, vote),
   Finnish-language rows only (the raw tables are duplicated per language),
   trimmed/normalised values, numeric ballots. Also builds the `terms`
   reference table. **Re-run after every sync.**
3. `term_matrix.py` — for one parliamentary term, produces the MP x MP
   agreement matrix, an MP lookup (name, party, cluster), and the
   similarity-map PNG.
4. `pairs_report.py` — turns those CSVs into readable reports: top
   cross-party pairs, within-party dissenters, per-MP ally lists, and
   cluster membership lists.

`analyse_votes.py` is the older whole-dataset entry point, superseded by
`term_matrix.py` except for its `rebels.csv` / `surprises.csv` reports.

## Tech stack

- **Python 3** (standard library only for fetching)
- **SQLite** for local caching (`votes.db`)
- **pandas / numpy** for data wrangling
- **scikit-learn** for agreement, PCA, and KMeans clustering
- **umap-learn** (optional) for a nicer 2D projection than PCA
- **matplotlib** for the map PNG

## Setup

```bash
# Create and activate a virtualenv
python -m venv venv

# Windows / PowerShell
./venv/Scripts/Activate.ps1
# bash / Git Bash
source venv/Scripts/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
# 1. pull the voting data into a local SQLite cache (votes.db)
#    resumable — safe to interrupt and re-run; multi-hour on first run
python fetch_votes.py --sync
python fetch_votes.py --sync --update    # incremental refresh: fetch rows added since last sync
python fetch_votes.py --sync --reset     # wipe and start over

# 2. build the cleaned ballots_clean table (re-run after every sync, --update included)
python build_clean.py

# 3. run the per-term analysis (terms: 1995-99 ... 2023-27)
python term_matrix.py --term 2019-23
python term_matrix.py --term 2019-23 --min-ballots 100 --min-shared 50

# 4. readable reports from the term outputs
python pairs_report.py --term 2019-23                  # cross-party pairs + dissenters
python pairs_report.py --term 2019-23 --mp "Valtonen"  # one MP's closest/furthest allies
python pairs_report.py --term 2019-23 --cluster 2      # who is in KMeans cluster 2
```

### Outputs

All term-scoped outputs are written under `outputs/{term}/` (see `paths.py`
for the convention).

| File | What it is |
|---|---|
| `outputs/{term}/agreement_{term}.csv` | MP x MP agreement matrix (fraction of shared votes cast the same way) |
| `outputs/{term}/lookup_{term}.csv` | person_id → name, party, KMeans cluster |
| `outputs/{term}/mp_map_{term}.png` | 2D similarity map, coloured by party |
| `outputs/{term}/cross_party_{term}.csv` | MP pairs ranked by agreement across party lines |
| `outputs/{term}/dissenters_{term}.csv` | within-party pairs ranked by lowest agreement |

## Notes

- Cluster numbers are arbitrary KMeans labels and can change between runs;
  `term_matrix.py` prints each cluster's party composition so you can tell
  which is which.
- Finland has coalition governments, so the dominant structure in any map is
  government vs opposition, not left vs right. The interesting findings are
  the deviations from that.
- Data quirks (language doubling, space-padded values, person keys) are
  documented in [CLAUDE.md](CLAUDE.md).
