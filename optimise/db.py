"""DEPRECATED – superseded (see docs/MODEL_AUDIT.md, 'Applied fixes').

Replaced by: preprocess/presence.py, preprocess/population.py, preprocess/antivenom.py,
optimise/demand.py, optimise/location.py, optimise/inventory.py, optimise/solver.py.
Kept only so old imports fail loudly instead of silently using the flawed logic.
"""
raise ImportError("db.py is deprecated; run scripts/run_pipeline.sh and use optimise.solver")
