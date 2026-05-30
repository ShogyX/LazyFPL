"""FPL Intelligence Engine.

Self-hosted service that ingests FPL/odds/stats data, learns predictive
weights, predicts expected points, and optimises squads & transfers.

Package layout mirrors the architecture in FPL_MASTER_PLAN_v2.md:
ingest / store / features / model / optimise / api / notify / orchestrator.
"""

__version__ = "0.1.0"
