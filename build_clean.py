"""Build ballots_clean, a normalised view of raw vote/ballot tables in votes.db."""

import argparse
import sqlite3

BUILD_SQL = """
CREATE TABLE ballots_clean AS
SELECT
  e.EdustajaHenkiloNumero AS person_id,
  e.EdustajaEtunimi || ' ' || e.EdustajaSukunimi AS name,
  LOWER(e.EdustajaRyhmaLyhenne) AS party,
  a.AanestysId AS vote_id,
  a.IstuntoPvm AS vote_date,
  CASE TRIM(e.EdustajaAanestys)
    WHEN 'Jaa' THEN 1
    WHEN 'Ei' THEN -1
    WHEN 'Tyhjää' THEN 0
    WHEN 'Poissa' THEN NULL
  END AS ballot
FROM SaliDBAanestysEdustaja e
JOIN SaliDBAanestys a ON a.AanestysId = e.AanestysId
WHERE a.KieliId = '1' AND a.AanestysMitatoity = '0';
"""

INDEX_SQL = [
    "CREATE INDEX ix_bc_person ON ballots_clean(person_id);",
    "CREATE INDEX ix_bc_vote ON ballots_clean(vote_id);",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="votes.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS ballots_clean;")
    cur.execute(BUILD_SQL)
    for stmt in INDEX_SQL:
        cur.execute(stmt)
    conn.commit()

    row_count = cur.execute("SELECT COUNT(*) FROM ballots_clean;").fetchone()[0]
    print(f"ballots_clean row count: {row_count:,}")

    print("ballot value distribution:")
    for ballot, count in cur.execute(
        "SELECT ballot, COUNT(*) FROM ballots_clean GROUP BY ballot ORDER BY ballot;"
    ):
        print(f"  {ballot!r}: {count:,}")

    conn.close()


if __name__ == "__main__":
    main()
