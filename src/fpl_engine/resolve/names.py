"""Name normalisation and fuzzy matching for cross-source entity resolution.

Uses only the standard library (``unicodedata`` + ``difflib``) so there is no
extra dependency for the fuzzy layer.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str | None) -> str:
    """Lowercase, de-accent, drop punctuation, collapse whitespace."""
    if not name:
        return ""
    text = strip_accents(name).lower().replace("_", " ")
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# External-source full club names (normalised) -> the FPL name/short they denote.
# Shared by every ingestor that resolves a club name to an FPL team_id.
TEAM_ALIASES = {
    "manchester city": "man city",
    "manchester united": "man utd",
    "man united": "man utd",
    "newcastle united": "newcastle",
    "wolverhampton wanderers": "wolves",
    "tottenham": "spurs",
    "tottenham hotspur": "spurs",
    "nottingham forest": "nott m forest",
    "forest": "nott m forest",
    "west bromwich albion": "west brom",
    "sheffield united": "sheffield utd",
    "leeds united": "leeds",
    "huddersfield town": "huddersfield",
    "cardiff city": "cardiff",
    "swansea city": "swansea",
    "stoke city": "stoke",
    "hull city": "hull",
    "leicester city": "leicester",
    "norwich city": "norwich",
    "luton town": "luton",
    "ipswich town": "ipswich",
    "brighton hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "afc bournemouth": "bournemouth",
}


def resolve_team(name: str | None, index: dict[str, int],
                 *, threshold: float = 0.8) -> int | None:
    """Map an external club name to an FPL team_id via alias + fuzzy match.

    ``index`` maps normalised FPL name/short -> team_id (built by the caller).
    """
    if not name or not index:
        return None
    key = normalize_name(name)
    key = TEAM_ALIASES.get(key, key)
    if key in index:
        return index[key]
    match, _ = best_match(key, list(index.items()), threshold=threshold)
    return match


def best_match(
    query: str,
    candidates: Iterable[tuple[str, object]],
    *,
    threshold: float = 0.84,
    margin: float = 0.04,
) -> tuple[object | None, float]:
    """Return (best_key, score) for the closest normalised candidate name.

    ``candidates`` is an iterable of ``(name, key)``; a key may appear under
    several name variants (its score is the max over variants). Returns
    ``(None, score)`` when the best score is below ``threshold`` OR when the
    best distinct key does not beat the runner-up *key* by ``margin``
    (ambiguous — e.g. two different players sharing a name; better left
    unmatched for manual review than guessed wrong).
    """
    q = normalize_name(query)
    by_key: dict[object, float] = {}
    for name, key in candidates:
        score = similarity(q, normalize_name(name))
        if key not in by_key or score > by_key[key]:
            by_key[key] = score
    if not by_key:
        return None, 0.0

    ranked = sorted(by_key.items(), key=lambda kv: kv[1], reverse=True)
    best_key, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if best_score < threshold:
        return None, best_score
    if (best_score - runner_up) < margin:
        return None, best_score  # ambiguous: too close to a different key
    return best_key, best_score
