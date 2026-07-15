"""Verdict extraction and decision rules."""

from __future__ import annotations

import re

# Tolerates the decoration real models emit around the token we asked for:
#   "VERDICT: TRUE" · "**VERDICT: FALSE**" · "**VERDICT:** TRUE" · "verdict - true."
# Root cause of the v0.1 full-run parse misses: markdown bold around the verdict.
_VERDICT_RE = re.compile(
    r"VERDICT[\*_`]*\s*[:\-\u2013]?\s*[\*_`\"']*\s*(TRUE|FALSE)", re.IGNORECASE
)


def parse_verdict(text: str | None) -> bool | None:
    """Return the LAST stated verdict in a message, or None if absent."""
    if not text:
        return None
    matches = _VERDICT_RE.findall(text)
    if not matches:
        return None
    return matches[-1].upper() == "TRUE"


def majority(verdicts: list[bool | None]) -> bool | None:
    """Strict majority over parseable verdicts. Ties or empty -> None.

    A None decision is scored as incorrect: a mesh that cannot decide has
    failed, which is precisely the behavior the harness measures.
    """
    votes = [v for v in verdicts if v is not None]
    if not votes:
        return None
    yes = sum(votes)
    no = len(votes) - yes
    if yes == no:
        return None
    return yes > no
