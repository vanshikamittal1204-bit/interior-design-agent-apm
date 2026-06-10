import pytest

from tools.evaluation_agent import (
    EvaluationItem,
    EvaluationRejectedItem,
    EvaluationRequest,
    evaluate_plan,
)
from tools.layout_validator import (
    LayoutPlanResult,
    LayoutEvaluation,
    ValidationResult,
    ValidationStatus,
)


def _build_layout_plan(valid: bool, minimum_clearance: float = 80.0, occupancy_ratio: float = 0.45) -> LayoutPlanResult:
    validation = ValidationResult(
        valid=valid,
        validation_status=ValidationStatus.VALID if valid else ValidationStatus.INVALID,
        reasons=[] if valid else ["Overlap detected"],
        occupancy_ratio=occupancy_ratio,
        circulation_score=20.0 if valid else 0.0,
        minimum_clearance_cm=minimum_clearance,
        furniture_area_cm2=12000,
        room_area_cm2=40000,
    )
    layout = LayoutEvaluation(
        layout_id="test_layout",
        layout_type="Test layout",
        placements=[],
        validation=validation,
        layout_score=75.0,
        pros=["Balanced placement."],
        cons=[],
    )
    return LayoutPlanResult(
        room_type="Living Room",
        room_width_cm=400,
        room_depth_cm=300,
        best_layout=layout,
        alternative_layouts=[layout],
        replan_triggered=False,
        removed_item_ids=[],
        failure_reasons=[],
        all_layouts_generated=1,
        valid_layout_count=1,
    )


def test_evaluate_plan_returns_high_scores_for_valid_plan():
    request = EvaluationRequest(
        selected_items=[
            EvaluationItem(
                item_id="SOF-001",
                category="Sofa",
                name="Scandi Sofa",
                price_inr=90000,
                width_cm=200,
                depth_cm=90,
                style_tags=["Scandinavian"],
            ),
            EvaluationItem(
                item_id="TV-001",
                category="TV Unit",
                name="Minimal TV Unit",
                price_inr=30000,
                width_cm=150,
                depth_cm=45,
                style_tags=["Scandinavian"],
            ),
            EvaluationItem(
                item_id="COF-001",
                category="Coffee Table",
                name="Scandi Coffee Table",
                price_inr=20000,
                width_cm=100,
                depth_cm=60,
                style_tags=["Scandinavian"],
            ),
        ],
        optional_additions=[],
        rejected_items=[],
        layout_plan=_build_layout_plan(valid=True),
        room_type="Living Room",
        room_width_cm=400,
        room_depth_cm=300,
        budget_inr=150000,
        style_preference="Scandinavian",
        must_haves=["sofa", "coffee table", "tv unit"],
        notes="movie night",
    )
    evaluation = evaluate_plan(request)

    assert evaluation.overall_score == 95
    assert evaluation.confidence_level == 100
    assert "All required must-haves are included." in evaluation.pros
    assert all(score >= 40 for score in evaluation.score_breakdown.values())
    assert "Budget is efficiently utilized." in evaluation.pros


def test_evaluate_plan_detects_missing_must_haves_and_invalid_layout():
    request = EvaluationRequest(
        selected_items=[
            EvaluationItem(
                item_id="SOF-002",
                category="Sofa",
                name="Modern Sofa",
                price_inr=150000,
                width_cm=220,
                depth_cm=90,
                style_tags=["Minimalist"],
            )
        ],
        optional_additions=[],
        rejected_items=[EvaluationRejectedItem(item_name="coffee table", reason="catalog unavailable")],
        layout_plan=_build_layout_plan(valid=False),
        room_type="Living Room",
        room_width_cm=300,
        room_depth_cm=250,
        budget_inr=200000,
        style_preference="Scandinavian",
        must_haves=["sofa", "coffee table", "tv unit"],
    )
    evaluation = evaluate_plan(request)

    assert evaluation.score_breakdown["must_have_coverage"] == 33
    assert evaluation.score_breakdown["layout_validity"] == 0
    assert any("Missing must-have item or category" in reason for reason in evaluation.cons)
    assert any("Overlap detected" in reason for reason in evaluation.cons)
    assert evaluation.overall_score < 50


def test_evaluate_plan_scores_budget_underuse():
    request = EvaluationRequest(
        selected_items=[
            EvaluationItem(
                item_id="BED-001",
                category="Bed",
                name="Cosy Bed",
                price_inr=30000,
                width_cm=180,
                depth_cm=200,
                style_tags=["Minimalist"],
            )
        ],
        optional_additions=[],
        rejected_items=[],
        layout_plan=_build_layout_plan(valid=True),
        room_type="Bedroom",
        room_width_cm=450,
        room_depth_cm=360,
        budget_inr=150000,
        style_preference="Minimalist",
        must_haves=["bed", "wardrobe"],
    )
    evaluation = evaluate_plan(request)

    assert evaluation.score_breakdown["budget_utilization"] == 40
    assert any("underuses available budget" in reason for reason in evaluation.cons)
    assert evaluation.score_breakdown["functional_completeness"] == 50


def test_evaluate_plan_handles_missing_style_preference_as_full_score():
    request = EvaluationRequest(
        selected_items=[
            EvaluationItem(
                item_id="DIN-001",
                category="Dining Table",
                name="Oak Dining Table",
                price_inr=50000,
                width_cm=150,
                depth_cm=90,
            )
        ],
        optional_additions=[],
        rejected_items=[],
        layout_plan=_build_layout_plan(valid=True),
        room_type="Dining Room",
        room_width_cm=360,
        room_depth_cm=320,
        budget_inr=120000,
        style_preference=None,
        must_haves=["dining table"],
    )
    evaluation = evaluate_plan(request)

    assert evaluation.score_breakdown["style_consistency"] == 100
    assert "No style preference was specified." in evaluation.pros
    assert evaluation.confidence_level == 100


def test_evaluate_plan_returns_consistent_reasoning_entries():
    request = EvaluationRequest(
        selected_items=[],
        optional_additions=[],
        rejected_items=[],
        layout_plan=None,
        room_type="Study",
        room_width_cm=300,
        room_depth_cm=250,
        budget_inr=50000,
        style_preference="Industrial",
        must_haves=["desk", "chair"],
    )
    evaluation = evaluate_plan(request)

    assert evaluation.overall_score == 5
    assert evaluation.confidence_level == 70
    assert len(evaluation.reasoning) == 6
    assert "Layout validity: 0/100" in evaluation.reasoning[2]
