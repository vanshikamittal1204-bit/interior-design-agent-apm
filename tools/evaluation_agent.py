import logging
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from tools.layout_validator import LayoutPlanResult

logger = logging.getLogger(__name__)


class EvaluationItem(BaseModel):
    item_id: str = Field(..., description="Catalog item identifier")
    category: str = Field(..., description="Item category")
    name: str = Field(..., description="Item display name")
    price_inr: int = Field(..., description="Item price in INR")
    width_cm: Optional[int] = Field(None, description="Item width in cm")
    depth_cm: Optional[int] = Field(None, description="Item depth in cm")
    style_tags: Optional[List[str]] = Field(None, description="Optional style tags")
    room_types: Optional[List[str]] = Field(None, description="Applicable room types")


class EvaluationRejectedItem(BaseModel):
    item_name: str = Field(..., description="Rejected item name")
    reason: str = Field(..., description="Reason the item was rejected")


class EvaluationRequest(BaseModel):
    selected_items: List[EvaluationItem] = Field(default_factory=list)
    optional_additions: List[EvaluationItem] = Field(default_factory=list)
    rejected_items: List[EvaluationRejectedItem] = Field(default_factory=list)
    layout_plan: Optional[LayoutPlanResult] = Field(None)
    room_type: str = Field(...)
    room_width_cm: int = Field(...)
    room_depth_cm: int = Field(...)
    budget_inr: int = Field(...)
    style_preference: Optional[str] = Field(None)
    must_haves: List[str] = Field(default_factory=list)
    notes: Optional[str] = Field(None)


class EvaluationResult(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    confidence_level: int = Field(..., ge=0, le=100)
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    reasoning: List[str] = Field(default_factory=list)
    score_breakdown: Dict[str, int] = Field(default_factory=dict)


FUNCTIONAL_REQUIREMENTS: Dict[str, List[str]] = {
    "living room": ["sofa", "coffee table", "tv unit"],
    "bedroom": ["bed", "wardrobe"],
    "study": ["desk", "chair"],
    "dining room": ["dining table"],
}

WEIGHTS: Dict[str, int] = {
    "must_have_coverage": 20,
    "budget_utilization": 20,
    "layout_validity": 20,
    "circulation_quality": 15,
    "functional_completeness": 15,
    "style_consistency": 10,
}


def _normalize_text(value: Optional[str]) -> str:
    return value.strip().lower() if value else ""


def _extract_categories(items: List[EvaluationItem]) -> Set[str]:
    return {item.category.strip().lower() for item in items if item.category}


def _extract_item_texts(items: List[EvaluationItem]) -> List[str]:
    values: List[str] = []
    for item in items:
        values.append(item.category or "")
        values.append(item.name or "")
    return [value.lower() for value in values if value]


def _compile_style_tokens(item: EvaluationItem) -> Set[str]:
    tokens: Set[str] = set()
    if item.style_tags:
        tokens.update(_normalize_text(tag) for tag in item.style_tags if tag)
    tokens.update(token for token in item.name.lower().split() if token)
    tokens.update(token for token in item.category.lower().split() if token)
    return tokens


def _score_missing_items(request: EvaluationRequest) -> Tuple[int, List[str], List[str]]:
    must_haves = [entry for entry in (request.must_haves or []) if entry.strip()]
    if not must_haves:
        return 100, ["No must-haves were specified."], []

    categories = _extract_categories(request.selected_items + request.optional_additions)
    reasons: List[str] = []
    pros: List[str] = []
    matched_count = 0
    for required in must_haves:
        normalized_required = _normalize_text(required)
        if any(normalized_required in category for category in categories):
            matched_count += 1
        else:
            reasons.append(f"Missing must-have item or category: '{required}'")

    score = round((matched_count / len(must_haves)) * 100)
    if score == 100:
        pros.append("All required must-haves are included.")
    else:
        pros.append(f"{matched_count}/{len(must_haves)} must-haves satisfied.")
    return score, pros, reasons


def _score_budget_utilization(request: EvaluationRequest) -> Tuple[int, List[str], List[str]]:
    total_spend = sum(item.price_inr for item in request.selected_items + request.optional_additions)
    reasons: List[str] = []
    pros: List[str] = []

    if total_spend <= 0:
        reasons.append("No budget was spent on selected items.")
        return 0, pros, reasons

    if total_spend > request.budget_inr:
        overflow = total_spend - request.budget_inr
        reasons.append(f"Plan exceeds budget by INR {overflow}.")
        return 0, pros, reasons

    utilization = (total_spend / request.budget_inr) * 100.0
    if utilization >= 90:
        score = 100
        pros.append("Budget is efficiently utilized.")
    elif utilization >= 70:
        score = 85
        pros.append("Budget utilization is strong.")
    elif utilization >= 40:
        score = 65
        reasons.append("Budget utilization is moderate; some budget remains unused.")
    else:
        score = 40
        reasons.append("Budget utilization is low; the plan underuses available budget.")

    if request.budget_inr - total_spend >= 0:
        pros.append(f"Remaining budget is INR {request.budget_inr - total_spend}.")
    return score, pros, reasons


def _score_layout_validity(request: EvaluationRequest) -> Tuple[int, List[str], List[str]]:
    if not request.layout_plan or not request.layout_plan.best_layout:
        return 0, [], ["No layout was provided for validation."]
    if request.layout_plan.best_layout.validation.valid:
        return 100, ["Layout passed hard validation."], []
    reasons = list(request.layout_plan.best_layout.validation.reasons)
    return 0, [], reasons or ["Layout did not pass validation."]


def _score_circulation_quality(request: EvaluationRequest) -> Tuple[int, List[str], List[str]]:
    if not request.layout_plan or not request.layout_plan.best_layout:
        return 0, [], ["Layout details are unavailable for circulation scoring."]

    validation = request.layout_plan.best_layout.validation
    if not validation.valid:
        return 0, [], ["Circulation cannot be scored for an invalid layout."]

    normalized = min(100, round((validation.circulation_score / 30.0) * 100))
    pros: List[str] = []
    reasons: List[str] = []
    if validation.minimum_clearance_cm >= 90:
        pros.append("Layout circulation exceeds minimum clearance expectations.")
    else:
        pros.append("Layout provides adequate circulation.")
        if validation.minimum_clearance_cm < 90:
            reasons.append(
                f"Minimum clearance is {validation.minimum_clearance_cm:.1f}cm, which is acceptable but not generous."
            )
    return normalized, pros, reasons


def _score_functional_completeness(request: EvaluationRequest) -> Tuple[int, List[str], List[str]]:
    room = _normalize_text(request.room_type)
    requirements = FUNCTIONAL_REQUIREMENTS.get(room, [])
    if not requirements:
        return 100, ["No standard functional checklist exists for this room type."], []

    categories = _extract_categories(request.selected_items)
    matched = 0
    missing: List[str] = []
    for requirement in requirements:
        if any(requirement in category for category in categories):
            matched += 1
        else:
            missing.append(requirement)
    score = round((matched / len(requirements)) * 100)
    pros: List[str] = []
    reasons: List[str] = []
    if matched == len(requirements):
        pros.append("All primary functional requirements are met.")
    else:
        reasons.append(f"Missing functional item categories: {', '.join(missing)}.")
    return score, pros, reasons


def _score_style_consistency(request: EvaluationRequest) -> Tuple[int, List[str], List[str]]:
    if not request.style_preference:
        return 100, ["No style preference was specified."], []

    target = _normalize_text(request.style_preference)
    if not target:
        return 100, ["Style preference is empty."], []

    items = request.selected_items + request.optional_additions
    if not items:
        return 50, [], ["No selected items are available for style consistency scoring."]

    matched_items = 0
    for item in items:
        style_tokens = _compile_style_tokens(item)
        if any(target in token for token in style_tokens):
            matched_items += 1

    if matched_items == 0:
        return 40, [], [f"None of the selected items contain the style keyword '{target}'."]

    score = min(100, round((matched_items / len(items)) * 100))
    return (
        score,
        [f"{matched_items}/{len(items)} selected items match the style preference '{request.style_preference}'."],
        [],
    )


def _confidence_level(request: EvaluationRequest, score_breakdown: Dict[str, int]) -> int:
    evidence = 40
    if request.layout_plan and request.layout_plan.best_layout:
        evidence += 20
    if request.selected_items:
        evidence += 20
    if request.budget_inr > 0:
        evidence += 10
    if request.must_haves:
        evidence += 10
    if request.style_preference:
        evidence += 10
    if request.notes:
        evidence += 10
    return min(100, evidence)


def evaluate_plan(request: EvaluationRequest) -> EvaluationResult:
    results: Dict[str, int] = {}
    pros: List[str] = []
    cons: List[str] = []
    reasoning: List[str] = []

    must_score, must_pros, must_cons = _score_missing_items(request)
    budget_score, budget_pros, budget_cons = _score_budget_utilization(request)
    layout_score, layout_pros, layout_cons = _score_layout_validity(request)
    circulation_score, circulation_pros, circulation_cons = _score_circulation_quality(request)
    functional_score, functional_pros, functional_cons = _score_functional_completeness(request)
    style_score, style_pros, style_cons = _score_style_consistency(request)

    results["must_have_coverage"] = must_score
    results["budget_utilization"] = budget_score
    results["layout_validity"] = layout_score
    results["circulation_quality"] = circulation_score
    results["functional_completeness"] = functional_score
    results["style_consistency"] = style_score

    for label, value in results.items():
        weight = WEIGHTS[label]
        reasoning.append(f"{label.replace('_', ' ').capitalize()}: {value}/100 (weight {weight}).")

    for group in (must_pros, budget_pros, layout_pros, circulation_pros, functional_pros, style_pros):
        pros.extend(group)
    for group in (must_cons, budget_cons, layout_cons, circulation_cons, functional_cons, style_cons):
        cons.extend(group)

    total_weight = sum(WEIGHTS.values())
    overall_score = round(
        sum(results[key] * WEIGHTS[key] for key in results) / total_weight
    )
    confidence = _confidence_level(request, results)

    if not pros:
        pros.append("Evaluation completed with no identified strengths.")
    if not cons:
        cons.append("No major weaknesses detected.")

    return EvaluationResult(
        overall_score=overall_score,
        confidence_level=confidence,
        pros=pros,
        cons=cons,
        reasoning=reasoning,
        score_breakdown={k: results[k] for k in results},
    )
