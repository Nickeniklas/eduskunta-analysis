# eduskunta-analysis

Analyses voting behaviour in the Finnish Parliament (Eduskunta) using the
[Eduskunta open data API](https://avoindata.eduskunta.fi/api/v1). Caches the
full voting record locally in SQLite, then:

- builds an **MP-by-MP voting similarity map** (who actually votes alike,
  vs. the official party split), and
- finds **"rebel" MPs** (who break from their party's majority) and
  **"surprise" votes** (closest yes/no splits).

Data is CC BY 4.0 (credit: Eduskunta / Parliament of Finland).

## Tech stack

- **Python 3** (standard library only for fetching)
- **SQLite** for local caching (`votes.db`)
- **pandas / numpy** for data wrangling
- **scikit-learn** for similarity, PCA, and KMeans clustering
- **umap-learn** (optional) for a nicer 2D projection than PCA
- **matplotlib** for the output plot

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
# 1. (optional) sanity-check the API's table/column names
python fetch_votes.py --list
python fetch_votes.py --peek SaliDBAanestysEdustaja

# 2. pull the voting data into a local SQLite cache (votes.db)
#    sync is resumable — safe to interrupt and re-run
python fetch_votes.py --sync

# to wipe and start over from scratch
python fetch_votes.py --sync --reset

# 3. run the analysis
python analyse_votes.py
```

This produces:

- `mp_map.png` + `clusters.csv` — the voting similarity map, coloured by party
- `rebels.csv` — MPs ranked by how often they vote against their own party
- `surprises.csv` — votes ranked by how close the yes/no split was

If the API changes its column names, `analyse_votes.py` will tell you which
`--col-*` flag to pass (see [CLAUDE.md](CLAUDE.md) for details).
