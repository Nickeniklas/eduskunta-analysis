#!/usr/bin/env python3
"""
term_matrix.py

Reads ballots_clean (built by build_clean.py) for a single parliamentary
term and produces an MP x MP pairwise agreement matrix, plus a similarity
map. Replaces analyse_votes.py as the main analysis entry point: it reads
the cleaned table instead of the raw API tables.

Outputs (in the current directory):
  agreement_{term}.csv   MP x MP agreement matrix (person_id index/columns)
  lookup_{term}.csv      person_id -> name, party, cluster (KMeans label)
  mp_map_{term}.png      2D projection (UMAP if installed, else PCA),
                         coloured by party

Deps: pandas, numpy, scikit-learn, matplotlib  (umap-learn optional)

Usage:
  python term_matrix.py --term 2019-23
  python term_matrix.py --term 2019-23 --db custom.db
  python term_matrix.py --term 2019-23 --min-ballots 100 --min-shared 50

Available terms come from the `terms` table (built by build_clean.py):
1995-99 through 2023-27. Requires ballots_clean, so run build_clean.py
first. Feed the outputs to pairs_report.py for readable pair reports.
"""

import argparse
import sqlite3

import numpy as np
import pandas as pd


def load_term(db, term):
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT start_date, end_date FROM terms WHERE term = ?;", (term,)
    ).fetchone()
    if row is None:
        available = [r[0] for r in con.execute("SELECT term FROM terms ORDER BY start_date;")]
        con.close()
        raise SystemExit(f"unknown term {term!r}; available terms: {available}")
    start_date, end_date = row

    df = pd.read_sql_query(
        """
        SELECT person_id, name, party, vote_id, ballot
        FROM ballots_clean
        WHERE date(vote_date) BETWEEN ? AND ?;
        """,
        con, params=(start_date, end_date),
    )
    con.close()
    return df, start_date, end_date


def filter_mps(df, min_ballots):
    counts = df.dropna(subset=["ballot"]).groupby("person_id").size()
    keep = counts[counts >= min_ballots].index
    dropped = df["person_id"].nunique() - len(keep)
    print(f"MPs kept: {len(keep)}, dropped (< {min_ballots} ballots): {dropped}")
    return df[df["person_id"].isin(keep)]


def build_pivot(df):
    mat = df.pivot_table(index="person_id", columns="vote_id", values="ballot",
                          aggfunc="first")
    return mat


def pairwise_agreement(mat, min_shared):
    X = mat.values.astype(float)
    voted = ~np.isnan(X)

    shared_votes = voted.astype(np.int32) @ voted.astype(np.int32).T

    equal_votes = np.zeros_like(shared_votes, dtype=np.int32)
    for v in (1.0, -1.0, 0.0):
        indicator = (X == v).astype(np.int32)  # NaN == v is False, no masking needed
        equal_votes += indicator @ indicator.T

    with np.errstate(invalid="ignore", divide="ignore"):
        agreement = equal_votes / shared_votes
    agreement[shared_votes < min_shared] = np.nan
    np.fill_diagonal(agreement, np.nan)

    return pd.DataFrame(agreement, index=mat.index, columns=mat.index)


def build_lookup(df, person_ids):
    sub = df[df["person_id"].isin(person_ids)]
    names = sub.groupby("person_id")["name"].agg(lambda s: s.mode().iat[0])
    parties = sub.groupby("person_id")["party"].agg(lambda s: s.mode().iat[0])
    return pd.DataFrame({"person_id": names.index, "name": names.values,
                          "party": parties.reindex(names.index).values})


def project(X):
    try:
        import umap
        reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="precomputed",
                            random_state=0)
        return reducer.fit_transform(X), "UMAP"
    except Exception:
        from sklearn.decomposition import PCA
        return PCA(n_components=2, random_state=0).fit_transform(X), "PCA"


def plot_map(coords, parties, method, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame({"x": coords[:, 0], "y": coords[:, 1], "party": parties})
    fig, ax = plt.subplots(figsize=(11, 8))
    for party, g in df.groupby("party"):
        ax.scatter(g["x"], g["y"], label=party, s=45, alpha=0.85)
    ax.set_title(f"MP voting-agreement map ({method})\ncolour = party")
    ax.legend(loc="best", fontsize=8, ncol=2)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    print(f"wrote {path}")


def print_stats(agreement, lookup):
    party_of = lookup.set_index("person_id")["party"]
    parties_arr = party_of.reindex(agreement.index).values
    vals = agreement.values

    print("\nmean agreement by party (within-party vs cross-party):")
    for party in sorted(set(parties_arr)):
        mask_p = parties_arr == party
        within = vals[np.ix_(mask_p, mask_p)]
        within = within[~np.isnan(within)]
        cross = vals[np.ix_(mask_p, ~mask_p)]
        cross = cross[~np.isnan(cross)]
        within_mean = within.mean() if within.size else float("nan")
        cross_mean = cross.mean() if cross.size else float("nan")
        print(f"  {party:>10s}: within={within_mean:.3f}  cross={cross_mean:.3f}  n={mask_p.sum()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--term", required=True, help="e.g. 2019-23 (see terms table)")
    ap.add_argument("--db", default="votes.db")
    ap.add_argument("--min-ballots", type=int, default=100,
                    help="minimum non-NULL ballots for an MP to be kept")
    ap.add_argument("--min-shared", type=int, default=50,
                    help="minimum shared votes for a pair to get an agreement score")
    args = ap.parse_args()

    df, start_date, end_date = load_term(args.db, args.term)
    print(f"term {args.term}: {start_date} to {end_date}, "
          f"{df['vote_id'].nunique():,} votes, {df['person_id'].nunique()} MPs (raw)")

    df = filter_mps(df, args.min_ballots)

    mat = build_pivot(df)
    print(f"pivoted matrix: {mat.shape[0]} MPs x {mat.shape[1]} votes")

    agreement = pairwise_agreement(mat, args.min_shared)
    agreement_path = f"agreement_{args.term}.csv"
    agreement.to_csv(agreement_path)
    print(f"wrote {agreement_path}")

    # distance for projection: 1 - agreement, missing pairs treated as fully dissimilar
    dist = (1 - agreement).fillna(1.0).values.copy()
    np.fill_diagonal(dist, 0.0)

    coords, method = project(dist)

    from sklearn.cluster import KMeans
    k = min(6, max(2, len(mat) // 25))
    cluster_labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(coords)

    # lookup is written AFTER clustering so the cluster label can be included:
    # person_id, name, party, cluster — makes "who is in cluster N" a CSV filter
    lookup = build_lookup(df, mat.index)
    lookup["cluster"] = pd.Series(cluster_labels, index=mat.index)\
        .reindex(lookup["person_id"]).values
    lookup_path = f"lookup_{args.term}.csv"
    lookup.to_csv(lookup_path, index=False)
    print(f"wrote {lookup_path}")

    party_of = lookup.set_index("person_id")["party"]
    parties = party_of.reindex(mat.index).values

    map_path = f"mp_map_{args.term}.png"
    plot_map(coords, parties, method, map_path)

    print_stats(agreement, lookup)

    print("\ncluster composition (party counts per cluster):")
    comp = lookup.groupby(["cluster", "party"]).size().rename("n").reset_index()
    for cluster, g in comp.groupby("cluster"):
        parts = ", ".join(f"{r.party}={r.n}" for r in g.itertuples())
        print(f"  cluster {cluster}: {parts}")


if __name__ == "__main__":
    main()
