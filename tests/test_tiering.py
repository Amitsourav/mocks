"""Unit tests for the reach/target/safe tiering (pure logic, no DB).

Verifies the honest tier rules: open admission is 'safe' only for a recognized
(H+) degree, restricted is always 'reach', unknown is 'target'; and that the
per-programme tier stays consistent with the aggregate tier_summary formula.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes.dashboard import _program_tier


def test_open_is_safe_only_when_eligible():
    assert _program_tier("open", eligible=True) == "safe"
    assert _program_tier("open", eligible=False) == "target"  # eligibility is the blocker


def test_restricted_is_always_reach():
    assert _program_tier("restricted", eligible=True) == "reach"
    assert _program_tier("restricted", eligible=False) == "reach"


def test_unknown_mode_is_target():
    assert _program_tier(None, eligible=True) == "target"
    assert _program_tier(None, eligible=False) == "target"


def test_tier_summary_formula_matches_per_programme_tally():
    # A sample matched set: (admission_mode) counts.
    modes = ["open"] * 5 + ["restricted"] * 3 + [None] * 4  # 5 open, 3 restricted, 4 unknown
    n_open, n_restricted, n_unknown = 5, 3, 4

    for eligible in (True, False):
        # Aggregate formula used by the route.
        summary = {
            "safe": n_open if eligible else 0,
            "target": n_unknown if eligible else n_open + n_unknown,
            "reach": n_restricted,
        }
        # Independent per-programme tally must agree.
        tally = {"safe": 0, "target": 0, "reach": 0}
        for m in modes:
            tally[_program_tier(m, eligible)] += 1
        assert tally == summary
        assert sum(summary.values()) == len(modes)
