"""Analytical (read-only) queries returning pandas DataFrames."""

from . import betting, calibration, football, odds_math

__all__ = ["football", "betting", "calibration", "odds_math"]
