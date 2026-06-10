import logging

import pytest

from planner.planner import Planner, PlannerRequest, RejectedItem
from utils.db import DatabaseConnection

logger = logging.getLogger(__name__)


@pytest.fixture
def db():
    connection = DatabaseConnection()
    yield connection
    connection.close()


@pytest.fixture
def planner(db):
    return Planner(db=db)


def _category_lower_set(items):
    return {item.category.lower() for item in items}


def _has_category(items, category):
    return any(category.lower() in item.category.lower() for item in items)


def _fetch_selected_db_items(db, selected_ids):
    items = []
    for item_id in selected_ids:
        item = db.get_item_by_id(item_id)
        if item:
            items.append(item)
    return items


def test_happy_path_selects_functional_items(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=250_000,
        room_width_cm=500,
        room_depth_cm=400,
        must_haves=["sofa", "coffee table", "tv unit"],
        notes="movie night",
    )
    result = planner.generate_plan(request)

    assert result.selected_items, "Planner should select at least one item"
    assert result.layout_passed is True
    assert result.total_cost <= request.budget
    assert _has_category(result.selected_items, "sofa")
    assert _has_category(result.selected_items, "coffee table")
    assert _has_category(result.selected_items, "tv unit")


def test_low_budget_scenario_returns_budget_compliant_plan(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=5_000,
        room_width_cm=400,
        room_depth_cm=300,
        must_haves=["sofa"],
    )
    result = planner.generate_plan(request)

    assert result.total_cost <= request.budget
    assert result.remaining_budget == request.budget - result.total_cost
    assert all(rejected.reason in {"budget exceeded", "catalog unavailable"} for rejected in result.rejected_items)


def test_must_have_priority_is_respected(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=300_000,
        room_width_cm=500,
        room_depth_cm=400,
        must_haves=["sofa", "coffee table", "tv unit"],
    )
    result = planner.generate_plan(request)

    assert _has_category(result.selected_items, "sofa")
    assert _has_category(result.selected_items, "coffee table")
    assert _has_category(result.selected_items, "tv unit")
    assert any("must-have" in reason.lower() for reason in result.selection_reasons)


def test_optional_additions_are_separated_from_main_boq(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=300_000,
        room_width_cm=600,
        room_depth_cm=450,
        must_haves=["sofa", "coffee table", "tv unit"],
        notes="cozy space",
    )
    result = planner.generate_plan(request)

    selected_ids = {item.item_id for item in result.selected_items}
    optional_ids = {item.item_id for item in result.optional_additions}

    assert selected_ids.isdisjoint(optional_ids)
    assert result.optional_additions or result.remaining_budget > 0


def test_layout_validation_integration(planner):
    request = PlannerRequest(
        room_type="Bedroom",
        style="Minimalist",
        budget=200_000,
        room_width_cm=450,
        room_depth_cm=360,
        must_haves=["bed", "wardrobe"],
        notes="quiet retreat",
    )
    result = planner.generate_plan(request)

    assert isinstance(result.layout_passed, bool)
    assert result.layout_passed is True
    assert result.metrics.layout_validation_time_seconds >= 0


def test_single_replan_is_triggered_when_required(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=200_000,
        room_width_cm=240,
        room_depth_cm=240,
        must_haves=["sofa", "coffee table", "tv unit"],
        notes="movie night",
    )
    result = planner.generate_plan(request)

    assert result.replan_count <= 1
    assert any(rejected.reason == "layout fit failure" for rejected in result.rejected_items)


def test_replan_never_exceeds_one_cycle(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=200_000,
        room_width_cm=240,
        room_depth_cm=240,
        must_haves=["sofa", "coffee table", "tv unit", "lamp"],
    )
    result = planner.generate_plan(request)

    assert result.replan_count in {0, 1}


def test_budget_compliance_for_selected_items(planner):
    request = PlannerRequest(
        room_type="Bedroom",
        style="Scandinavian",
        budget=150_000,
        room_width_cm=420,
        room_depth_cm=360,
        must_haves=["bed", "wardrobe"],
    )
    result = planner.generate_plan(request)

    assert result.total_cost <= request.budget
    assert result.remaining_budget >= 0


def test_catalog_room_and_style_compatibility(db, planner):
    request = PlannerRequest(
        room_type="Study",
        style="Scandinavian",
        budget=200_000,
        room_width_cm=420,
        room_depth_cm=360,
        must_haves=["desk", "chair"],
    )
    result = planner.generate_plan(request)

    selected_ids = [item.item_id for item in result.selected_items]
    selected_items = _fetch_selected_db_items(db, selected_ids)

    assert selected_items, "Selected items should exist in the catalog"
    assert all(item.is_in_stock() for item in selected_items)
    assert all(item.matches_room_type(request.room_type) for item in selected_items)
    assert all(item.matches_style(request.style) for item in selected_items)


def test_reading_corner_priority_boost(planner, db):
    available = [
        item
        for item in db.get_items_by_room_type("Study")
        if item.category.lower() in {"bookshelf", "floor lamp", "table lamp", "accent chair"}
    ]
    if not available:
        pytest.skip("No study reading corner candidates available in catalog")

    request = PlannerRequest(
        room_type="Study",
        style="Scandinavian",
        budget=250_000,
        room_width_cm=420,
        room_depth_cm=360,
        must_haves=["desk", "chair"],
        notes="reading corner",
    )
    result = planner.generate_plan(request)

    assert any(
        item.category.lower() in {"bookshelf", "floor lamp", "table lamp", "accent chair"}
        for item in result.optional_additions + result.selected_items
    )


def test_work_from_home_priority_boost(planner, db):
    available = [
        item
        for item in db.get_items_by_room_type("Study")
        if item.category.lower() in {"desk", "chair", "bookshelf"}
    ]
    if not available:
        pytest.skip("No work-from-home candidates available in catalog")

    request = PlannerRequest(
        room_type="Study",
        style="Minimalist",
        budget=250_000,
        room_width_cm=420,
        room_depth_cm=360,
        must_haves=["desk"],
        notes="work from home",
    )
    result = planner.generate_plan(request)

    assert any(
        item.category.lower() in {"desk", "chair", "bookshelf"}
        for item in result.optional_additions + result.selected_items
    )


def test_rejected_item_tracking_for_unavailable_must_haves(planner):
    request = PlannerRequest(
        room_type="Living Room",
        style="Scandinavian",
        budget=200_000,
        room_width_cm=500,
        room_depth_cm=400,
        must_haves=["moon chair"],
    )
    result = planner.generate_plan(request)

    assert any(rejected.item_name == "moon chair" for rejected in result.rejected_items)
    assert any(rejected.reason == "catalog unavailable" for rejected in result.rejected_items)


def test_transparency_fields_are_populated(planner):
    request = PlannerRequest(
        room_type="Dining Room",
        style="Contemporary",
        budget=200_000,
        room_width_cm=450,
        room_depth_cm=380,
        must_haves=["dining table"],
        notes="family meals",
    )
    result = planner.generate_plan(request)

    assert result.selection_reasons
    assert result.metrics is not None
    assert result.metrics.execution_time_seconds >= 0
    assert result.metrics.catalog_search_time_seconds >= 0
    assert result.metrics.layout_validation_time_seconds >= 0
    assert result.metrics.selected_item_count == len(result.selected_items)


def test_execution_metrics_are_included(planner):
    request = PlannerRequest(
        room_type="Bedroom",
        style="Minimalist",
        budget=180_000,
        room_width_cm=420,
        room_depth_cm=360,
        must_haves=["bed", "wardrobe"],
    )
    result = planner.generate_plan(request)

    metrics = result.metrics
    assert metrics.execution_time_seconds > 0
    assert metrics.catalog_search_time_seconds >= 0
    assert metrics.budget_calculation_time_seconds >= 0
    assert metrics.layout_validation_time_seconds >= 0
    assert metrics.selected_item_count == len(result.selected_items)
    assert metrics.rejected_item_count == len(result.rejected_items)
