"""Per-request nonce fences that mark untrusted text in LLM prompts as data.

Document text can read as instructions ("ignore your previous instructions").
A static delimiter could be copied into a document to fake the end of the data
region; a fresh random nonce per request cannot be.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

#: Bytes of entropy in a fence nonce (32 hex chars), far too many to guess.
_FENCE_NONCE_BYTES: int = 16


@dataclass(frozen=True, slots=True)
class DataFence:
    """A pair of fence markers sharing one per-request nonce."""

    nonce: str
    open_marker: str
    close_marker: str

    def wrap(self, content: str) -> str:
        """Return *content* between the markers, each on its own line."""
        return f"{self.open_marker}\n{content}\n{self.close_marker}"


def build_data_fence(*, label: str) -> DataFence:
    """Build a :class:`DataFence` with a fresh nonce, labelled *label*.

    Call once per request; a cached or module-level fence would make the nonce
    predictable. *label* (e.g. ``"DOCUMENT"``) tells several fences apart.
    """
    nonce = secrets.token_hex(_FENCE_NONCE_BYTES)
    return DataFence(
        nonce=nonce,
        open_marker=f"<<<{label} {nonce}>>>",
        close_marker=f"<<<END {label} {nonce}>>>",
    )
