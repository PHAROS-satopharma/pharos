"""PHAROS — our label against an originator's label change (Phase 11, migration 0043).

``gap`` is the check itself (pure, no I/O): for each sentence the originator added to a watched section, whether
the same section of our label says it — covered, partly or missing — in one language, never a translation.
``recompute`` writes what it found to ``label_gap``: when a change is recorded, and on every run for the changes
of the last year that have no row for a current version of our label.
"""
