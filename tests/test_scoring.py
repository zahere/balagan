"""Verdict parsing must survive what real models actually emit.

The v0.1 full run had 7/225 undecided trials; inspection pointed at markdown
decoration around the verdict token. These cases pin the hardened regex.
"""

import pytest

from balagan.scoring import majority, parse_verdict


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Checked it. VERDICT: TRUE", True),
        ("verdict: false", False),
        ("**VERDICT: TRUE**", True),
        ("**VERDICT:** FALSE", False),
        ("__VERDICT__ - true.", True),
        ("VERDICT:FALSE", False),
        ("The verdict — TRUE", None),  # no VERDICT token; stay strict
        ("VERDICT: TRUE ... on reflection, VERDICT: FALSE", False),  # last wins
        ("VERDICT: maybe", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_verdict(text, expected):
    assert parse_verdict(text) is expected


def test_majority_rules():
    assert majority([True, True, False]) is True
    assert majority([True, False]) is None  # tie -> undecided -> wrong
    assert majority([None, None]) is None
    assert majority([True, None, None]) is True  # abstentions don't block
