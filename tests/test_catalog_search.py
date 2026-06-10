import logging

import pytest

from tools.catalog_search import (
    get_eligible_items,
    search_by_category,
    search_by_room_and_style,
    search_by_room_type,
    search_by_style,
)
from utils.db import DatabaseConnection

logger = logging.getLogger(__name__)


def test_search_by_room_type_returns_living_room_items():
    db = DatabaseConnection()
    results = search_by_room_type(db, room_type="Living Room")

    assert results, "Expected at least one Living Room result"
    assert all(item.matches_room_type("Living Room") for item in results)
    assert all(item.has_complete_dimensions() for item in results)
    db.close()


def test_search_by_style_returns_style_matches():
    db = DatabaseConnection()
    results = search_by_style(db, style="Scandinavian")

    assert results, "Expected at least one Scandinavian result"
    assert all(item.matches_style("Scandinavian") for item in results)
    assert all(item.has_complete_dimensions() for item in results)
    db.close()


def test_search_by_category_returns_matching_category():
    db = DatabaseConnection()
    results = search_by_category(db, category="Coffee Table")

    assert results, "Expected Coffee Table results"
    assert all(item.category.lower() == "coffee table" for item in results)
    assert all(item.has_complete_dimensions() for item in results)
    db.close()


def test_search_by_room_and_style_returns_filtered_items():
    db = DatabaseConnection()
    results = search_by_room_and_style(db, room_type="Living Room", style="Scandinavian")

    assert results, "Expected Living Room + Scandinavian results"
    assert all(item.matches_room_type("Living Room") for item in results)
    assert all(item.matches_style("Scandinavian") for item in results)
    assert all(item.has_complete_dimensions() for item in results)
    db.close()


def test_priority_boost_changes_ranking():
    db = DatabaseConnection()
    base_results = search_by_category(db, category="Sofa")
    assert base_results, "Expected some sofas in the catalog"

    boosted_results = get_eligible_items(
        db,
        category="Sofa",
        priority_boosts={"SOF-001": 10.0},
    )

    assert boosted_results, "Expected some ranked sofa results"
    assert boosted_results[0].item_id == "SOF-001"
    db.close()


def test_logging_reports_candidate_and_filter_counts(caplog):
    db = DatabaseConnection()
    caplog.set_level(logging.INFO)

    search_by_room_type(db, room_type="Living Room")

    assert any("Catalog search candidates=" in record.message for record in caplog.records)
    assert any("filtered_missing_dimensions=" in record.message for record in caplog.records)
    db.close()
