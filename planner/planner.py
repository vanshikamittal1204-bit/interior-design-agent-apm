import logging
import time
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from tools.budget_calculator import calculate_total_cost, remaining_budget
from tools.catalog_search import search_by_room_and_style
from tools.layout_validator import LayoutPlanResult, plan_layout
from utils.db import CatalogItem, DatabaseConnection

logger = logging.getLogger(__name__)


class PlannerRequest(BaseModel):
    room_type: str = Field(..., description="Target room type")
    style: str = Field(..., description="Preferred design style")
    budget: int = Field(..., description="Available budget in INR")
    room_width_cm: int = Field(..., description="Room width in cm")
    room_depth_cm: int = Field(..., description="Room depth in cm")
    must_haves: List[str] = Field(default_factory=list, description="Must-have items or categories")
    notes: Optional[str] = Field(None, description="Additional room notes or context")

    @field_validator("budget", "room_width_cm", "room_depth_cm", mode="before")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value is None or value <= 0:
            raise ValueError("Value must be positive")
        return value

    @field_validator("must_haves", mode="before")
    @classmethod
    def normalize_must_haves(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [entry.strip() for entry in value if entry and entry.strip()]


class ItemSummary(BaseModel):
    item_id: str
    category: str
    name: str
    price_inr: int


class RejectedItem(BaseModel):
    item_name: str
    reason: str


class ExecutionMetrics(BaseModel):
    execution_time_seconds: float
    catalog_search_time_seconds: float
    budget_calculation_time_seconds: float
    layout_validation_time_seconds: float
    selected_item_count: int
    rejected_item_count: int
    total_cost: int
    remaining_budget: int
    replan_count: int


class PlannerResult(BaseModel):
    selected_items: List[ItemSummary] = Field(default_factory=list)
    optional_additions: List[ItemSummary] = Field(default_factory=list)
    rejected_items: List[RejectedItem] = Field(default_factory=list)
    total_cost: int = 0
    remaining_budget: int = 0
    layout_passed: bool = False
    replan_count: int = 0
    selection_reasons: List[str] = Field(default_factory=list)
    metrics: ExecutionMetrics
    layout_plan: Optional[LayoutPlanResult] = None


class Planner:
    FUNCTIONAL_REQUIREMENTS: Dict[str, List[str]] = {
        "living room": ["sofa", "coffee table", "tv unit"],
        "bedroom": ["bed", "wardrobe"],
        "study": ["desk", "chair"],
        "dining room": ["dining table"],
    }

    NOTES_PRIORITY_MAP: Dict[str, List[str]] = {
        "reading corner": ["bookshelf", "lamp", "accent chair"],
        "work from home": ["desk", "chair", "bookshelf"],
        "movie night": ["sofa", "tv unit", "coffee table"],
        "cozy": ["rug", "lamp", "accent chair"],
        "entertainment": ["tv unit", "sofa", "coffee table"],
    }

    OPTIONAL_CATEGORIES: List[str] = [
        "lamp",
        "accent chair",
        "bookshelf",
        "artwork",
        "rug",
        "mirror",
        "planter",
        "wall art",
        "side table",
        "console",
    ]

    def __init__(self, db: Optional[DatabaseConnection] = None):
        self.db = db or DatabaseConnection()

    def generate_plan(self, request: PlannerRequest) -> PlannerResult:
        start_time = time.perf_counter()
        catalog_start = time.perf_counter()
        priority_boosts = self._build_priority_boosts(request)
        eligible_items = search_by_room_and_style(
            self.db,
            room_type=request.room_type,
            style=request.style,
            must_haves=request.must_haves,
            priority_boosts=priority_boosts,
        )
        catalog_search_time = time.perf_counter() - catalog_start

        selected_items: List[CatalogItem] = []
        rejected_items: List[RejectedItem] = []
        selection_reasons: List[str] = []
        must_have_item_ids: set = set()

        current_budget = request.budget
        selected_items, rejected_items, current_budget, reasons, mh_ids = self._select_must_haves(
            eligible_items,
            request.must_haves,
            current_budget,
        )
        must_have_item_ids.update(mh_ids)
        selection_reasons.extend(reasons)

        selected_items, rejected_items, current_budget, reasons = self._complete_functional_plan(
            eligible_items,
            selected_items,
            current_budget,
            request.room_type,
        )
        selection_reasons.extend(reasons)

        optional_additions, optional_reasons = self._recommend_optional_additions(
            eligible_items,
            selected_items,
            current_budget,
            request.notes,
        )
        selection_reasons.extend(optional_reasons)
        rejected_items.extend([])

        layout_start = time.perf_counter()
        layout_plan = plan_layout(
            request.room_type,
            request.room_width_cm,
            request.room_depth_cm,
            selected_items,
            user_constraints=self._build_user_constraints(request),
        )
        layout_validation_time = time.perf_counter() - layout_start

        if layout_plan.removed_item_ids:
            removed_ids = set(layout_plan.removed_item_ids)
            removed_items = [item for item in selected_items if item.item_id in removed_ids]
            removable_items = [item for item in removed_items if item.item_id not in must_have_item_ids]
            selected_items = [item for item in selected_items if item.item_id not in {r.item_id for r in removable_items}]
            for removed in removable_items:
                rejected_items.append(
                    RejectedItem(
                        item_name=removed.name,
                        reason="layout fit failure",
                    )
                )
                selection_reasons.append(
                    f"Removed {removed.name} during layout replan to improve fit."
                )

        total_cost = calculate_total_cost(selected_items)
        budget_start = time.perf_counter()
        remaining = remaining_budget(request.budget, selected_items)
        budget_calculation_time = time.perf_counter() - budget_start

        replan_count = 1 if layout_plan.replan_triggered else 0
        layout_passed = bool(layout_plan.best_layout and layout_plan.best_layout.validation.valid)

        metrics = ExecutionMetrics(
            execution_time_seconds=time.perf_counter() - start_time,
            catalog_search_time_seconds=catalog_search_time,
            budget_calculation_time_seconds=budget_calculation_time,
            layout_validation_time_seconds=layout_validation_time,
            selected_item_count=len(selected_items),
            rejected_item_count=len(rejected_items),
            total_cost=total_cost,
            remaining_budget=remaining,
            replan_count=replan_count,
        )

        logger.info(
            "planner_summary room=%s style=%s budget=%d selected=%d rejected=%d "
            "cost=%d remaining=%d layout_valid=%s replan=%d",
            request.room_type,
            request.style,
            request.budget,
            len(selected_items),
            len(rejected_items),
            total_cost,
            remaining,
            layout_passed,
            replan_count,
        )

        return PlannerResult(
            selected_items=[self._summarize_item(item) for item in selected_items],
            optional_additions=[self._summarize_item(item) for item in optional_additions],
            rejected_items=rejected_items,
            total_cost=total_cost,
            remaining_budget=remaining,
            layout_passed=layout_passed,
            replan_count=replan_count,
            selection_reasons=selection_reasons,
            metrics=metrics,
            layout_plan=layout_plan,
        )

    def _build_user_constraints(self, request: PlannerRequest) -> List[str]:
        constraints: List[str] = []
        if request.notes:
            constraints.append(request.notes)
        constraints.extend(request.must_haves)
        return constraints

    def _build_priority_boosts(self, request: PlannerRequest) -> Dict[str, float]:
        boosts: Dict[str, float] = {}
        normalized_room = request.room_type.strip().lower()
        base_map = self._room_priority_map(normalized_room)
        for category, score in base_map.items():
            boosts[category] = float(score)

        for keyword, boosted_categories in self.NOTES_PRIORITY_MAP.items():
            if keyword in (request.notes or "").lower():
                for category in boosted_categories:
                    boosts[category] = boosts.get(category, 0.0) + 20.0
        return boosts

    def _select_must_haves(
        self,
        eligible_items: List[CatalogItem],
        must_haves: List[str],
        budget_inr: int,
    ) -> Tuple[List[CatalogItem], List[RejectedItem], int, List[str], set]:
        selected: List[CatalogItem] = []
        rejected: List[RejectedItem] = []
        reasons: List[str] = []
        must_have_ids: set = set()

        index_map = {item.item_id: i for i, item in enumerate(eligible_items)}
        for term in must_haves:
            normalized_term = term.strip().lower()
            candidates = [
                item
                for item in eligible_items
                if item.item_id not in {selected_item.item_id for selected_item in selected}
                and self._matches_term(item, normalized_term)
            ]
            if not candidates:
                rejected.append(
                    RejectedItem(item_name=term, reason="catalog unavailable")
                )
                reasons.append(f"Must-have '{term}' was unavailable in the catalog.")
                continue

            candidates.sort(key=lambda item: (item.price_inr, index_map[item.item_id]))
            chosen = None
            for candidate in candidates:
                if candidate.price_inr <= budget_inr:
                    chosen = candidate
                    break
            if chosen is None:
                rejected.append(
                    RejectedItem(item_name=term, reason="budget exceeded")
                )
                reasons.append(
                    f"Must-have '{term}' could not be selected within budget."
                )
                continue

            selected.append(chosen)
            must_have_ids.add(chosen.item_id)
            budget_inr -= chosen.price_inr
            reasons.append(f"Selected must-have '{chosen.name}'.")

        return selected, rejected, budget_inr, reasons, must_have_ids

    def _complete_functional_plan(
        self,
        eligible_items: List[CatalogItem],
        selected_items: List[CatalogItem],
        budget_inr: int,
        room_type: str,
    ) -> Tuple[List[CatalogItem], List[RejectedItem], int, List[str]]:
        rejected: List[RejectedItem] = []
        reasons: List[str] = []
        normalized_room = room_type.strip().lower()
        requirements = self.FUNCTIONAL_REQUIREMENTS.get(normalized_room, [])
        selected_item_ids = {item.item_id for item in selected_items}

        for requirement in requirements:
            if self._requirement_satisfied(requirement, selected_items):
                continue
            candidates = [
                item
                for item in eligible_items
                if item.item_id not in selected_item_ids
                and self._category_matches(item, requirement)
            ]
            if not candidates:
                rejected.append(
                    RejectedItem(item_name=requirement, reason="catalog unavailable")
                )
                reasons.append(
                    f"Functional requirement '{requirement}' is unavailable in catalog."
                )
                continue
            chosen = next((item for item in candidates if item.price_inr <= budget_inr), None)
            if chosen is None:
                rejected.append(
                    RejectedItem(item_name=requirement, reason="budget exceeded")
                )
                reasons.append(
                    f"Could not satisfy '{requirement}' before exceeding budget."
                )
                continue

            selected_items.append(chosen)
            selected_item_ids.add(chosen.item_id)
            budget_inr -= chosen.price_inr
            reasons.append(f"Added '{chosen.name}' to satisfy {requirement} requirement.")

        return selected_items, rejected, budget_inr, reasons

    def _recommend_optional_additions(
        self,
        eligible_items: List[CatalogItem],
        selected_items: List[CatalogItem],
        budget_inr: int,
        notes: Optional[str],
    ) -> Tuple[List[CatalogItem], List[str]]:
        if budget_inr <= 0:
            return [], []

        selected_ids = {item.item_id for item in selected_items}
        notes_lower = (notes or "").lower()
        optional_candidates = [
            item
            for item in eligible_items
            if item.item_id not in selected_ids
            and item.price_inr <= budget_inr
            and self._is_optional_category(item)
        ]

        if not optional_candidates:
            return [], []

        boosts = self._notes_priority_boosts(notes_lower)
        optional_candidates.sort(
            key=lambda item: (
                -(boosts.get(item.category.lower(), 0)),
                item.price_inr,
            )
        )

        recommendations: List[CatalogItem] = []
        reasons: List[str] = []
        for item in optional_candidates:
            if len(recommendations) >= 4:
                break
            recommendations.append(item)

        if recommendations:
            reasons.append(
                "Generated optional additions based on remaining budget and room preferences."
            )
        return recommendations, reasons

    def _room_priority_map(self, room_type: str) -> Dict[str, int]:
        room = room_type.strip().lower()
        if room == "living room":
            return {"sofa": 100, "tv unit": 90, "coffee table": 80, "bookshelf": 50, "lamp": 30}
        if room == "bedroom":
            return {"bed": 100, "wardrobe": 90, "side table": 70, "dresser": 60, "lamp": 40}
        if room == "study":
            return {"desk": 100, "chair": 90, "bookshelf": 60, "lamp": 40, "side table": 30}
        if room == "dining room":
            return {"dining table": 100, "dining chair": 90, "sideboard": 60, "lamp": 40}
        return {"desk": 100, "chair": 90, "sofa": 80, "table": 70}

    def _notes_priority_boosts(self, notes_lower: str) -> Dict[str, int]:
        boosts: Dict[str, int] = {}
        for keyword, categories in self.NOTES_PRIORITY_MAP.items():
            if keyword in notes_lower:
                for category in categories:
                    boosts[category] = boosts.get(category, 0) + 10
        return boosts

    def _category_matches(self, item: CatalogItem, requirement: str) -> bool:
        requirement_lower = requirement.strip().lower()
        if requirement_lower in item.category.lower():
            return True
        if requirement_lower in (item.name or "").lower():
            return True
        return False

    def _matches_term(self, item: CatalogItem, term: str) -> bool:
        """
        Match a term against an item.
        For single-word terms: check if term is substring of category or name.
        For multi-word terms: check if all words appear in category or name.
        """
        term_lower = term.strip().lower()
        category_lower = item.category.lower() if item.category else ""
        name_lower = (item.name or "").lower()
        
        words = term_lower.split()
        
        if len(words) == 1:
            return term_lower in category_lower or term_lower in name_lower
        else:
            all_in_category = all(word in category_lower for word in words)
            all_in_name = all(word in name_lower for word in words)
            return all_in_category or all_in_name

    def _requirement_satisfied(self, requirement: str, selected_items: List[CatalogItem]) -> bool:
        required = requirement.lower()
        for item in selected_items:
            if required in item.category.lower() or required in (item.name or "").lower():
                return True
        return False

    def _is_optional_category(self, item: CatalogItem) -> bool:
        lowered = item.category.lower()
        return any(optional in lowered for optional in self.OPTIONAL_CATEGORIES)

    def _summarize_item(self, item: CatalogItem) -> ItemSummary:
        return ItemSummary(
            item_id=item.item_id,
            category=item.category,
            name=item.name,
            price_inr=item.price_inr,
        )
