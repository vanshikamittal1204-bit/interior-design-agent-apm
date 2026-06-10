"""Budget calculator for interior design planning.

This module provides:
1. Budget tracking and calculation
2. Overflow/underflow detection
3. Budget status classification
4. Structured logging for audit trail
"""

import logging
from enum import Enum
from typing import List, Optional

from utils.db import CatalogItem

logger = logging.getLogger(__name__)


class BudgetStatus(str, Enum):
    """Categorical budget status."""
    WITHIN_BUDGET = "within_budget"
    EXCEEDED = "exceeded"
    TOO_LOW = "too_low"
    UNUSED = "unused"


class BudgetResult:
    """Result object for budget calculations.
    
    Attributes:
        total_budget_inr: Total budget in Indian Rupees
        total_spend_inr: Sum of all selected item prices
        remaining_budget_inr: Difference (budget - spend)
        utilization_percent: Percentage of budget used (0-100 or >100 if exceeded)
        overflow_inr: Positive if exceeded, 0 if within budget
        status: Categorical status (within_budget, exceeded, too_low, unused)
        item_count: Number of selected items
    """

    def __init__(
        self,
        total_budget_inr: int,
        total_spend_inr: int,
        item_count: int = 0,
    ):
        """Initialize budget result.

        Args:
            total_budget_inr: Total available budget
            total_spend_inr: Total cost of selected items
            item_count: Number of items selected
        """
        self.total_budget_inr = total_budget_inr
        self.total_spend_inr = total_spend_inr
        self.item_count = item_count

    @property
    def remaining_budget_inr(self) -> int:
        """Calculate remaining budget after spend."""
        return self.total_budget_inr - self.total_spend_inr

    @property
    def overflow_inr(self) -> int:
        """Calculate overflow amount (0 if within budget, >0 if exceeded)."""
        return max(0, self.total_spend_inr - self.total_budget_inr)

    @property
    def utilization_percent(self) -> float:
        """Calculate budget utilization percentage (0-100+ if exceeded)."""
        if self.total_budget_inr <= 0:
            return 0.0
        return (self.total_spend_inr / self.total_budget_inr) * 100.0

    @property
    def status(self) -> BudgetStatus:
        """Determine budget status based on spend vs budget."""
        if self.item_count == 0:
            return BudgetStatus.UNUSED

        if self.total_spend_inr > self.total_budget_inr:
            return BudgetStatus.EXCEEDED

        # Threshold: if utilization < 10%, budget is too low
        if self.utilization_percent < 10.0:
            return BudgetStatus.TOO_LOW

        return BudgetStatus.WITHIN_BUDGET

    def is_within_budget(self) -> bool:
        """Check if selection is within budget."""
        return self.total_spend_inr <= self.total_budget_inr

    def __repr__(self) -> str:
        return (
            f"BudgetResult(budget={self.total_budget_inr}, "
            f"spend={self.total_spend_inr}, "
            f"remaining={self.remaining_budget_inr}, "
            f"utilization={self.utilization_percent:.1f}%, "
            f"status={self.status.value})"
        )


# ============================================================================
# Budget Calculation Functions
# ============================================================================


def calculate_total_cost(items: List[CatalogItem]) -> int:
    """Calculate total cost of selected items.

    Args:
        items: List of CatalogItem objects to sum

    Returns:
        Total cost in Indian Rupees

    Raises:
        ValueError: If any item is missing price information
    """
    total = 0
    for item in items:
        if not item.has_price():
            raise ValueError(
                f"Item {item.item_id} ({item.name}) is missing price information"
            )
        total += item.price_inr

    logger.debug("calculate_total_cost items=%d total=%d", len(items), total)
    return total


def remaining_budget(
    total_budget_inr: int,
    items: List[CatalogItem],
) -> int:
    """Calculate remaining budget after items are selected.

    Args:
        total_budget_inr: Total available budget
        items: List of selected CatalogItems

    Returns:
        Remaining budget in Indian Rupees (can be negative if exceeded)

    Raises:
        ValueError: If any item is missing price
    """
    total_spend = calculate_total_cost(items)
    remaining = total_budget_inr - total_spend

    logger.debug(
        "remaining_budget budget=%d spend=%d remaining=%d",
        total_budget_inr,
        total_spend,
        remaining,
    )
    return remaining


def budget_utilization(
    total_budget_inr: int,
    items: List[CatalogItem],
) -> float:
    """Calculate budget utilization percentage.

    Args:
        total_budget_inr: Total available budget
        items: List of selected CatalogItems

    Returns:
        Utilization percentage (0.0-100.0+)

    Raises:
        ValueError: If budget is 0 or if any item missing price
    """
    if total_budget_inr <= 0:
        raise ValueError(f"Budget must be positive, got {total_budget_inr}")

    total_spend = calculate_total_cost(items)
    utilization = (total_spend / total_budget_inr) * 100.0

    logger.debug(
        "budget_utilization budget=%d spend=%d utilization=%.2f%%",
        total_budget_inr,
        total_spend,
        utilization,
    )
    return utilization


def budget_status(
    total_budget_inr: int,
    items: List[CatalogItem],
) -> BudgetResult:
    """Calculate complete budget status.

    Args:
        total_budget_inr: Total available budget
        items: List of selected CatalogItems

    Returns:
        BudgetResult object with all calculated values

    Raises:
        ValueError: If budget is 0 or if any item missing price
    """
    if total_budget_inr <= 0:
        raise ValueError(f"Budget must be positive, got {total_budget_inr}")

    total_spend = calculate_total_cost(items)
    result = BudgetResult(
        total_budget_inr=total_budget_inr,
        total_spend_inr=total_spend,
        item_count=len(items),
    )

    logger.info(
        "budget_status budget=%d spend=%d remaining=%d utilization=%.1f%% "
        "overflow=%d status=%s items=%d",
        result.total_budget_inr,
        result.total_spend_inr,
        result.remaining_budget_inr,
        result.utilization_percent,
        result.overflow_inr,
        result.status.value,
        result.item_count,
    )

    return result
