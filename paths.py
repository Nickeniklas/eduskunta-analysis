#!/usr/bin/env python3
"""
paths.py

Centralizes the output-location convention for the term-scoped analysis
scripts (term_matrix.py, pairs_report.py): every artifact for a term lives
under outputs/{term}/, keeping filenames unchanged so they stay
self-identifying if moved or shared. Not used by analyse_votes.py, which
is not term-scoped and still writes to the repo root.
"""

import os

OUTPUT_ROOT = "outputs"


def output_dir(term):
    """Return outputs/{term}/, creating it if needed."""
    d = os.path.join(OUTPUT_ROOT, term)
    os.makedirs(d, exist_ok=True)
    return d


def output_path(term, filename):
    """Full path for an output file under its term folder."""
    return os.path.join(output_dir(term), filename)
