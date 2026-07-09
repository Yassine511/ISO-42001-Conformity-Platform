"""M6 evaluation harness (plan §10).

Deterministic scoring over persisted pipeline/chat provenance. Nothing in
this package calls an LLM or a vector store: it reads rows and artifacts and
computes frozen metrics. The scoring rules themselves are frozen in
eval/m6/regles_notation_pipeline.md (sha256 reported with every artifact).
"""
