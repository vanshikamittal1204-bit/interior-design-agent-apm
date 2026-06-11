"""Regression tests for ISSUE-01, ISSUE-03, ISSUE-04, ISSUE-05, ISSUE-06, ISSUE-07."""

import pytest

from planner.planner import Planner, PlannerRequest
from tools.evaluation_agent import EvaluationItem, EvaluationRequest, evaluate_plan
from tools.layout_validator import (
    FurniturePlacement,
    ValidationStatus,
    _minimum_clearance,
    plan_layout,
    validate_layout,
)
from utils.db import CatalogItem, DatabaseConnection


@pytest.fixture
def db():
    connection = DatabaseConnection()
    yield connection
    connection.close()


@pytest.fixture
def planner(db):
    return Planner(db=db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_item(items, category):
    for item in items:
        if item.category.lower() == category.lower() and item.has_complete_dimensions():
            return item
    return None


# ---------------------------------------------------------------------------
# ISSUE-01: best_layout must be None (not an invalid layout) when no valid
#           layout can be produced.
# ---------------------------------------------------------------------------

class TestIssue01NoBestLayoutWhenInvalid:

    def test_best_layout_is_none_when_furniture_does_not_fit(self, db):
        """A bed larger than the room must yield best_layout=None, not an invalid layout."""
        items = db.get_items_by_room_type("Bedroom")
        bed = _find_item(items, "bed")
        assert bed

        result = plan_layout(
            room_type="Bedroom",
            room_width_cm=100,
            room_depth_cm=100,
            selected_items=[bed],
        )

        assert result.best_layout is None, (
            "best_layout must be None when no valid layout exists (ISSUE-01)"
        )
        assert len(result.failure_reasons) > 0

    def test_failure_reasons_populated_when_no_valid_layout(self, db):
        """failure_reasons must contain meaningful text when layout validation fails."""
        items = db.get_items_by_room_type("Bedroom")
        bed = _find_item(items, "bed")
        assert bed

        result = plan_layout(
            room_type="Bedroom",
            room_width_cm=100,
            room_depth_cm=100,
            selected_items=[bed],
        )

        assert result.failure_reasons, "failure_reasons must not be empty"
        assert any(len(r) > 5 for r in result.failure_reasons)

    def test_valid_layout_not_affected(self, db):
        """A room that fits all items still returns a valid best_layout."""
        items = db.get_items_by_room_type("Living Room")
        sofa = _find_item(items, "sofa")
        tv = _find_item(items, "tv unit")
        coffee = _find_item(items, "coffee table")
        assert sofa and tv and coffee

        result = plan_layout(
            room_type="Living Room",
            room_width_cm=500,
            room_depth_cm=420,
            selected_items=[sofa, tv, coffee],
        )

        assert result.best_layout is not None
        assert result.best_layout.validation.valid
        assert result.best_layout.validation.validation_status == ValidationStatus.VALID

    def test_layout_passed_false_when_best_layout_none(self, planner):
        """PlannerResult.layout_passed must be False when no valid layout exists."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=300_000,
            room_width_cm=50,
            room_depth_cm=50,
            must_haves=["sofa"],
        )
        result = planner.generate_plan(request)

        assert result.layout_passed is False


# ---------------------------------------------------------------------------
# ISSUE-03: Single-item layout must not receive an inflated circulation score.
# ---------------------------------------------------------------------------

class TestIssue03SingleItemClearance:

    def test_single_item_minimum_clearance_equals_threshold(self):
        """_minimum_clearance for one item must return MIN_CIRCULATION_CM, not inf."""
        from tools.layout_validator import MIN_CIRCULATION_CM

        placements = [
            FurniturePlacement(
                item_id="A", item_name="Sofa", category="Sofa",
                x=50, y=50, width=190, depth=85,
            )
        ]
        clearance = _minimum_clearance(placements)
        assert clearance == MIN_CIRCULATION_CM, (
            f"Expected {MIN_CIRCULATION_CM}, got {clearance} (ISSUE-03)"
        )

    def test_single_item_circulation_score_not_maximum(self):
        """validate_layout for a lone item must not award the maximum circulation score."""
        from tools.layout_validator import CIRCULATION_WEIGHT

        placements = [
            FurniturePlacement(
                item_id="A", item_name="Sofa", category="Sofa",
                x=50, y=50, width=190, depth=85,
            )
        ]
        result = validate_layout(placements, room_width_cm=400, room_depth_cm=400)

        assert result.valid
        # Score must equal exactly the neutral threshold value, not CIRCULATION_WEIGHT
        assert result.circulation_score < CIRCULATION_WEIGHT, (
            "Single-item layout must not score the maximum circulation weight (ISSUE-03)"
        )
        assert result.minimum_clearance_cm < float("inf"), (
            "minimum_clearance_cm must not be inf for a single-item layout (ISSUE-03)"
        )

    def test_two_items_clearance_computed_normally(self):
        """With two items, clearance is the real edge distance, not the threshold."""
        placements = [
            FurniturePlacement(item_id="A", item_name="Sofa", category="Sofa",
                               x=0, y=0, width=190, depth=85),
            FurniturePlacement(item_id="B", item_name="TV Unit", category="TV Unit",
                               x=0, y=250, width=180, depth=40),
        ]
        clearance = _minimum_clearance(placements)
        assert clearance == pytest.approx(250 - 85, abs=1), (
            "Two-item clearance must be the actual edge distance"
        )


# ---------------------------------------------------------------------------
# ISSUE-04: PlannerResult must expose optional_cost as a canonical field so
#           consumers do not need to re-sum optional_additions independently.
# ---------------------------------------------------------------------------

class TestIssue04OptionalCostField:

    def test_optional_cost_matches_sum_of_optional_additions(self, planner):
        """optional_cost must equal the sum of optional_additions prices."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=300_000,
            room_width_cm=600,
            room_depth_cm=450,
            must_haves=["sofa", "coffee table", "tv unit"],
        )
        result = planner.generate_plan(request)

        assert result.optional_additions, (
            "Precondition failed: no optional_additions were recommended. "
            "Increase budget or room size so optional items are suggested."
        )

        expected = sum(item.price_inr for item in result.optional_additions)
        assert result.optional_cost == expected, (
            f"optional_cost ({result.optional_cost}) does not match "
            f"sum of optional_additions prices ({expected}) (ISSUE-04)"
        )

    def test_optional_cost_is_zero_when_no_optional_additions(self, planner):
        """optional_cost must be 0 when optional_additions is empty (e.g. out-of-scope)."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=300_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes="rewire the apartment",
        )
        result = planner.generate_plan(request)

        assert result.optional_additions == []
        assert result.optional_cost == 0, (
            f"optional_cost must be 0 when optional_additions is empty (ISSUE-04), "
            f"got {result.optional_cost}"
        )


# ---------------------------------------------------------------------------
# ISSUE-05: Auto-added functional items must be surfaced clearly.
# ---------------------------------------------------------------------------

class TestIssue05AutoAddedFunctional:

    def test_auto_added_functional_field_populated(self, planner):
        """auto_added_functional must list categories added to satisfy requirements."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=250_000,
            room_width_cm=500,
            room_depth_cm=400,
            must_haves=[],  # no must-haves → all functional items are auto-added
        )
        result = planner.generate_plan(request)

        assert isinstance(result.auto_added_functional, list)
        functional_cats = {"sofa", "coffee table", "tv unit"}
        present = {cat for cat in result.auto_added_functional if cat in functional_cats}
        assert len(present) > 0, (
            "auto_added_functional must contain at least one functional category (ISSUE-05)"
        )

    def test_must_have_not_listed_as_auto_added(self, planner):
        """Items explicitly requested by the user must NOT appear in auto_added_functional."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=250_000,
            room_width_cm=500,
            room_depth_cm=400,
            must_haves=["sofa", "coffee table", "tv unit"],
        )
        result = planner.generate_plan(request)

        assert "sofa" not in result.auto_added_functional
        assert "coffee table" not in result.auto_added_functional
        assert "tv unit" not in result.auto_added_functional

    def test_auto_added_annotation_in_selection_reasons(self, planner):
        """selection_reasons must contain [AUTO-ADDED] tags for functional items."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=250_000,
            room_width_cm=500,
            room_depth_cm=400,
            must_haves=[],
        )
        result = planner.generate_plan(request)

        auto_added_reasons = [r for r in result.selection_reasons if "[AUTO-ADDED]" in r]
        assert len(auto_added_reasons) > 0, (
            "selection_reasons must contain at least one [AUTO-ADDED] entry (ISSUE-05)"
        )

    def test_no_auto_added_when_all_satisfied_by_must_haves(self, planner):
        """When must-haves cover all functional requirements, auto_added_functional is empty."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=300_000,
            room_width_cm=500,
            room_depth_cm=400,
            must_haves=["sofa", "coffee table", "tv unit"],
        )
        result = planner.generate_plan(request)

        assert result.auto_added_functional == [], (
            "auto_added_functional must be empty when must-haves satisfy all requirements (ISSUE-05)"
        )


# ---------------------------------------------------------------------------
# ISSUE-07: Out-of-scope requests must be detected and refused.
# ---------------------------------------------------------------------------

class TestIssue07OutOfScope:

    # --- Structural intents that must be rejected ---

    @pytest.mark.parametrize("notes", [
        "remove wall between living room and kitchen",
        "demolish wall to open up space",
        "knock down wall for open plan",
        "knock wall down to merge rooms",
    ])
    def test_structural_wall_modifications_rejected(self, planner, notes):
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes=notes,
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is not None, (
            f"Expected out-of-scope rejection for notes='{notes}' (ISSUE-07)"
        )
        assert result.selected_items == []

    @pytest.mark.parametrize("notes", [
        "rewire the entire apartment",
        "add socket near the window",
        "move outlet to the other wall",
        "install socket beside the TV unit",
        "electrical wiring needs updating",
    ])
    def test_electrical_work_rejected(self, planner, notes):
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes=notes,
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is not None, (
            f"Expected out-of-scope rejection for notes='{notes}' (ISSUE-07)"
        )

    @pytest.mark.parametrize("notes", [
        "install plumbing for wet bar",
        "move drain in the corner",
        "install tap near the island",
        "plumbing work required for sink",
    ])
    def test_plumbing_work_rejected(self, planner, notes):
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes=notes,
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is not None, (
            f"Expected out-of-scope rejection for notes='{notes}' (ISSUE-07)"
        )

    @pytest.mark.parametrize("notes", [
        "install hvac system",
        "add hvac duct above the sofa",
        "install duct for better airflow",
    ])
    def test_hvac_work_rejected(self, planner, notes):
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes=notes,
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is not None, (
            f"Expected out-of-scope rejection for notes='{notes}' (ISSUE-07)"
        )

    def test_unsupported_room_type_rejected(self, planner):
        request = PlannerRequest(
            room_type="Garage",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is not None
        assert "garage" in result.out_of_scope_reason.lower()

    # --- Valid design references that must NOT be rejected ---

    @pytest.mark.parametrize("notes", [
        "place TV on the wall",
        "floor lamp beside the sofa",
        "ceiling light above dining table",
        "wall art above the sofa",
        "tap into the cozy aesthetic",
        "pipe dream: a reading corner",
        "drainpipe-style floor lamp",
    ])
    def test_valid_design_references_not_rejected(self, planner, notes):
        """Normal interior-design language must never trigger an out-of-scope refusal."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes=notes,
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is None, (
            f"Valid design note '{notes}' was incorrectly rejected (ISSUE-07)"
        )

    def test_out_of_scope_result_has_empty_selected_items(self, planner):
        """An out-of-scope request must return no selected items."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes="rewire the apartment",
        )
        result = planner.generate_plan(request)

        assert result.selected_items == []
        assert result.optional_additions == []
        assert result.total_cost == 0

    def test_out_of_scope_reason_message_is_informative(self, planner):
        """out_of_scope_reason must mention the matched phrase."""
        request = PlannerRequest(
            room_type="Living Room",
            style="Scandinavian",
            budget=200_000,
            room_width_cm=500,
            room_depth_cm=400,
            notes="add socket behind the bookshelf",
        )
        result = planner.generate_plan(request)

        assert result.out_of_scope_reason is not None
        assert "add socket" in result.out_of_scope_reason


# ---------------------------------------------------------------------------
# ISSUE-06: _score_style_consistency must return 0 (not 40) when no items
#           match the requested style preference.
# ---------------------------------------------------------------------------

def _eval_item(item_id: str, category: str, name: str, style_tags: list) -> EvaluationItem:
    return EvaluationItem(
        item_id=item_id,
        category=category,
        name=name,
        price_inr=50_000,
        style_tags=style_tags,
    )


def _style_request(selected_items, style_preference: str) -> EvaluationRequest:
    return EvaluationRequest(
        selected_items=selected_items,
        optional_additions=[],
        rejected_items=[],
        layout_plan=None,
        room_type="Living Room",
        room_width_cm=400,
        room_depth_cm=300,
        budget_inr=200_000,
        style_preference=style_preference,
        must_haves=[],
    )


class TestIssue06StyleConsistency:

    def test_zero_style_matches_scores_0_not_40(self):
        """When every selected item has the wrong style, score must be 0, not 40 (ISSUE-06)."""
        request = _style_request(
            selected_items=[
                _eval_item("X-001", "Sofa", "Industrial Sofa", ["Industrial"]),
                _eval_item("X-002", "Coffee Table", "Industrial Coffee Table", ["Industrial"]),
            ],
            style_preference="Scandinavian",
        )
        result = evaluate_plan(request)

        assert result.score_breakdown["style_consistency"] == 0, (
            f"style_consistency must be 0 when no items match the style, "
            f"got {result.score_breakdown['style_consistency']} (ISSUE-06)"
        )

    def test_zero_style_matches_produces_cons_message(self):
        """Zero-match path must report the unmatched style keyword in cons."""
        request = _style_request(
            selected_items=[
                _eval_item("X-001", "Sofa", "Industrial Sofa", ["Industrial"]),
            ],
            style_preference="Scandinavian",
        )
        result = evaluate_plan(request)

        assert any("scandinavian" in c.lower() for c in result.cons), (
            "cons must mention the unmatched style keyword (ISSUE-06)"
        )

    def test_full_style_match_still_scores_100(self):
        """Full style match must continue to score 100 after the fix (regression guard)."""
        request = _style_request(
            selected_items=[
                _eval_item("X-001", "Sofa", "Scandi Sofa", ["Scandinavian"]),
                _eval_item("X-002", "Coffee Table", "Scandi Table", ["Scandinavian"]),
            ],
            style_preference="Scandinavian",
        )
        result = evaluate_plan(request)

        assert result.score_breakdown["style_consistency"] == 100
