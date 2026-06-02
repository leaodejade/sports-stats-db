"""Leakage-free backtesting over stored predictions, odds and settlements."""

from .engine import BacktestConfig, BacktestResult, run_backtest, summarize_by

__all__ = ["BacktestConfig", "BacktestResult", "run_backtest", "summarize_by"]
