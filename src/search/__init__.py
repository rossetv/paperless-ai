"""Search pipeline — the read side of the semantic search subsystem.

This package implements the agentic-but-bounded retrieval pipeline:
plan → retrieve (hybrid vector + keyword) → refine (≤1 time) → synthesise.

Allowed dependencies: store/ (StoreReader), common/.
Forbidden: indexer/, ocr/, classifier/. The core pipeline (planner, retriever,
synthesizer, refinement, core) imports neither fastapi nor mcp — those belong
only in api.py and mcp_server.py respectively.
"""
