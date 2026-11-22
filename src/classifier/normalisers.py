"""String normalisation for taxonomy matching and tag filtering."""

from __future__ import annotations

import unicodedata

# Corporate suffixes stripped when comparing organisation names.
COMPANY_SUFFIXES: frozenset[str] = frozenset(
    {
        "ab",
        "as",
        "bv",
        "co",
        "company",
        "corp",
        "corporation",
        "gmbh",
        "inc",
        "incorporated",
        "limited",
        "llc",
        "ltd",
        "oy",
        "plc",
        "sa",
        "sarl",
        "spa",
    }
)


def normalise_simple(value: str) -> str:
    """
    Collapse whitespace and lowercase a string.

    >>> normalise_simple("  Bank  Statement ")
    'bank statement'
    """
    return " ".join(value.lower().split())


def _is_symbol_or_other_number(ch: str) -> bool:
    category = unicodedata.category(ch)
    return category.startswith("S") or category == "No"


def normalise_name(value: str) -> str:
    """
    Normalise an organisation name for fuzzy matching.

    Strips punctuation and accents, lowercases, and removes trailing
    corporate suffixes so that *"Revolut Ltd."* and *"Revolut"* compare as
    equal. Letters of any script are kept.

    >>> normalise_name("Revolut Ltd.")
    'revolut'
    >>> normalise_name("Müller GmbH")
    'muller'
    """
    # Symbols and superscripts go first: NFKD would turn "™" into "TM", "²" into "2".
    kept = "".join(ch for ch in value if not _is_symbol_or_other_number(ch))
    folded = unicodedata.normalize("NFKD", kept).casefold()
    cleaned = "".join(
        ch
        for ch in folded
        if (ch.isalnum() or ch.isspace()) and not unicodedata.combining(ch)
    )
    parts = cleaned.split()
    while parts and parts[-1] in COMPANY_SUFFIXES:
        parts.pop()
    return " ".join(parts)
