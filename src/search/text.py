"""Shared text-length constants for the search pipeline.

The pipeline truncates a few strings before they go into a structured log
event — a query, a synthesiser adjustment hint — so a log line stays a sane
length.  The planner, the synthesiser, and the core all do this; the cap
literals live here once rather than being respelled at each call site
(``CODE_GUIDELINES.md`` §3.5).

Depends on: nothing.
"""

from __future__ import annotations

# Maximum characters of a raw user query included in a structured log event.
# A query is logged for triage, not stored — ~60 chars identifies it without
# bloating the log line or risking a very long line in a JSON sink.
QUERY_LOG_PREFIX_CHARS = 60

# Maximum characters of a synthesiser adjustment hint included in a log event.
# An adjustment is a short instruction phrase; 120 chars captures it whole in
# the common case while still bounding a pathological one.
ADJUSTMENT_LOG_PREFIX_CHARS = 120
