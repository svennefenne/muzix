"""Place names among artists' genre tags ("finland", "DE", "U.S.A", "british"): taken off by the general
rule in Admin → Tags (tagging.py). The list is places_data.py, written by scripts/places.py with norm()."""

import re
from functools import cache


def norm(tag: str) -> str:
    """A tag as places are kept: lower case, no dots or dashes, single letters joined (U.S.A, u. s. a → usa)."""
    t = re.sub(r"[.\-_/]+", " ", tag.casefold())
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split(" ")
    return "".join(words) if len(words) > 1 and all(len(w) == 1 for w in words) else t


@cache
def _places() -> frozenset:
    from .places_data import PLACES     # read when first asked: scripts/places.py writes it with norm()
    return PLACES


def is_place(tag: str) -> bool:
    """Whether the whole tag is a place: "finnish" is, "finnish metal" isn't."""
    return norm(tag) in _places()
