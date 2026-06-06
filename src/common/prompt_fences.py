"""Per-request nonce fences for isolating untrusted content in LLM prompts.

Both the search synthesiser and the document classifier embed
operator-unknown, untrusted text — retrieved document chunks, raw OCR
transcriptions — into an LLM prompt. That text can read as an instruction
("ignore your previous instructions and ..."), so §10.2 requires it be fenced
and the model told to treat everything inside the fence as data, never as
instructions.

A *static* delimiter is source-visible: an attacker who knows the marker can
embed it in a document to forge the boundary and smuggle a control marker that
reads as being outside the data region. The defence is a fresh, unguessable
nonce per request: a document cannot reproduce a token it cannot see, so it
cannot forge the closing fence to break out of the data region or open a fake
control plane.

This module is the single home of that pattern (§1.3) so the synthesiser and
the classifier do not carry two parallel copies. It lives in ``common/`` so
both callers may import it within the import rules (§2.3, §2.5): ``classifier``
may import ``common`` but not ``search``, and ``search`` may import ``common``.

Allowed deps: standard library only.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

#: Bytes of entropy in a fence nonce. 16 bytes (32 hex chars) is far beyond any
#: document's ability to guess or reproduce the closing marker.
_FENCE_NONCE_BYTES: int = 16


@dataclass(frozen=True, slots=True)
class DataFence:
    """A matched pair of nonce-bearing fence markers for one prompt.

    The *same* nonce appears in both markers, so the model can be told the data
    region runs from the opening marker to the matching closing marker — a
    region a document cannot terminate early because it cannot reproduce the
    nonce.

    Attributes:
        nonce: The per-request random hex token both markers carry.
        open_marker: The marker that begins the untrusted-data region.
        close_marker: The marker that ends it; carries the same nonce.
    """

    nonce: str
    open_marker: str
    close_marker: str

    def wrap(self, content: str) -> str:
        """Return *content* wrapped between the opening and closing markers.

        Each marker sits on its own line so the fence is unambiguous even when
        the content begins or ends mid-line.
        """
        return f"{self.open_marker}\n{content}\n{self.close_marker}"


def build_data_fence(*, label: str) -> DataFence:
    """Build a fresh nonce :class:`DataFence` labelled *label*.

    The nonce is generated here, per call, **after and independently of** any
    document content the caller will wrap — so the content can never contain it
    (§10.2). Call this once per request, never module-level or cached, or the
    nonce would become predictable and forgeable.

    Args:
        label: A short human-readable tag woven into both markers (e.g.
            ``"DATA"`` or ``"DOCUMENT"``), so a prompt that uses more than one
            fence keeps them distinguishable.

    Returns:
        A :class:`DataFence` whose two markers share one fresh nonce.
    """
    nonce = secrets.token_hex(_FENCE_NONCE_BYTES)
    return DataFence(
        nonce=nonce,
        open_marker=f"<<<{label} {nonce}>>>",
        close_marker=f"<<<END {label} {nonce}>>>",
    )
