"""Analytical (read-only) queries returning pandas DataFrames."""

from . import betting, calibration, football

__all__ = ["football", "betting", "calibration"]
