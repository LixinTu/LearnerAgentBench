"""Result aggregation."""
from .compare import compare_runs, parse_filter
from .summary import bootstrap_ci, collect_runs, passive_floor, summarize_runs

__all__ = ["bootstrap_ci", "collect_runs", "compare_runs", "parse_filter", "passive_floor", "summarize_runs"]
