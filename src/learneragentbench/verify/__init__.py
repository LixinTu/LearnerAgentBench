"""Deterministic verifiers and verdict assembly."""
from . import builtin as _builtin  # noqa: F401 — registers the built-in verifiers
from . import tutoring as _tutoring  # noqa: F401 — registers the tutoring verifier
from .base import VERIFIERS, VerifyContext, assemble_verdict, result, run_checks, verifier

__all__ = ["VERIFIERS", "VerifyContext", "assemble_verdict", "result", "run_checks", "verifier"]
