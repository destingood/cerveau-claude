"""Eval harness of CERVEAU (plan section 9, ADR-009): cases, fixture web, checks, judge, report.

promptfoo drives the runs through the shim ``evals/promptfoo/cerveau.py``; everything else lives
here so that pytest covers it. Offline (CI), scripted models replace the real ones and only the
deterministic checks count; live (D8), the real models answer on the same fixture pages and a
judge, called through the model router, scores the golden set.
"""
