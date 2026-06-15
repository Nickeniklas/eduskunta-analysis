#!/usr/bin/env python3
"""
analyse_votes.py

Reads the local votes.db built by fetch_votes.py and produces:

  1. A vote similarity map        -> mp_map.png  + clusters.csv
     MP-by-MP agreement matrix, projected to 2D (PCA, or UMAP if installed),
     coloured by party. Shows the real voting blocs vs the official party split.

  2. A surprise / rebel report    -> surprises.csv
     Flags (a) MPs who broke from their party majority on a given vote, and
           (b) votes that split unusually close or cut across the gov/opp line.

This is deliberately schema-tolerant: Eduskunta column names are guessed from
common candidates and you can override them with the CLI flags after you run
`fetch_votes.py --peek SaliDBAanestysEdustaja` to see the real names.

Deps: pandas, numpy, scikit-learn, matplotlib  (umap-learn optional)
  pip install pandas numpy scikit-learn matplotlib
  pip install umap-learn        # optional, nicer projection
"""

import argparse
import sqlite3
import sys
import numpy as np
import pandas as pd

# ---- column name guessing -------------------------------------------------
# Run fetch_votes.py --peek to confirm, then pass --col-* flags if these miss.
BALLOT_DEFAULTS = {
    "vote_id":   ["AanestysId", "VoteId"],
    "mp":        ["EdustajaHenkilonumero", "Henkilonumero", "EdustajaId", "Edustaja"],
    "mp_name":   ["EdustajaNimi", "Etunimi", "Nimi", "EdustajaTeksti"],
    "party":     ["RyhmaLyhenne", "EduskuntaRyhma", "Ryhma", "RyhmaNimi"],
    "choice":    ["EdustajanAanestys", "Aanestys", "Aani", "AanestysTeksti"],
}
VOTE_DEFAULTS = {
    "vote_id":   ["AanestysId", "Id", "VoteId"],
    "date":      ["AanestysAlkuPvm", "Pvm", "AanestysPvm", "Aika"],
    "title":     ["AanestysOtsikko", "KohtaOtsikko", "Otsikko", "Asiakohta"],
}

# Finnish ballot choices normalised to: yes / no / empty / absent
CHOICE_MAP = {
    "jaa": "yes", "yes": "yes",
    "ei": "no", "no": "no",
    "tyhjää": "empty", "tyhjaa": "empty", "tyhja": "empty", "empty": "empty",
    "poissa": "absent", "absent": "absent",
}


def pick(df, candidates, override):
    if override and override in df.columns:
        return override
    for c in candidates:
        if c in df.columns:
            return c
    raise SystemExit(
        f"none of {candidates} found in columns {list(df.columns)}; "
        "use the matching --col-* flag"
    )


def normalise_choice(v):
    if v is None:
        return "absent"
    return CHOICE_MAP.get(str(v).strip().lower(), "absent")


def load(db, cols):
    con = sqlite3.connect(db)
    ballots = pd.read_sql_query("SELECT * FROM SaliDBAanestysEdustaja", con)
    votes = pd.read_sql_query("SELECT * FROM SaliDBAanestys", con)
    con.close()

    b_vote = pick(ballots, BALLOT_DEFAULTS["vote_id"], cols.get("vote_id"))
    b_mp = pick(ballots, BALLOT_DEFAULTS["mp"], cols.get("mp"))
    b_party = pick(ballots, BALLOT_DEFAULTS["party"], cols.get("party"))
    b_choice = pick(ballots, BALLOT_DEFAULTS["choice"], cols.get("choice"))
    try:
        b_name = pick(ballots, BALLOT_DEFAULTS["mp_name"], cols.get("mp_name"))
    except SystemExit:
        b_name = None

    df = pd.DataFrame({
        "vote_id": ballots[b_vote].astype(str),
        "mp": ballots[b_mp].astype(str),
        "party": ballots[b_party].astype(str),
        "choice": ballots[b_choice].map(normalise_choice),
    })
    df["mp_name"] = ballots[b_name].astype(str) if b_name else df["mp"]

    v_vote = pick(votes, VOTE_DEFAULTS["vote_id"], cols.get("v_vote_id"))
    votes["vote_id"] = votes[v_vote].astype(str)
    return df, votes


# ---- 1. similarity map ----------------------------------------------------
def build_map(df, since=None, min_votes=20):
    if since:
        # vote_id is roughly monotonic with time; for real date filtering join votes table.
        pass
    # encode yes=+1, no=-1, everything else 0 (so abstain/absent don't fake agreement)
    enc = df.copy()
    enc["v"] = enc["choice"].map({"yes": 1, "no": -1}).fillna(0)
    mat = enc.pivot_table(index="mp", columns="vote_id", values="v",
                          aggfunc="first", fill_value=0)
    # drop MPs with too few actual votes (avoids noise from people who barely voted)
    active = (mat != 0).sum(axis=1) >= min_votes
    mat = mat[active]
    parties = df.groupby("mp")["party"].agg(lambda s: s.mode().iat[0])
    names = df.groupby("mp")["mp_name"].agg(lambda s: s.mode().iat[0])

    X = mat.values.astype(float)
    # agreement-based distance via cosine similarity
    from sklearn.metrics.pairwise import cosine_similarity
    sim = cosine_similarity(X)

    # project
    coords, method = project(X)

    # cluster on the similarity (KMeans on coords is fine for a visual)
    from sklearn.cluster import KMeans
    k = min(6, max(2, len(mat) // 25))
    labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(coords)

    out = pd.DataFrame({
        "mp": mat.index,
        "name": names.reindex(mat.index).values,
        "party": parties.reindex(mat.index).values,
        "x": coords[:, 0],
        "y": coords[:, 1],
        "cluster": labels,
    })
    return out, sim, mat.index.tolist(), method


def project(X):
    try:
        import umap
        reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine",
                            random_state=0)
        return reducer.fit_transform(X), "UMAP"
    except Exception:
        from sklearn.decomposition import PCA
        return PCA(n_components=2, random_state=0).fit_transform(X), "PCA"


def plot_map(out, method, path="mp_map.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 8))
    for party, g in out.groupby("party"):
        ax.scatter(g["x"], g["y"], label=party, s=40, alpha=0.8)
    ax.set_title(f"Eduskunta vote similarity map ({method})\ncolour = party, "
                 "position = voting behaviour")
    ax.legend(loc="best", fontsize=8, ncol=2)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    print(f"wrote {path}")


# ---- 2. surprise / rebel detector -----------------------------------------
def surprises(df, rebel_only=False):
    """For each (vote, party) find the party majority choice, flag MPs who
    voted against it. Also score each vote by how close it was."""
    cast = df[df["choice"].isin(["yes", "no"])].copy()

    # party line per vote = majority choice within that party on that vote
    party_line = (cast.groupby(["vote_id", "party"])["choice"]
                  .agg(lambda s: s.mode().iat[0])
                  .rename("party_line").reset_index())
    merged = cast.merge(party_line, on=["vote_id", "party"])
    merged["rebel"] = merged["choice"] != merged["party_line"]

    rebels = (merged[merged["rebel"]]
              .groupby(["mp", "mp_name", "party"])
              .size().rename("rebel_votes").reset_index()
              .sort_values("rebel_votes", ascending=False))

    # closeness per vote: |yes - no| / total  (small = nail-biter)
    tally = (cast.groupby(["vote_id", "choice"]).size()
             .unstack(fill_value=0))
    for c in ("yes", "no"):
        if c not in tally:
            tally[c] = 0
    tally["total"] = tally["yes"] + tally["no"]
    tally["margin"] = (tally["yes"] - tally["no"]).abs()
    tally["closeness"] = 1 - (tally["margin"] / tally["total"].clip(lower=1))
    close_votes = (tally.sort_values("closeness", ascending=False)
                   .reset_index()[["vote_id", "yes", "no", "closeness"]])

    return rebels, close_votes, merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="votes.db")
    ap.add_argument("--min-votes", type=int, default=20,
                    help="ignore MPs with fewer than this many actual votes")
    ap.add_argument("--since", help="year filter (needs date join, placeholder)")
    # column overrides if the guesses miss
    for k in ("vote_id", "mp", "mp_name", "party", "choice", "v_vote_id"):
        ap.add_argument(f"--col-{k.replace('_','-')}", dest=f"col_{k}")
    args = ap.parse_args()

    cols = {k: getattr(args, f"col_{k}", None)
            for k in ("vote_id", "mp", "mp_name", "party", "choice", "v_vote_id")}

    df, votes = load(args.db, cols)
    print(f"loaded {len(df):,} ballots across {df['vote_id'].nunique():,} votes, "
          f"{df['mp'].nunique()} MPs")

    out, sim, order, method = build_map(df, since=args.since,
                                        min_votes=args.min_votes)
    out.to_csv("clusters.csv", index=False)
    print("wrote clusters.csv")
    plot_map(out, method)

    rebels, close_votes, _ = surprises(df)
    rebels.to_csv("rebels.csv", index=False)
    close_votes.head(200).to_csv("surprises.csv", index=False)
    print("wrote rebels.csv (most independent MPs) and surprises.csv (closest votes)")
    print("\ntop 10 most independent MPs:")
    print(rebels.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
