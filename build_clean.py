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

# Parliamentary terms. Add a ninth row once the 2027 election result is known.
TERMS = [
    ("1995-99", "1995-04-15", "1999-04-14"),
    ("1999-03", "1999-04-15", "2003-04-14"),
    ("2003-07", "2003-04-15", "2007-04-14"),
    ("2007-11", "2007-04-15", "2011-04-14"),
    ("2011-15", "2011-04-15", "2015-04-14"),
    ("2015-19", "2015-04-15", "2019-04-14"),
    ("2019-23", "2019-04-15", "2023-04-14"),
    ("2023-27", "2023-04-15", "2027-04-14"),
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

    cur.execute("DROP TABLE IF EXISTS terms;")
    cur.execute("CREATE TABLE terms (term TEXT, start_date TEXT, end_date TEXT);")
    cur.executemany("INSERT INTO terms VALUES (?, ?, ?);", TERMS)

    conn.commit()

    row_count = cur.execute("SELECT COUNT(*) FROM ballots_clean;").fetchone()[0]
    print(f"ballots_clean row count: {row_count:,}")

    print("ballot value distribution:")
    for ballot, count in cur.execute(
        "SELECT ballot, COUNT(*) FROM ballots_clean GROUP BY ballot ORDER BY ballot;"
    ):
        print(f"  {ballot!r}: {count:,}")

    print("\nper-term vote/person counts:")
    for term, votes, persons in cur.execute(
        """
        SELECT t.term, COUNT(DISTINCT b.vote_id), COUNT(DISTINCT b.person_id)
        FROM terms t
        JOIN ballots_clean b ON date(b.vote_date) BETWEEN t.start_date AND t.end_date
        GROUP BY t.term
        ORDER BY t.start_date;
        """
    ):
        print(f"  {term}: {votes:,} votes, {persons:,} persons")

    outside_count = cur.execute(
        """
        SELECT COUNT(*) FROM ballots_clean b
        WHERE NOT EXISTS (
          SELECT 1 FROM terms t
          WHERE date(b.vote_date) BETWEEN t.start_date AND t.end_date
        );
        """
    ).fetchone()[0]
    print(f"\nballots_clean rows outside every term: {outside_count:,}")

    conn.close()


if __name__ == "__main__":
    main()
