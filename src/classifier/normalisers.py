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


def _is_letter_with_word_marks(ch: str) -> bool:
    """Whether marks on *ch* spell the word (Devanagari vowel signs) rather
    than accent it (the umlaut in "Müller", which is folded away)."""
    return ch.isalpha() and not unicodedata.name(ch, "").startswith(
        ("LATIN", "GREEK", "CYRILLIC")
    )


def normalise_name(value: str) -> str:
    """
    Normalise an organisation name for fuzzy matching.

    Strips punctuation and the accents of Latin, Greek and Cyrillic letters,
    lowercases, and removes trailing corporate suffixes so that
    *"Revolut Ltd."* and *"Revolut"* compare as equal. Letters of any script
    are kept, with the vowel signs of scripts that write vowels as marks.

    >>> normalise_name("Revolut Ltd.")
    'revolut'
    >>> normalise_name("Müller GmbH")
    'muller'
    """
    return _fold_name(value, punctuation="")


def name_words(value: str) -> str:
    """
    Normalise an organisation name like :func:`normalise_name`, but with
    punctuation as a word break, for whole-word containment.

    >>> name_words("Amazon.co.uk")
    'amazon co uk'
    """
    return _fold_name(value, punctuation=" ")


def _fold_name(value: str, punctuation: str) -> str:
    # Symbols and superscripts go first: NFKD would turn "™" into "TM", "²" into "2".
    kept = "".join(ch for ch in value if not _is_symbol_or_other_number(ch))
    folded = unicodedata.normalize("NFKD", kept).casefold()
    chars: list[str] = []
    base = ""
    for ch in folded:
        if unicodedata.category(ch).startswith("M"):
            if _is_letter_with_word_marks(base):
                chars.append(ch)
            continue
        base = ch
        chars.append(ch if ch.isalnum() or ch.isspace() else punctuation)
    parts = "".join(chars).split()
    while parts and parts[-1] in COMPANY_SUFFIXES:
        parts.pop()
    return " ".join(parts)
