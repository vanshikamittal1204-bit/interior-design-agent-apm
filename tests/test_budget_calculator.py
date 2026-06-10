"""Unit tests for the budget calculator tool."""

import logging

import pytest

from tools.budget_calculator import (
    BudgetResult,
    BudgetStatus,
    budget_status,
    budget_utilization,
    calculate_total_cost,
    remaining_budget,
)
from utils.db import CatalogItem, DatabaseConnection


@pytest.fixture
def db():
    """Provide a database connection for tests."""
    return DatabaseConnection()


@pytest.fixture
def sample_items(db):
    """Load sample items from database for testing."""
    all_items = db.get_all_items()
    return all_items[:5]  # Use first 5 items


@pytest.fixture
def living_room_items(db):
    """Load Living Room items for budget testing."""
    return db.get_items_by_room_type("Living Room")


class TestCalculateTotalCost:
    """Tests for calculate_total_cost()."""

    def test_calculate_total_cost_single_item(self, sample_items):
        """Test cost calculation for single item."""
        item = sample_items[0]
        total = calculate_total_cost([item])
        assert total == item.price_inr

    def test_calculate_total_cost_multiple_items(self, sample_items):
        """Test cost calculation for multiple items."""
        items = sample_items[:3]
        total = calculate_total_cost(items)
        expected = sum(item.price_inr for item in items)
        assert total == expected

    def test_calculate_total_cost_empty_list(self):
        """Test cost calculation for empty item list."""
        total = calculate_total_cost([])
        assert total == 0

    def test_calculate_total_cost_raises_on_missing_price(self):
        """Test that missing price raises ValueError."""
        item = CatalogItem(
            item_id="TEST-001",
            category="Test",
            name="Test Item",
            price_inr=None,  # Missing price
            in_stock=1,
        )
        with pytest.raises(ValueError, match="missing price"):
            calculate_total_cost([item])


class TestRemainingBudget:
    """Tests for remaining_budget()."""

    def test_remaining_budget_within_budget(self, sample_items):
        """Test remaining budget when within budget."""
        budget = 1_000_000
        items = sample_items[:2]
        remaining = remaining_budget(budget, items)
        expected = budget - sum(item.price_inr for item in items)
        assert remaining == expected
        assert remaining > 0

    def test_remaining_budget_exact_fit(self, sample_items):
        """Test remaining budget when spend exactly equals budget."""
        items = sample_items[:1]
        budget = items[0].price_inr
        remaining = remaining_budget(budget, items)
        assert remaining == 0

    def test_remaining_budget_exceeded(self, sample_items):
        """Test remaining budget when budget is exceeded."""
        budget = 1000  # Very low budget
        items = sample_items[:3]
        remaining = remaining_budget(budget, items)
        assert remaining < 0

    def test_remaining_budget_empty_selection(self):
        """Test remaining budget with no items selected."""
        budget = 100_000
        remaining = remaining_budget(budget, [])
        assert remaining == budget


class TestBudgetUtilization:
    """Tests for budget_utilization()."""

    def test_budget_utilization_50_percent(self, db):
        """Test utilization calculation at 50%."""
        items = db.get_all_items()[:2]
        budget = sum(item.price_inr for item in items) * 2  # Double the spend
        utilization = budget_utilization(budget, items)
        assert pytest.approx(utilization, rel=1e-2) == 50.0

    def test_budget_utilization_100_percent(self, db):
        """Test utilization calculation at 100%."""
        items = db.get_all_items()[:2]
        budget = sum(item.price_inr for item in items)
        utilization = budget_utilization(budget, items)
        assert pytest.approx(utilization, rel=1e-2) == 100.0

    def test_budget_utilization_over_100_percent(self, sample_items):
        """Test utilization > 100% when budget exceeded."""
        budget = 1000  # Very low budget
        items = sample_items[:2]
        utilization = budget_utilization(budget, items)
        assert utilization > 100.0

    def test_budget_utilization_zero_budget_raises(self):
        """Test that zero budget raises ValueError."""
        with pytest.raises(ValueError, match="Budget must be positive"):
            budget_utilization(0, [])

    def test_budget_utilization_negative_budget_raises(self):
        """Test that negative budget raises ValueError."""
        with pytest.raises(ValueError, match="Budget must be positive"):
            budget_utilization(-100, [])


class TestBudgetStatus:
    """Tests for budget_status()."""

    def test_budget_status_within_budget(self, db):
        """Test status when within budget."""
        items = db.get_items_by_room_type("Living Room")[:2]
        budget = sum(item.price_inr for item in items) + 50_000
        result = budget_status(budget, items)

        assert result.status == BudgetStatus.WITHIN_BUDGET
        assert result.is_within_budget()
        assert result.overflow_inr == 0
        assert result.utilization_percent < 100.0

    def test_budget_status_exceeded(self, sample_items):
        """Test status when budget exceeded."""
        budget = 1000  # Very low budget
        items = sample_items[:2]
        result = budget_status(budget, items)

        assert result.status == BudgetStatus.EXCEEDED
        assert not result.is_within_budget()
        assert result.overflow_inr > 0
        assert result.utilization_percent > 100.0

    def test_budget_status_too_low(self, db):
        """Test status when budget is too low (<10% utilization)."""
        items = db.get_items_by_room_type("Living Room")[:1]
        budget = sum(item.price_inr for item in items) * 50  # 50x budget (2% util)
        result = budget_status(budget, items)

        assert result.status == BudgetStatus.TOO_LOW
        assert result.utilization_percent < 10.0

    def test_budget_status_unused_empty_selection(self):
        """Test status when no items selected."""
        budget = 100_000
        result = budget_status(budget, [])

        assert result.status == BudgetStatus.UNUSED
        assert result.item_count == 0
        assert result.total_spend_inr == 0

    def test_budget_status_exact_fit(self, sample_items):
        """Test status when spend exactly equals budget."""
        items = sample_items[:1]
        budget = items[0].price_inr
        result = budget_status(budget, items)

        assert result.is_within_budget()
        assert result.remaining_budget_inr == 0
        assert result.overflow_inr == 0
        assert pytest.approx(result.utilization_percent, rel=1e-2) == 100.0


class TestBudgetResult:
    """Tests for BudgetResult class."""

    def test_budget_result_properties(self):
        """Test all BudgetResult properties."""
        result = BudgetResult(
            total_budget_inr=100_000,
            total_spend_inr=60_000,
            item_count=5,
        )

        assert result.remaining_budget_inr == 40_000
        assert result.overflow_inr == 0
        assert pytest.approx(result.utilization_percent, rel=1e-2) == 60.0
        assert result.status == BudgetStatus.WITHIN_BUDGET
        assert result.is_within_budget()

    def test_budget_result_overflow_property(self):
        """Test overflow property calculation."""
        result = BudgetResult(
            total_budget_inr=50_000,
            total_spend_inr=75_000,
            item_count=3,
        )

        assert result.remaining_budget_inr == -25_000
        assert result.overflow_inr == 25_000
        assert not result.is_within_budget()

    def test_budget_result_repr(self):
        """Test string representation."""
        result = BudgetResult(
            total_budget_inr=100_000,
            total_spend_inr=80_000,
            item_count=4,
        )

        repr_str = repr(result)
        assert "100000" in repr_str
        assert "80000" in repr_str
        assert "80.0" in repr_str


class TestBudgetCalculationIntegration:
    """Integration tests for budget calculations."""

    def test_real_world_living_room_budget(self, db):
        """Test with real Living Room items and budget."""
        items = db.get_items_by_room_type("Living Room")[:4]
        budget = 200_000

        # Calculate using all functions
        total_cost = calculate_total_cost(items)
        remaining = remaining_budget(budget, items)
        utilization = budget_utilization(budget, items)
        result = budget_status(budget, items)

        # Verify consistency
        assert total_cost == result.total_spend_inr
        assert remaining == result.remaining_budget_inr
        assert pytest.approx(utilization, rel=1e-2) == result.utilization_percent

    def test_multiple_scenarios_with_same_items(self, db):
        """Test same items with different budgets."""
        items = db.get_all_items()[:3]
        total_cost = sum(item.price_inr for item in items)

        # Scenario 1: Comfortable budget
        result1 = budget_status(total_cost * 2, items)
        assert result1.status == BudgetStatus.WITHIN_BUDGET

        # Scenario 2: Tight budget
        result2 = budget_status(total_cost, items)
        assert result2.is_within_budget()
        assert result2.overflow_inr == 0

        # Scenario 3: Exceeded budget
        result3 = budget_status(total_cost // 2, items)
        assert result3.status == BudgetStatus.EXCEEDED

    def test_logging_output(self, caplog, db):
        """Test that logging produces expected output."""
        items = db.get_all_items()[:2]
        budget = 250_000

        caplog.set_level(logging.INFO)
        budget_status(budget, items)

        assert any("budget_status" in record.message for record in caplog.records)
        assert any("budget=" in record.message for record in caplog.records)
        assert any("spend=" in record.message for record in caplog.records)
        assert any("status=" in record.message for record in caplog.records)


class TestEdgeCases:
    """Edge case tests."""

    def test_single_expensive_item_under_budget(self, db):
        """Test single expensive item that still fits."""
        all_items = db.get_all_items()
        expensive_item = max(all_items, key=lambda x: x.price_inr)
        budget = expensive_item.price_inr + 10_000

        result = budget_status(budget, [expensive_item])
        assert result.is_within_budget()

    def test_many_cheap_items_stay_under_budget(self, db):
        """Test that many cheap items can stay under budget."""
        all_items = db.get_all_items()
        cheap_items = sorted(all_items, key=lambda x: x.price_inr)[:10]
        budget = sum(item.price_inr for item in cheap_items) + 1000

        result = budget_status(budget, cheap_items)
        assert result.is_within_budget()

    def test_large_budget_low_utilization(self, db):
        """Test very large budget with minimal spend."""
        items = db.get_all_items()[:1]
        budget = 10_000_000  # Very large budget

        result = budget_status(budget, items)
        assert result.utilization_percent < 1.0
        assert result.status == BudgetStatus.TOO_LOW
