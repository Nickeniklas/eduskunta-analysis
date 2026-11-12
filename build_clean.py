"""Build ballots_clean, a normalised view of raw vote/ballot tables in votes.db.

After the build, the sanity checks are enforced: the script exits non-zero if
any raw ballot string is unrecognised, ballots_clean has duplicate
(person_id, vote_id) pairs, or any row falls outside every term. The whole
rebuild is one transaction, rolled back on failure so the previous
ballots_clean is kept.
"""

import argparse
import sqlite3

# Raw EdustajaAanestys strings (trimmed) that BUILD_SQL knows how to encode.
KNOWN_BALLOTS = ("Jaa", "Ei", "Tyhjää", "Poissa")

# The raw rows that feed ballots_clean: Finnish-language, non-annulled votes.
# Shared by BUILD_SQL and the unknown-ballot check so they cannot drift apart.
# DISTINCT guards against exact-duplicate vote rows in the raw table, which
# would otherwise fan out every ballot of that vote.
SOURCE_SQL = """
FROM SaliDBAanestysEdustaja e
JOIN (
  SELECT DISTINCT AanestysId, IstuntoPvm, KieliId, AanestysMitatoity
  FROM SaliDBAanestys
) a ON a.AanestysId = e.AanestysId
LEFT JOIN party_map pm ON pm.raw_code = LOWER(TRIM(e.EdustajaRyhmaLyhenne))
WHERE a.KieliId = '1' AND a.AanestysMitatoity = '0'
"""

BUILD_SQL = f"""
CREATE TABLE ballots_clean AS
SELECT
  e.EdustajaHenkiloNumero AS person_id,
  e.EdustajaEtunimi || ' ' || e.EdustajaSukunimi AS name,
  -- party is the canonical code (party_map renames applied); party_raw keeps
  -- the code as the API recorded it at the time of the vote.
  COALESCE(pm.canonical_code, LOWER(TRIM(e.EdustajaRyhmaLyhenne))) AS party,
  LOWER(TRIM(e.EdustajaRyhmaLyhenne)) AS party_raw,
  a.AanestysId AS vote_id,
  -- IstuntoPvm is Finnish local midnight, but from 2018 on (and sporadically
  -- 2009-15) the API serialises it as UTC: 22:00 (EET) / 21:00 (EEST) on the
  -- previous day. +3 hours lands every variant on the right local date, and
  -- date() stores it as plain YYYY-MM-DD.
  date(a.IstuntoPvm, '+3 hours') AS vote_date,
  CASE TRIM(e.EdustajaAanestys)
    WHEN 'Jaa' THEN 1
    WHEN 'Ei' THEN -1
    WHEN 'Tyhjää' THEN 0
    WHEN 'Poissa' THEN NULL
  END AS ballot
{SOURCE_SQL};
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

# Party-code renames: (raw_code, canonical_code), both lowercased/trimmed.
# Renames only — the same parliamentary group under an older/interim code.
# Splits and one-MP groups keep their own codes.
PARTY_MAP = [
    ("skl", "kd"),
    ("uv", "sin"),
    ("si", "sin"),
    ("hh", "liik"),
]


def check_build(conn):
    """Print and enforce the post-build sanity checks on ``conn``.

    Raises SystemExit (non-zero exit, message on stderr) if any of these is
    above 0: raw ballot strings outside KNOWN_BALLOTS, duplicate
    (person_id, vote_id) pairs in ballots_clean, ballots_clean rows outside
    every term. Expects ballots_clean, terms and the raw tables to exist.
    """
    cur = conn.cursor()
    failures = []

    # Raw ballot strings feeding the build. BUILD_SQL's CASE has no ELSE, so an
    # unrecognised string would silently become NULL, i.e. look like Poissa.
    # COALESCE keeps a NULL raw value visible instead of dropping out of NOT IN.
    placeholders = ", ".join("?" * len(KNOWN_BALLOTS))
    raw_counts = dict(
        cur.execute(
            f"SELECT COALESCE(TRIM(e.EdustajaAanestys), '<NULL>'), COUNT(*) "
            f"{SOURCE_SQL} GROUP BY 1;"
        ).fetchall()
    )
    print("\nraw ballot strings (Finnish, non-annulled):")
    for s in KNOWN_BALLOTS:
        print(f"  {s!r}: {raw_counts.get(s, 0):,}")
    unknown = {s: n for s, n in raw_counts.items() if s not in KNOWN_BALLOTS}
    unknown_total = sum(unknown.values())
    print(f"unknown raw ballot rows: {unknown_total:,}")
    if unknown:
        listing = ", ".join(f"{s!r}: {n:,}" for s, n in sorted(unknown.items()))
        failures.append(f"{unknown_total:,} raw ballot rows with unknown value(s): {listing}")

    outside_count = cur.execute(
        """
        SELECT COUNT(*) FROM ballots_clean b
        WHERE NOT EXISTS (
          SELECT 1 FROM terms t
          WHERE date(b.vote_date) BETWEEN t.start_date AND t.end_date
        );
        """
    ).fetchone()[0]
    print(f"ballots_clean rows outside every term: {outside_count:,}")
    if outside_count:
        failures.append(f"{outside_count:,} ballots_clean rows outside every term")

    # ballots_clean must be one row per (person, vote). Anything non-zero means
    # duplicates crept in upstream (see the DISTINCT in SOURCE_SQL).
    dup_pairs = cur.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT 1 FROM ballots_clean
          GROUP BY person_id, vote_id HAVING COUNT(*) > 1
        );
        """
    ).fetchone()[0]
    print(f"duplicate (person_id, vote_id) pairs: {dup_pairs:,}")
    if dup_pairs:
        failures.append(f"{dup_pairs:,} duplicate (person_id, vote_id) pairs in ballots_clean")

    if failures:
        raise SystemExit(
            "build_clean.py: sanity checks FAILED:\n  - " + "\n  - ".join(failures)
        )
    print("sanity checks passed")


def build_tables(conn):
    """(Re)build party_map, ballots_clean and terms from the raw tables.

    Does not commit: call it inside the transaction opened by rebuild().
    """
    cur = conn.cursor()

    # party_map must exist before BUILD_SQL, which LEFT JOINs to it.
    cur.execute("DROP TABLE IF EXISTS party_map;")
    cur.execute("CREATE TABLE party_map (raw_code TEXT PRIMARY KEY, canonical_code TEXT NOT NULL);")
    cur.executemany("INSERT INTO party_map VALUES (?, ?);", PARTY_MAP)

    cur.execute("DROP TABLE IF EXISTS ballots_clean;")
    cur.execute(BUILD_SQL)
    for stmt in INDEX_SQL:
        cur.execute(stmt)

    cur.execute("DROP TABLE IF EXISTS terms;")
    cur.execute("CREATE TABLE terms (term TEXT, start_date TEXT, end_date TEXT);")
    cur.executemany("INSERT INTO terms VALUES (?, ?, ?);", TERMS)


def print_summary(conn):
    cur = conn.cursor()

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

    print("\nparties (after party_map):")
    for party, first, last, mps in cur.execute(
        """
        SELECT party, MIN(vote_date), MAX(vote_date), COUNT(DISTINCT person_id)
        FROM ballots_clean GROUP BY party ORDER BY MIN(vote_date), party;
        """
    ):
        print(f"  {party:<6} {first} .. {last}  {mps:>3} MPs")


def rebuild(conn):
    """Atomically rebuild party_map, ballots_clean and terms, then run the checks.

    Everything (drops, build, summary, check_build) runs in one explicit
    transaction. It is committed only if check_build passes; otherwise it is
    rolled back, so the previous party_map / ballots_clean / terms are kept,
    and SystemExit (exit 1) is raised. SQLite DDL is transactional, so the
    DROP TABLEs roll back too.
    """
    if conn.in_transaction:
        raise RuntimeError("rebuild() needs a connection with no open transaction")
    conn.isolation_level = None  # autocommit: we issue BEGIN/COMMIT ourselves
    conn.execute("BEGIN")
    try:
        build_tables(conn)
        print_summary(conn)
        check_build(conn)
    except SystemExit as exc:
        conn.execute("ROLLBACK")
        raise SystemExit(
            f"{exc.code}\nRolled back: the previous ballots_clean (and party_map, "
            "terms) was kept; nothing was changed."
        ) from None
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="votes.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        rebuild(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
