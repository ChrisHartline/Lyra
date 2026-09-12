from __future__ import annotations

from scripts.validate_docs import validate_documentation


def test_documentation_links_and_freshness_invariants():
    assert validate_documentation() == []
