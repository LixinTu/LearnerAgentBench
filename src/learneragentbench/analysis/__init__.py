"""Result aggregation."""
from .compare import compare_runs, parse_filter
from .summary import bootstrap_ci, summarize_runs

__all__ = ["bootstrap_ci", "compare_runs", "parse_filter", "summarize_runs"]
