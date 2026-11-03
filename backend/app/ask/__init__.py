"""Ask-the-Network sub-package (Track F).

Components:
  F1 — query_generator.py  : NL → GeneratedQuery (schema-constrained LLM call)
  F2 — validator.py        : validate GeneratedQuery before execution (DOC3 §10, Invariant 13)
  F3 — query_executor.py   : execute validated Cypher and attach evidence (planned)
  F4 — narrator.py         : narrate GraphQueryResult over LLM (planned)
"""

