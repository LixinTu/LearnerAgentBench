"""LearnerAgentBench — a benchmark for agents that act on behalf of a student.

The package is organised by dependency order:

    schema   -> typed records shared by everything else (Pydantic)
    env      -> the persistent simulated world (SQLite), clock, events, snapshots
    learner  -> learner models (transparent synthetic, knowledge-tracing) and plan oracles
    tools    -> the agent-facing tool layer: registry, permissions, idempotency, audit log
    runtime  -> the agent loop, adapters, trajectories, interruption/resume
    tasks    -> task specs, families, counterfactual variants
    verify   -> deterministic verifiers, judge interface, failure attribution
    harness  -> benchmark runner and CLI
    baselines, analysis
"""

__version__ = "0.1.0.dev0"
