"""Unit tests for the layout validator tool."""

from typing import List, Optional, Tuple

import pytest

from tools.layout_validator import (
    FurniturePlacement,
    LayoutEvaluation,
    LayoutPlanResult,
    ValidationResult,
    ValidationStatus,
    plan_layout,
    validate_layout,
)
from utils.db import CatalogItem, DatabaseConnection


@pytest.fixture
def db() -> DatabaseConnection:
    connection = DatabaseConnection()
    yield connection
    connection.close()


def _find_item_by_category(items: List[CatalogItem], categories: List[str]) -> Optional[CatalogItem]:
    normalized = [category.lower() for category in categories]
    for item in items:
        if item.category.lower() in normalized and item.has_complete_dimensions():
            return item
    return None


def _find_items_by_category(items: List[CatalogItem], categories: List[str], limit: int = 1) -> List[CatalogItem]:
    normalized = [category.lower() for category in categories]
    results: List[CatalogItem] = []
    for item in items:
        if item.category.lower() in normalized and item.has_complete_dimensions():
            results.append(item)
            if len(results) >= limit:
                break
    return results


def test_furniture_fits_room(db: DatabaseConnection):
    items = db.get_items_by_room_type("Living Room")
    sofa = _find_item_by_category(items, ["sofa"])
    tv_unit = _find_item_by_category(items, ["tv unit"])
    coffee = _find_item_by_category(items, ["coffee table"])

    assert sofa and tv_unit and coffee

    result = plan_layout(
        room_type="Living Room",
        room_width_cm=500,
        room_depth_cm=420,
        selected_items=[sofa, tv_unit, coffee],
    )

    assert isinstance(result, LayoutPlanResult)
    assert result.best_layout is not None
    assert result.best_layout.validation.valid
    assert result.best_layout.validation.validation_status == ValidationStatus.VALID


def test_furniture_exceeds_room(db: DatabaseConnection):
    items = db.get_items_by_room_type("Bedroom")
    bed = _find_item_by_category(items, ["bed"])
    assert bed

    result = plan_layout(
        room_type="Bedroom",
        room_width_cm=150,
        room_depth_cm=150,
        selected_items=[bed],
    )

    assert result.best_layout is not None
    assert not result.best_layout.validation.valid
    assert any("does not fit" in reason for reason in result.best_layout.validation.reasons)


def test_occupancy_pass(db: DatabaseConnection):
    items = db.get_items_by_room_type("Dining")
    table = _find_item_by_category(items, ["dining table"])
    chairs = _find_items_by_category(items, ["dining chair"], limit=4)
    assert table and chairs

    result = plan_layout(
        room_type="Dining",
        room_width_cm=450,
        room_depth_cm=420,
        selected_items=[table] + chairs,
    )

    assert result.best_layout is not None
    assert result.best_layout.validation.occupancy_ratio <= 0.65
    assert result.best_layout.validation.valid


def test_occupancy_fail(db: DatabaseConnection):
    items = db.get_items_by_room_type("Living Room")
    sofa = _find_item_by_category(items, ["sofa"])
    tv_unit = _find_item_by_category(items, ["tv unit"])
    coffee = _find_item_by_category(items, ["coffee table"])
    armchair = _find_item_by_category(items, ["armchair"])
    rug = _find_item_by_category(items, ["rug"])

    assert sofa and tv_unit and coffee and armchair and rug

    result = plan_layout(
        room_type="Living Room",
        room_width_cm=280,
        room_depth_cm=300,
        selected_items=[sofa, tv_unit, coffee, armchair, rug],
    )

    assert result.best_layout is not None
    assert result.best_layout.validation.occupancy_ratio > 0.65 or not result.best_layout.validation.valid


def test_overlap_detection():
    placements = [
        FurniturePlacement(item_id="A", item_name="Sofa A", category="Sofa", x=0, y=0, width=150, depth=90),
        FurniturePlacement(item_id="B", item_name="Coffee Table B", category="Coffee Table", x=100, y=50, width=100, depth=60),
    ]
    validation = validate_layout(placements, room_width_cm=400, room_depth_cm=300)

    assert not validation.valid
    assert any("overlaps" in reason for reason in validation.reasons)


def test_circulation_pass():
    placements = [
        FurniturePlacement(item_id="A", item_name="Sofa A", category="Sofa", x=50, y=50, width=150, depth=90),
        FurniturePlacement(item_id="B", item_name="TV Unit B", category="TV Unit", x=50, y=250, width=120, depth=40),
    ]
    validation = validate_layout(placements, room_width_cm=400, room_depth_cm=360)

    assert validation.valid
    assert validation.minimum_clearance_cm >= 75


def test_circulation_fail():
    placements = [
        FurniturePlacement(item_id="A", item_name="Sofa A", category="Sofa", x=50, y=50, width=150, depth=90),
        FurniturePlacement(item_id="B", item_name="Side Table B", category="Side Table", x=170, y=100, width=40, depth=40),
    ]
    validation = validate_layout(placements, room_width_cm=400, room_depth_cm=360)

    assert not validation.valid
    assert any("circulation" in reason for reason in validation.reasons)


def test_best_layout_selection(db: DatabaseConnection):
    items = db.get_items_by_room_type("Study")
    desk = _find_item_by_category(items, ["desk"])
    chair = _find_item_by_category(items, ["office chair", "armchair"])
    bookshelf = _find_item_by_category(items, ["bookshelf"])

    assert desk and chair and bookshelf

    result = plan_layout(
        room_type="Study",
        room_width_cm=420,
        room_depth_cm=360,
        selected_items=[desk, chair, bookshelf],
    )

    assert result.best_layout is not None
    assert result.best_layout.validation.valid
    assert len(result.alternative_layouts) >= 1


def test_alternative_layouts_returned(db: DatabaseConnection):
    items = db.get_items_by_room_type("Living Room")
    sofa = _find_item_by_category(items, ["sofa"])
    tv = _find_item_by_category(items, ["tv unit"])
    coffee = _find_item_by_category(items, ["coffee table"])

    assert sofa and tv and coffee

    result = plan_layout(
        room_type="Living Room",
        room_width_cm=520,
        room_depth_cm=420,
        selected_items=[sofa, tv, coffee],
    )

    assert len(result.alternative_layouts) >= 1
    assert any(isinstance(layout, LayoutEvaluation) for layout in result.alternative_layouts)


def test_single_replan_triggered_and_succeeds(db: DatabaseConnection):
    items = db.get_items_by_room_type("Living Room")
    sofa = _find_item_by_category(items, ["sofa"])
    tv = _find_item_by_category(items, ["tv unit"])
    coffee = _find_item_by_category(items, ["coffee table"])
    rug = _find_item_by_category(items, ["rug"])
    lamp = _find_item_by_category(items, ["floor lamp", "table lamp"])

    assert sofa and tv and coffee and rug and lamp

    result = plan_layout(
        room_type="Living Room",
        room_width_cm=280,
        room_depth_cm=310,
        selected_items=[sofa, tv, coffee, rug, lamp],
    )

    assert result.replan_triggered
    assert len(result.removed_item_ids) == 1
    assert result.best_layout is not None


def test_single_replan_fails(db: DatabaseConnection):
    items = db.get_items_by_room_type("Bedroom")
    bed = _find_item_by_category(items, ["bed"])
    wardrobe = _find_item_by_category(items, ["wardrobe"])
    bedside = _find_item_by_category(items, ["bedside table"])
    rug = _find_item_by_category(items, ["rug"])

    assert bed and wardrobe and bedside and rug

    result = plan_layout(
        room_type="Bedroom",
        room_width_cm=220,
        room_depth_cm=220,
        selected_items=[bed, wardrobe, bedside, rug],
    )

    assert result.replan_triggered
    assert result.best_layout is not None
    assert not result.best_layout.validation.valid


def test_coordinate_generation(db: DatabaseConnection):
    items = db.get_items_by_room_type("Dining")
    table = _find_item_by_category(items, ["dining table"])
    chairs = _find_items_by_category(items, ["dining chair"], limit=4)
    assert table and chairs

    result = plan_layout(
        room_type="Dining",
        room_width_cm=500,
        room_depth_cm=420,
        selected_items=[table] + chairs,
    )

    layout = result.best_layout
    assert layout is not None
    for placement in layout.placements:
        assert isinstance(placement.x, int)
        assert isinstance(placement.y, int)
        assert placement.width > 0
        assert placement.depth > 0


def test_living_room_layout_generation(db: DatabaseConnection):
    items = db.get_items_by_room_type("Living Room")
    sofa = _find_item_by_category(items, ["sofa"])
    tv = _find_item_by_category(items, ["tv unit"])
    assert sofa and tv

    result = plan_layout(
        room_type="Living Room",
        room_width_cm=520,
        room_depth_cm=420,
        selected_items=[sofa, tv],
    )

    assert result.best_layout is not None
    assert "living room" in result.best_layout.layout_type.lower()


def test_bedroom_layout_generation(db: DatabaseConnection):
    items = db.get_items_by_room_type("Bedroom")
    bed = _find_item_by_category(items, ["bed"])
    wardrobe = _find_item_by_category(items, ["wardrobe"])
    assert bed and wardrobe

    result = plan_layout(
        room_type="Bedroom",
        room_width_cm=450,
        room_depth_cm=390,
        selected_items=[bed, wardrobe],
    )

    assert result.best_layout is not None
    assert "bed" in result.best_layout.layout_type.lower()


def test_study_layout_generation(db: DatabaseConnection):
    items = db.get_items_by_room_type("Study")
    desk = _find_item_by_category(items, ["desk"])
    chair = _find_item_by_category(items, ["office chair", "armchair"])
    assert desk and chair

    result = plan_layout(
        room_type="Study",
        room_width_cm=420,
        room_depth_cm=360,
        selected_items=[desk, chair],
    )

    assert result.best_layout is not None
    assert "study" in result.best_layout.layout_type.lower()


def test_dining_room_layout_generation(db: DatabaseConnection):
    items = db.get_items_by_room_type("Dining")
    table = _find_item_by_category(items, ["dining table"])
    chair = _find_item_by_category(items, ["dining chair"])
    assert table and chair

    result = plan_layout(
        room_type="Dining",
        room_width_cm=520,
        room_depth_cm=420,
        selected_items=[table, chair],
    )

    assert result.best_layout is not None
    assert "dining" in result.best_layout.layout_type.lower()
