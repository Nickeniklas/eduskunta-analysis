# Audit — eduskunta-analysis

Date: 2026-11-11, at commit `ac7e1d0` (clean working tree).
Scope: every tracked file (6 Python scripts, docs, `.gitignore`, `requirements.txt`) and all 23 commits of history.

How it was checked: code was read in full; suspected bugs were then tested with read-only queries against the local `votes.db` (opened `mode=ro`), an in-memory recompute of one term, and 17 GET requests to the public Eduskunta API. Nothing was written except this file. Each finding says whether it is **verified** or a **guess**.

## 1. Top 5 findings (ranked by impact vs effort)

### 1. Party-switchers get one party label per term, which distorts the dissenter report and party cohesion — verified

- **Where:** `term_matrix.py:93-98` (`build_lookup` takes the modal party over the whole term); consumed by `term_matrix.py:129-143` (`print_stats`) and `pairs_report.py:71-90`.
- **Why it matters:** an MP who changes group mid-term is labelled with their most frequent party, but their agreement scores cover the whole term. Their votes under the other party are then counted as dissent inside the labelled party.
- **Evidence (2015-19, the worst term):** 22 of 211 MPs cast at least 100 ballots under two or more parties (the PS/SIN split).
  - 19 of the 20 lowest within-party pairs in the dissenter ranking involve a switcher (e.g. Maria Tolppanen, labelled `sd`, 3,003 ballots as `sd` and 576 as `ps`).
  - PS within-party mean agreement is 0.936 as computed today, 0.971 excluding switchers, and 0.990 when computed only on votes cast under the `ps` label.
- **Other terms:** 1 to 3 such MPs each (1, 1, 1, 2, 2, 22, 2, 3 in term order), so the effect is small there but not zero.
- **Why now:** the planned `longitudinal.py` computes within-party cohesion per party per term from these same CSVs, so it would inherit the error.
- **Fix:** make the unit a (person, party) spell: pivot on `(person_id, party)`, keep spells with at least `--min-ballots` cast ballots, and write one lookup row per spell. A cheaper stopgap is a `switched` flag in the lookup that `pairs_report.py` and the stats exclude.

### 2. `build_clean.py` sanity checks only print, and unknown ballot strings silently become "absent" — verified by reading; data is clean today

- **Where:** `build_clean.py:21-26` (the `CASE` has no `ELSE`), `build_clean.py:111-132` (outside-term and duplicate-pair counts are printed, never enforced).
- **Why it matters:** the docs say the duplicate count "must be 0", but a non-zero count still exits 0 and `term_matrix.py` runs on the bad table. Any new or mis-encoded value in `EdustajaAanestys` maps to `NULL`, which is indistinguishable from `Poissa`. This is the only gate between the raw cache and all analysis.
- **Current state:** all four raw strings map (`Jaa` 2,691,553, `Ei` 966,912, `Tyhjää` 28,799, `Poissa` 643,916), 0 duplicate pairs, 0 rows outside terms.
- **Fix:** after the build, count rows whose trimmed raw ballot is not one of the four known strings, and `raise SystemExit` (non-zero) if that count, the duplicate-pair count, or the outside-term count is above 0. About ten lines.

### 3. Positional `INSERT` breaks, or corrupts, when the API schema changes — verified by reading; latent

- **Where:** `fetch_votes.py:149-151` (`CREATE TABLE IF NOT EXISTS`, so an existing table is never altered) and `fetch_votes.py:237-243` (`INSERT ... VALUES (?,?,...)` with no column list).
- **Why it matters:** the docs claim the cache schema "always matches whatever the API currently returns". That holds only for a fresh table.
  - If the API adds a column, every later `--sync --update` fails with a column-count error, and the documented remedy is a multi-hour `--reset`.
  - If the API reorders columns with the same count, values land in the wrong columns with no error (guess: unlikely, but nothing would catch it).
- **Current state:** API column order equals the local column order for both tables.
- **Fix:** name the columns in the `INSERT`, and `ALTER TABLE ... ADD COLUMN` for any API column missing locally.

### 4. `analyse_votes.py` is the only source of `rebels.csv` / `surprises.csv` and does not work as shipped — verified by reading; not run

- **Where:** `analyse_votes.py:32-38` (column guesses), `:74-75` (`SELECT *` on both raw tables), `:174-175` (party line by mode).
- **Why it matters:** the rebel report is one of the project's two stated goals.
  - Default run exits at `pick()` because no `party` or `choice` candidate exists (already noted in `CLAUDE.md`), after loading all 8.67M raw ballot rows.
  - With the documented `--col-*` overrides it would still read raw tables: untrimmed, un-mapped party codes, annulled votes included, both language rows, no MP names (no name candidate matches, so `mp_name` falls back to the id). This also breaks the layering rule.
  - `s.mode().iat[0]` breaks ties alphabetically, so in an even split `no` becomes the party line and every `yes` voter is counted as a rebel.
- **Fix:** port `surprises()` (about 40 lines) to read `ballots_clean` for one term, treat ties as "no party line", then delete `analyse_votes.py`.

### 5. `--update` trusts row-count page arithmetic with no alignment check — mechanism verified; that it has ever gone wrong is a guess

- **Where:** `fetch_votes.py:197-203` (start page from the local row count), `:134-135` and `:229` (an empty page means "finished" and the table is marked `done`), `:84-91` (HTTP errors other than 429 are not retried).
- **Why it matters:** the start page is derived from how many rows are cached, not from which rows. If upstream ever deletes a row, every later row shifts down a position and the update starts too late, silently skipping new rows. Separately, only the last two pages are re-read, so a vote annulled or corrected later is never refreshed, and ballots use `INSERT OR IGNORE`, so a corrected ballot is never picked up at all.
- **Current state:** aligned. The API row at the resume offset equals the local row at that offset for both tables, and 1,200 sampled API rows (12 pages across both tables) match the cache exactly. Both tables are cached in strictly increasing primary-key order.
- **Fix:** before fetching, compare the first key on the resume page with the local key at the same offset and abort with a "run `--reset`" message on mismatch. Retry 5xx responses the same way as 429.

### Security

No real exposure found.

- **Secrets in history:** none. All 23 commits were pattern-scanned; the only paths ever committed are the tracked files plus one `votes.db-journal` (9.7 KB, added in `9ccae62`, removed in `642d484`). It holds fragments of public voting data only.
- **Auth:** none exists and none is needed (public API, local scripts).
- **Unvalidated input:** `fetch_votes.py:150` and `:242` build SQL from API-supplied column names and `:108` puts `--peek TABLE` into a URL unescaped. The source is a government API over HTTPS and the user's own CLI input, so the risk is low; a column name containing `"` would break the DDL.
- **Commit metadata:** the author email is in every commit. If the GitHub repo is public and that is unwanted, switch to the GitHub noreply address.

### Lower priority (real, small)

- `term_matrix.py:171`: pairs with too few shared votes get distance 1.0 in the projection. That is 20 to 193 pairs per term (12 to 42 MPs), mostly an MP and their replacement. Little effect under UMAP, more under the PCA fallback.
- `term_matrix.py:102-109`: `except Exception` falls back to PCA on any UMAP error, not only a missing install. The only signal is the word in the plot title.
- `pairs_report.py:100`: `str.contains` treats `--mp` as a regex, so `--mp "("` crashes. Pass `regex=False`.
- `requirements.txt`: nothing is pinned. Installed today: pandas 3.0.3, numpy 2.4.6, scikit-learn 1.9.0, umap-learn 0.5.12. The `stack()` gotcha in `CLAUDE.md` shows the code is version-sensitive.

### Checked and found fine

- **Term boundaries:** no vote lands in the wrong term. First votes of each new parliament fall on or after 15 April (the closest is 2003-04-15, exactly on the start date); the 2011-04-13 votes belong to the outgoing parliament.
- **Completeness:** all 21,765 Finnish non-annulled votes are in `ballots_clean`, and the Jaa / Ei / Tyhjää counts equal the official `AanestysTulos*` tallies for every one. 50 votes (June 2009) have 198 ballots where the official total is 199; one absent MP is missing upstream.
- **Agreement maths:** the vectorised `pairwise_agreement` matches a naive loop on 300 random pairs.
- **Outputs on disk:** `agreement_2015-19.csv` equals a fresh in-memory recompute from the current DB (max difference 1e-16).
- **Cleaning:** no padded or NULL names, person ids, parties or dates in `ballots_clean`.

## 2. Tests that would catch real breakage

There is no test suite. These five, with pytest and tiny in-memory SQLite fixtures, cover the places where a silent error is possible.

1. **`build_clean` golden fixture.** A hand-written raw DB with padded strings, both language rows, one annulled vote, `IstuntoPvm` at `00:00`, `22:00` and `21:00` the previous day, an `skl` ballot, and a duplicated vote row. Assert the exact `ballots_clean` rows. Catches join fan-out, the date shift, trimming, `party_map` and the language filter in one test.
2. **`pairwise_agreement` on a hand-computed 4-MP matrix.** Absent excluded from shared votes, abstain-abstain counted as agreement, pairs below `--min-shared` are `NaN`, matrix symmetric, diagonal `NaN`.
3. **Sync resume and update against a fake `_get`.** Interrupt a sync mid-table, resume, and assert the cached key set equals the fake API's with no duplicates; then append rows and edit one vote row, run `--update`, and assert both land. Add a case where the fake API gains a column (fails today, see finding 3).
4. **Reconciliation check on the real DB.** Per vote, the Jaa / Ei / Tyhjää counts in `ballots_clean` equal `AanestysTulos*`; every Finnish non-annulled vote is present; 0 duplicate pairs; 0 rows outside terms. This is the single best guard against a partial or drifted sync. It passes today (do not assert on the absent count, because of the 50 known upstream mismatches).
5. **`term_matrix` to `pairs_report` round trip.** Write a small agreement matrix and lookup, load them through `pairs_report.load`, and assert `long_pairs` returns exactly the non-`NaN` upper-triangle pairs, no self-pairs, and that cross-party plus within-party partition them. Guards the `stack()` / `dropna()` behaviour across pandas upgrades and the int/str id round trip.

## 3. Not verified

- **`analyse_votes.py` was not run.** It loads 8.67M rows and writes four files to the repo root, which a read-only audit rules out. Finding 4 is from reading the code.
- **No sync path was executed** (`--sync`, `--update`, `--reset` all write to `votes.db`). Resume, checkpointing, 429 backoff and the `INSERT OR REPLACE` behaviour are assessed from the code only.
- **Whether the API edits or deletes old rows.** The 1,200-row sample matched, which is weak evidence that it does not. 40 vote rows since 2019 have an `Imported` timestamp more than 30 days after the session; the cause is unknown.
- **Root cause of the 8 duplicate vote rows fixed on 2026-11-06.** The API serves 43,595 vote rows today, equal to the deduplicated cache, so the duplicates were not in the API at the time of this audit. Whether they once were, or came from a double fetch, is unknown.
- **A primary-key range endpoint.** `/tables/{table}/batch?pkStartValue=...` returned HTTP 400 on one attempt; not explored further, so finding 5 recommends an alignment check instead.
- **`PARTY_MAP` correctness.** The four mappings and the "renames only" rule were not checked against any external source, and the 28 unmapped codes were not reviewed for missed renames.
- **Outputs for the other seven terms.** Only 2015-19 was recomputed and compared with disk.
- **Whether the GitHub repo is public**, which decides whether the journal blob and commit emails are visible to anyone.
- **The proposed tests and fixes.** None were written or run.
