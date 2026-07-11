#!/usr/bin/env python3
"""
pairs_report.py

Turns the agreement matrix from term_matrix.py into human-readable reports.
Reads agreement_{term}.csv + lookup_{term}.csv (must exist in the current
directory — run term_matrix.py for that term first).

Default run produces three reports:
  1. Highest CROSS-party pairs   -> cross_party_{term}.csv
     MPs who vote most alike despite different parties.
  2. Lowest WITHIN-party pairs   -> dissenters_{term}.csv
     Party colleagues who agree least — internal friction.
  3. (with --mp) One MP's closest and furthest voting allies, printed.

Extra:
  --cluster N   list the members of KMeans cluster N (needs the cluster
                column in lookup_{term}.csv, added by the updated
                term_matrix.py)

Usage:
  python pairs_report.py --term 2019-23
  python pairs_report.py --term 2019-23 --top 30
  python pairs_report.py --term 2019-23 --mp "Elina Valtonen"
  python pairs_report.py --term 2019-23 --mp 1329
  python pairs_report.py --term 2019-23 --cluster 3
"""

import argparse
import sys

import numpy as np
import pandas as pd


def load(term):
    try:
        agreement = pd.read_csv(f"agreement_{term}.csv", index_col=0)
        lookup = pd.read_csv(f"lookup_{term}.csv")
    except FileNotFoundError as e:
        raise SystemExit(
            f"{e.filename} not found — run `python term_matrix.py --term {term}` first"
        )
    # person_ids come back as ints from CSV; keep everything as str so the
    # matrix index, matrix columns, and lookup keys always compare equal
    agreement.index = agreement.index.astype(str)
    agreement.columns = agreement.columns.astype(str)
    lookup["person_id"] = lookup["person_id"].astype(str)
    return agreement, lookup


def long_pairs(agreement, lookup):
    """Melt the symmetric matrix into one row per unique MP pair."""
    mask = np.triu(np.ones(agreement.shape, dtype=bool), k=1)  # upper triangle, no diagonal
    # .dropna() is required: newer pandas stack() keeps NaN by default, which
    # would leak the masked lower triangle + diagonal back in as NaN rows
    pairs = agreement.where(mask).stack().dropna().rename("agreement").reset_index()
    pairs.columns = ["mp1", "mp2", "agreement"]

    info = lookup.set_index("person_id")
    for side in ("1", "2"):
        pairs[f"name{side}"] = pairs[f"mp{side}"].map(info["name"])
        pairs[f"party{side}"] = pairs[f"mp{side}"].map(info["party"])

    cols = ["name1", "party1", "name2", "party2", "agreement", "mp1", "mp2"]
    return pairs[cols]


def report_cross_party(pairs, term, top):
    cross = pairs[pairs["party1"] != pairs["party2"]]
    cross = cross.sort_values("agreement", ascending=False)
    path = f"cross_party_{term}.csv"
    cross.to_csv(path, index=False)
    print(f"wrote {path} ({len(cross):,} pairs)")
    print(f"\ntop {top} cross-party pairs (vote most alike despite different parties):")
    print(cross.head(top).drop(columns=["mp1", "mp2"]).to_string(index=False))
    return cross


def report_dissenters(pairs, term, top):
    within = pairs[pairs["party1"] == pairs["party2"]]
    within = within.sort_values("agreement", ascending=True)
    path = f"dissenters_{term}.csv"
    within.to_csv(path, index=False)
    print(f"\nwrote {path} ({len(within):,} pairs)")
    print(f"\nbottom {top} within-party pairs (party colleagues who agree least):")
    print(within.head(top).drop(columns=["mp1", "mp2"]).to_string(index=False))
    return within


def report_mp(agreement, lookup, mp, top):
    info = lookup.set_index("person_id")

    # accept either a person_id or a (case-insensitive, partial) name
    if mp in agreement.index:
        pid = mp
    else:
        hits = lookup[lookup["name"].str.contains(mp, case=False, na=False)]
        if len(hits) == 0:
            raise SystemExit(f"no MP matching {mp!r} in this term's lookup")
        if len(hits) > 1:
            print(f"multiple matches for {mp!r}:", file=sys.stderr)
            print(hits[["person_id", "name", "party"]].to_string(index=False),
                  file=sys.stderr)
            raise SystemExit("narrow the name or pass the person_id instead")
        pid = hits["person_id"].iat[0]

    row = agreement.loc[pid].dropna().sort_values(ascending=False)
    out = pd.DataFrame({
        "name": row.index.map(info["name"]),
        "party": row.index.map(info["party"]),
        "agreement": row.values,
    })
    who = f"{info.loc[pid, 'name']} ({info.loc[pid, 'party']})"
    print(f"\n{who} — closest voting allies:")
    print(out.head(top).to_string(index=False))
    print(f"\n{who} — furthest (lowest agreement):")
    print(out.tail(top).iloc[::-1].to_string(index=False))


def report_cluster(lookup, cluster):
    if "cluster" not in lookup.columns:
        raise SystemExit(
            "no cluster column in the lookup CSV — re-run the updated "
            "term_matrix.py so it writes cluster labels into the lookup"
        )
    members = lookup[lookup["cluster"] == cluster].sort_values(["party", "name"])
    if members.empty:
        avail = sorted(lookup["cluster"].dropna().unique().tolist())
        raise SystemExit(f"cluster {cluster} not found; available: {avail}")
    print(f"\ncluster {cluster} members ({len(members)}):")
    print(members[["name", "party"]].to_string(index=False))
    print("\nparty breakdown:")
    print(members["party"].value_counts().to_string())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--term", required=True, help="e.g. 2019-23")
    ap.add_argument("--top", type=int, default=20,
                    help="rows to print per report (default 20)")
    ap.add_argument("--mp", help="person_id or (partial) name for an ally report")
    ap.add_argument("--cluster", type=int,
                    help="list members of this KMeans cluster from the lookup")
    args = ap.parse_args()

    agreement, lookup = load(args.term)

    if args.cluster is not None:
        report_cluster(lookup, args.cluster)
        return
    if args.mp:
        report_mp(agreement, lookup, args.mp, args.top)
        return

    pairs = long_pairs(agreement, lookup)
    print(f"{len(pairs):,} scored MP pairs in term {args.term}")
    report_cross_party(pairs, args.term, args.top)
    report_dissenters(pairs, args.term, args.top)


if __name__ == "__main__":
    main()
