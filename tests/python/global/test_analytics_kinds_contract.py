"""The analytics receiver takes every file kind the CAD apps send.

cadgen's analytics client names each file it counts by a kind (``FILE_KINDS``); the
api's receiver (`apps/api`) refuses a batch that names a kind outside the closed list of the
batch's schema, and a refused batch is dropped with every count in it. The two lists live in
two languages; this keeps the client's list one with its schema's list in the receiver.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.python.support.paths import add_repo_path

REPO = Path(__file__).resolve().parents[3]
add_repo_path("packages/cadgen/src")

from cadgen.analytics import KINDS, SCHEMA  # noqa: E402


def receiver_kinds(schema: int) -> set[str]:
    """The kinds the receiver takes in a batch of ``schema``: the `kinds` set its `SCHEMAS` entry names,
    each `new Set([...])` read with the sets it spreads (`...KINDS`)."""
    text = (REPO / "apps/api/src/events.mjs").read_text(encoding="utf-8")
    sets = {name: body for name, body in re.findall(r"const (KINDS\w*) = new Set\(\[([^\]]*)\]\)", text)}
    if "KINDS" not in sets:
        raise AssertionError("apps/api/src/events.mjs has no `const KINDS = new Set([...])`")
    start = text.find(f"[{schema}, {{ fields:")
    entry = re.compile(r"kinds: (KINDS\w*)").search(text, start) if start >= 0 else None
    if entry is None:
        raise AssertionError(f"apps/api/src/events.mjs's SCHEMAS has no entry for schema {schema} naming its kinds")

    def read(name: str) -> set[str]:
        body = sets[name]
        return set(re.findall(r"'([^']+)'", body)).union(*(read(spread) for spread in re.findall(r"\.\.\.(KINDS\w*)", body)))

    return read(entry.group(1))


class AnalyticsKindsContractTest(unittest.TestCase):
    def test_the_receiver_takes_every_kind_the_client_sends(self) -> None:
        self.assertEqual(set(KINDS), receiver_kinds(SCHEMA))


if __name__ == "__main__":
    unittest.main()
