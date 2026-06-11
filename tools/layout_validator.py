"""Layout validation tool for the Interior Design Agent.

This module generates deterministic room layout candidates, validates them
against hard constraints, scores them, and selects the best valid layout.
It returns structured coordinate data suitable for future floorplan rendering.
"""

import logging
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from utils.db import CatalogItem

logger = logging.getLogger(__name__)

MIN_CIRCULATION_CM = 75
MAX_OCCUPANCY_RATIO = 0.65
IDEAL_OCCUPANCY_RATIO = 0.50
CIRCULATION_WEIGHT = 30.0
OCCUPANCY_WEIGHT = 20.0
FUNCTIONAL_WEIGHT = 25.0
CONSTRAINT_WEIGHT = 15.0
SIMPLICITY_WEIGHT = 10.0


class ValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


class FurniturePlacement(BaseModel):
    item_id: str = Field(..., description="Catalog item identifier")
    item_name: str = Field(..., description="Catalog item display name")
    category: str = Field(..., description="Catalog item category")
    x: int = Field(..., description="Top-left corner X coordinate in cm")
    y: int = Field(..., description="Top-left corner Y coordinate in cm")
    width: int = Field(..., description="Item width in cm")
    depth: int = Field(..., description="Item depth in cm")


class ValidationResult(BaseModel):
    valid: bool = Field(..., description="Whether the layout passed hard validation")
    validation_status: ValidationStatus = Field(..., description="Validation state")
    reasons: List[str] = Field(default_factory=list, description="Failure reasons")
    occupancy_ratio: float = Field(..., description="Furniture area / room area")
    circulation_score: float = Field(..., description="Circulation score based on minimum clearance")
    minimum_clearance_cm: float = Field(..., description="Minimum separation distance between furniture items")
    furniture_area_cm2: int = Field(..., description="Total furniture area")
    room_area_cm2: int = Field(..., description="Room area")


class LayoutEvaluation(BaseModel):
    layout_id: str = Field(..., description="Unique layout candidate identifier")
    layout_type: str = Field(..., description="Named layout type")
    placements: List[FurniturePlacement] = Field(..., description="Placed furniture coordinates")
    validation: ValidationResult = Field(..., description="Validation summary")
    layout_score: float = Field(..., description="Composite layout score")
    pros: List[str] = Field(default_factory=list, description="Deterministic pros")
    cons: List[str] = Field(default_factory=list, description="Deterministic cons")


class LayoutPlanResult(BaseModel):
    room_type: str = Field(..., description="Room type for the plan")
    room_width_cm: int = Field(..., description="Room width in cm")
    room_depth_cm: int = Field(..., description="Room depth in cm")
    best_layout: Optional[LayoutEvaluation] = Field(None, description="Highest scoring valid layout")
    alternative_layouts: List[LayoutEvaluation] = Field(default_factory=list, description="All candidate layouts")
    replan_triggered: bool = Field(False, description="Whether a replan cycle occurred")
    removed_item_ids: List[str] = Field(default_factory=list, description="Removed item IDs during replan")
    failure_reasons: List[str] = Field(default_factory=list, description="Reasons no valid layout could be produced")
    all_layouts_generated: int = Field(..., description="Total layouts generated")
    valid_layout_count: int = Field(..., description="Number of valid layouts")


def _normalize_text(value: Optional[str]) -> str:
    return value.strip().lower() if value else ""


def _normalize_tokens(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return []
    return [token.strip().lower() for value in values for token in value.split(",") if token.strip()]


def _room_area(room_width_cm: int, room_depth_cm: int) -> int:
    return room_width_cm * room_depth_cm


def _furniture_area(placements: List[FurniturePlacement]) -> int:
    return sum(item.width * item.depth for item in placements)


def _rectangles_overlap(a: FurniturePlacement, b: FurniturePlacement) -> bool:
    return not (
        a.x + a.width <= b.x
        or b.x + b.width <= a.x
        or a.y + a.depth <= b.y
        or b.y + b.depth <= a.y
    )


def _edge_distance(a: FurniturePlacement, b: FurniturePlacement) -> float:
    dx = max(0, max(b.x - (a.x + a.width), a.x - (b.x + b.width)))
    dy = max(0, max(b.y - (a.y + a.depth), a.y - (b.y + b.depth)))
    if dx == 0:
        return dy
    if dy == 0:
        return dx
    return (dx**2 + dy**2) ** 0.5


def _minimum_clearance(placements: List[FurniturePlacement]) -> float:
    if len(placements) < 2:
        return float("inf")
    min_distance = float("inf")
    for i, item_a in enumerate(placements):
        for item_b in placements[i + 1 :]:
            distance = _edge_distance(item_a, item_b)
            if distance < min_distance:
                min_distance = distance
    return min_distance


def _fits_room(placement: FurniturePlacement, room_width_cm: int, room_depth_cm: int) -> bool:
    return (
        placement.x >= 0
        and placement.y >= 0
        and placement.x + placement.width <= room_width_cm
        and placement.y + placement.depth <= room_depth_cm
    )


def _calculate_occupancy_ratio(placements: List[FurniturePlacement], room_width_cm: int, room_depth_cm: int) -> float:
    room_area = _room_area(room_width_cm, room_depth_cm)
    if room_area <= 0:
        return 0.0
    return _furniture_area(placements) / room_area


def _build_placement(item: CatalogItem, x: int, y: int) -> FurniturePlacement:
    return FurniturePlacement(
        item_id=item.item_id,
        item_name=item.name,
        category=item.category,
        x=max(0, int(x)),
        y=max(0, int(y)),
        width=int(item.width_cm),
        depth=int(item.depth_cm),
    )


def _group_items_by_category(items: List[CatalogItem]) -> Dict[str, List[CatalogItem]]:
    categories: Dict[str, List[CatalogItem]] = {}
    for item in items:
        key = _normalize_text(item.category)
        categories.setdefault(key, []).append(item)
    return categories


def _place_center(item: CatalogItem, room_width_cm: int, room_depth_cm: int) -> FurniturePlacement:
    x = (room_width_cm - item.width_cm) // 2
    y = (room_depth_cm - item.depth_cm) // 2
    return _build_placement(item, x, y)


def _place_against_wall(item: CatalogItem, room_width_cm: int, room_depth_cm: int, wall: str, offset: int = 75) -> FurniturePlacement:
    if wall == "north":
        x = max(offset, (room_width_cm - item.width_cm) // 2)
        y = offset
    elif wall == "south":
        x = max(offset, (room_width_cm - item.width_cm) // 2)
        y = max(offset, room_depth_cm - item.depth_cm - offset)
    elif wall == "west":
        x = offset
        y = max(offset, (room_depth_cm - item.depth_cm) // 2)
    elif wall == "east":
        x = max(offset, room_width_cm - item.width_cm - offset)
        y = max(offset, (room_depth_cm - item.depth_cm) // 2)
    else:
        x = 0
        y = 0
    return _build_placement(item, x, y)


def _place_along_wall(
    items: List[CatalogItem],
    room_width_cm: int,
    room_depth_cm: int,
    wall: str,
    margin: int = 75,
    spacing: int = 75,
) -> List[FurniturePlacement]:
    placements: List[FurniturePlacement] = []
    if not items:
        return placements

    if wall in ("north", "south"):
        total_width = sum(item.width_cm for item in items) + spacing * (len(items) - 1)
        start_x = max(margin, (room_width_cm - total_width) // 2)
        y = margin if wall == "north" else max(margin, room_depth_cm - max(item.depth_cm for item in items) - margin)
        x = start_x
        for item in items:
            placements.append(_build_placement(item, x, y))
            x += item.width_cm + spacing
    else:
        total_depth = sum(item.depth_cm for item in items) + spacing * (len(items) - 1)
        start_y = max(margin, (room_depth_cm - total_depth) // 2)
        x = margin if wall == "west" else max(margin, room_width_cm - max(item.width_cm for item in items) - margin)
        y = start_y
        for item in items:
            placements.append(_build_placement(item, x, y))
            y += item.depth_cm + spacing
    return placements


def _place_items_in_corner(
    items: List[CatalogItem],
    room_width_cm: int,
    room_depth_cm: int,
    corner: str,
    margin: int = 75,
    spacing: int = 75,
) -> List[FurniturePlacement]:
    placements = []
    if not items:
        return placements

    x = margin if corner in ("nw", "sw") else max(margin, room_width_cm - items[0].width_cm - margin)
    y = margin if corner in ("nw", "ne") else max(margin, room_depth_cm - items[0].depth_cm - margin)

    for item in items:
        placements.append(_build_placement(item, x, y))
        if corner in ("nw", "sw"):
            x += item.width_cm + spacing
        else:
            x -= item.width_cm + spacing
    return placements


def _find_items(categories: Dict[str, List[CatalogItem]], keys: List[str]) -> List[CatalogItem]:
    results: List[CatalogItem] = []
    normalized_keys = [key.lower() for key in keys]
    for key in normalized_keys:
        results.extend(categories.get(key, []))
    return results


def _remove_duplicate_items(items: List[CatalogItem]) -> List[CatalogItem]:
    seen: Dict[str, CatalogItem] = {}
    for item in items:
        seen[item.item_id] = item
    return list(seen.values())


def _candidate_id(layout_type: str, index: int) -> str:
    return f"{layout_type.replace(' ', '_').lower()}_{index}"


def _generate_living_room_layouts(
    items: List[CatalogItem],
    room_width_cm: int,
    room_depth_cm: int,
) -> List[Tuple[str, List[FurniturePlacement]]]:
    categories = _group_items_by_category(items)
    tv_units = _find_items(categories, ["tv unit"])
    sofas = _find_items(categories, ["sofa"])
    coffee_tables = _find_items(categories, ["coffee table"])
    armchairs = _find_items(categories, ["armchair", "ottoman"])
    dining_chairs = _find_items(categories, ["dining chair", "office chair"])
    side_tables = _find_items(categories, ["side table", "console"])
    rugs = _find_items(categories, ["rug"])

    layouts: List[Tuple[str, List[FurniturePlacement]]] = []

    if tv_units and sofas:
        placements: List[FurniturePlacement] = []
        tv = tv_units[0]
        sofa = sofas[0]
        placements.append(_place_against_wall(tv, room_width_cm, room_depth_cm, "north", offset=0))
        placements.append(_place_against_wall(sofa, room_width_cm, room_depth_cm, "south", offset=0))

        if coffee_tables:
            table = coffee_tables[0]
            y = max(75 + tv.depth_cm, room_depth_cm - sofa.depth_cm - table.depth_cm - 75)
            x = (room_width_cm - table.width_cm) // 2
            placements.append(_build_placement(table, x, y))

        placements.extend(_place_along_wall(armchairs + dining_chairs, room_width_cm, room_depth_cm, "west"))
        placements.extend(_place_along_wall(side_tables, room_width_cm, room_depth_cm, "east"))
        if rugs:
            rug = rugs[0]
            placements.append(_build_placement(rug, max(75, (room_width_cm - rug.width_cm) // 2), max(75, (room_depth_cm - rug.depth_cm) // 2)))
        layouts.append(("TV-focused living room", placements))

    if sofas and (armchairs or len(sofas) > 1 or dining_chairs):
        placements: List[FurniturePlacement] = []
        sofa = sofas[0]
        placements.append(_place_against_wall(sofa, room_width_cm, room_depth_cm, "south"))
        if coffee_tables:
            table = coffee_tables[0]
            x = (room_width_cm - table.width_cm) // 2
            y = max(75, room_depth_cm - sofa.depth_cm - table.depth_cm - 150)
            placements.append(_build_placement(table, x, y))
        side_seats = (armchairs + dining_chairs)[:2]
        if side_seats:
            placements.extend(_place_along_wall(side_seats, room_width_cm, room_depth_cm, "north"))
        if tv_units:
            placements.append(_place_against_wall(tv_units[0], room_width_cm, room_depth_cm, "east"))
        if rugs:
            rug = rugs[0]
            placements.append(_build_placement(rug, max(75, (room_width_cm - rug.width_cm) // 2), max(75, (room_depth_cm - rug.depth_cm) // 2)))
        layouts.append(("Conversation-focused living room", placements))

    if not layouts:
        placements = [_place_center(item, room_width_cm, room_depth_cm) for item in items]
        layouts.append(("Balanced living room", placements))

    return layouts


def _generate_bedroom_layouts(
    items: List[CatalogItem],
    room_width_cm: int,
    room_depth_cm: int,
) -> List[Tuple[str, List[FurniturePlacement]]]:
    categories = _group_items_by_category(items)
    beds = _find_items(categories, ["bed"])
    wardrobes = _find_items(categories, ["wardrobe"])
    bedside_tables = _find_items(categories, ["bedside table"])
    dressers = _find_items(categories, ["console"])
    lamps = _find_items(categories, ["floor lamp", "table lamp", "pendant light"])
    rugs = _find_items(categories, ["rug"])

    layouts: List[Tuple[str, List[FurniturePlacement]]] = []

    if beds:
        placements: List[FurniturePlacement] = []
        bed = beds[0]
        placements.append(_place_against_wall(bed, room_width_cm, room_depth_cm, "south"))
        for index, side_table in enumerate(bedside_tables[:2]):
            x_offset = 75 + (bed.width_cm + 75) * index
            y = room_depth_cm - side_table.depth_cm - 75
            placements.append(_build_placement(side_table, x_offset, y))
        if wardrobes:
            placements.extend(_place_along_wall(wardrobes, room_width_cm, room_depth_cm, "north"))
        elif dressers:
            placements.extend(_place_along_wall(dressers, room_width_cm, room_depth_cm, "north"))
        placements.extend(_place_along_wall(lamps, room_width_cm, room_depth_cm, "west"))
        if rugs:
            rug = rugs[0]
            placements.append(_build_placement(rug, max(75, (room_width_cm - rug.width_cm) // 2), max(75, room_depth_cm - bed.depth_cm - rug.depth_cm - 150)))
        layouts.append(("Bed-focused bedroom", placements))

    if wardrobes or dressers:
        placements: List[FurniturePlacement] = []
        if wardrobes:
            placements.extend(_place_along_wall(wardrobes, room_width_cm, room_depth_cm, "north"))
        if beds:
            placements.append(_place_against_wall(beds[0], room_width_cm, room_depth_cm, "south"))
        if dressers and not wardrobes:
            placements.extend(_place_along_wall(dressers, room_width_cm, room_depth_cm, "east"))
        placements.extend(_place_along_wall(lamps, room_width_cm, room_depth_cm, "west"))
        if rugs:
            rug = rugs[0]
            placements.append(_build_placement(rug, max(75, (room_width_cm - rug.width_cm) // 2), 75))
        layouts.append(("Storage-focused bedroom", placements))

    if not layouts:
        placements = [_place_center(item, room_width_cm, room_depth_cm) for item in items]
        layouts.append(("Balanced bedroom", placements))

    return layouts


def _fits_room_and_non_overlapping(
    placement: FurniturePlacement,
    existing: List[FurniturePlacement],
    room_width_cm: int,
    room_depth_cm: int,
) -> bool:
    if not _fits_room(placement, room_width_cm, room_depth_cm):
        return False
    return all(not _rectangles_overlap(placement, other) for other in existing)


def _generate_study_layouts(
    items: List[CatalogItem],
    room_width_cm: int,
    room_depth_cm: int,
    window_position: Optional[Tuple[int, int]] = None,
) -> List[Tuple[str, List[FurniturePlacement]]]:
    categories = _group_items_by_category(items)
    desks = _find_items(categories, ["desk"])
    chairs = _find_items(categories, ["office chair", "armchair", "dining chair"])
    bookshelves = _find_items(categories, ["bookshelf"])
    side_tables = _find_items(categories, ["side table", "console"])
    lamps = _find_items(categories, ["floor lamp", "table lamp", "pendant light"])

    layouts: List[Tuple[str, List[FurniturePlacement]]] = []

    if desks:
        placements: List[FurniturePlacement] = []
        desk = desks[0]
        wall = "north" if window_position else "east"
        placements.append(_place_against_wall(desk, room_width_cm, room_depth_cm, wall))
        if chairs:
            chair_placement = _place_against_wall(chairs[0], room_width_cm, room_depth_cm, "west")
            if _fits_room_and_non_overlapping(chair_placement, placements, room_width_cm, room_depth_cm):
                placements.append(chair_placement)
            else:
                placements.append(_place_against_wall(chairs[0], room_width_cm, room_depth_cm, "south"))
        bookshelf_wall = "north" if wall == "east" else "east"
        placements.extend(_place_along_wall(bookshelves, room_width_cm, room_depth_cm, bookshelf_wall))
        placements.extend(_place_along_wall(lamps, room_width_cm, room_depth_cm, "south"))
        layouts.append(("Work-focused study", placements))

    if bookshelves and chairs:
        placements: List[FurniturePlacement] = []
        placements.extend(_place_items_in_corner(chairs[:1], room_width_cm, room_depth_cm, "se"))
        placements.extend(_place_along_wall(bookshelves, room_width_cm, room_depth_cm, "east"))
        if desks:
            placements.append(_place_against_wall(desks[0], room_width_cm, room_depth_cm, "north"))
        placements.extend(_place_along_wall(lamps, room_width_cm, room_depth_cm, "west"))
        layouts.append(("Reading-focused study", placements))

    if not layouts:
        placements = [_place_center(item, room_width_cm, room_depth_cm) for item in items]
        layouts.append(("Balanced study", placements))

    return layouts


def _generate_dining_layouts(
    items: List[CatalogItem],
    room_width_cm: int,
    room_depth_cm: int,
) -> List[Tuple[str, List[FurniturePlacement]]]:
    categories = _group_items_by_category(items)
    tables = _find_items(categories, ["dining table"])
    chairs = _find_items(categories, ["dining chair"])
    sideboards = _find_items(categories, ["console"])
    lamps = _find_items(categories, ["pendant light", "floor lamp", "table lamp"])
    rugs = _find_items(categories, ["rug"])

    layouts: List[Tuple[str, List[FurniturePlacement]]] = []

    if tables:
        table = tables[0]
        placements: List[FurniturePlacement] = []
        center_table = _place_center(table, room_width_cm, room_depth_cm)
        placements.append(center_table)
        if chairs:
            chair_placements: List[FurniturePlacement] = []
            for index, chair in enumerate(chairs[:4]):
                if index == 0:
                    x = center_table.x + (center_table.width - chair.width_cm) // 2
                    y = center_table.y - chair.depth_cm - 75
                elif index == 1:
                    x = center_table.x + (center_table.width - chair.width_cm) // 2
                    y = center_table.y + center_table.depth + 75
                elif index == 2:
                    x = center_table.x - chair.width_cm - 75
                    y = center_table.y + (center_table.depth - chair.depth_cm) // 2
                else:
                    x = center_table.x + center_table.width + 75
                    y = center_table.y + (center_table.depth - chair.depth_cm) // 2
                chair_placements.append(_build_placement(chair, x, y))
            if all(_fits_room_and_non_overlapping(chair, [center_table] + chair_placements[:i], room_width_cm, room_depth_cm) for i, chair in enumerate(chair_placements)):
                placements.extend(chair_placements)
            else:
                placements.extend(_place_along_wall(chairs[:4], room_width_cm, room_depth_cm, "north"))
        placements.extend(_place_along_wall(sideboards, room_width_cm, room_depth_cm, "north"))
        placements.extend(_place_along_wall(lamps, room_width_cm, room_depth_cm, "south"))
        if rugs:
            placements.append(_build_placement(rugs[0], max(75, center_table.x - 50), max(75, center_table.y - 50)))
        layouts.append(("Dining-centered layout", placements))

    if not layouts:
        if len(items) == 1:
            placements = [_place_center(items[0], room_width_cm, room_depth_cm)]
        else:
            placements = _place_along_wall(items, room_width_cm, room_depth_cm, "north")
        layouts.append(("Balanced dining room", placements))

    return layouts


def _generate_candidate_layouts(
    room_type: str,
    room_width_cm: int,
    room_depth_cm: int,
    selected_items: List[CatalogItem],
    user_constraints: Optional[List[str]] = None,
    door_position: Optional[Tuple[int, int]] = None,
    window_position: Optional[Tuple[int, int]] = None,
) -> List[LayoutEvaluation]:
    normalized_room = _normalize_text(room_type)
    items = _remove_duplicate_items(selected_items)
    base_candidates: List[Tuple[str, List[FurniturePlacement]]] = []

    if normalized_room == "living room":
        base_candidates = _generate_living_room_layouts(items, room_width_cm, room_depth_cm)
    elif normalized_room == "bedroom":
        base_candidates = _generate_bedroom_layouts(items, room_width_cm, room_depth_cm)
    elif normalized_room == "study":
        base_candidates = _generate_study_layouts(items, room_width_cm, room_depth_cm, window_position=window_position)
    elif normalized_room == "dining":
        base_candidates = _generate_dining_layouts(items, room_width_cm, room_depth_cm)
    else:
        base_candidates = [("Balanced layout", [_place_center(item, room_width_cm, room_depth_cm) for item in items])]

    layout_evaluations: List[LayoutEvaluation] = []
    for index, (layout_type, placements) in enumerate(base_candidates, start=1):
        evaluation = _evaluate_layout(
            layout_id=_candidate_id(layout_type, index),
            layout_type=layout_type,
            placements=placements,
            room_width_cm=room_width_cm,
            room_depth_cm=room_depth_cm,
            selected_items=items,
            room_type=room_type,
            user_constraints=user_constraints,
        )
        layout_evaluations.append(evaluation)
    return layout_evaluations


def _evaluate_layout(
    layout_id: str,
    layout_type: str,
    placements: List[FurniturePlacement],
    room_width_cm: int,
    room_depth_cm: int,
    selected_items: List[CatalogItem],
    room_type: str,
    user_constraints: Optional[List[str]] = None,
) -> LayoutEvaluation:
    validation = validate_layout(placements, room_width_cm, room_depth_cm, selected_items)
    score = _score_layout(validation, layout_type, placements, user_constraints)
    pros, cons = _generate_pros_cons(validation, layout_type, placements, user_constraints)

    logger.info(
        "layout_evaluated layout_id=%s type=%s valid=%s score=%.2f occupancy=%.2f clearance=%.1f",
        layout_id,
        layout_type,
        validation.valid,
        score,
        validation.occupancy_ratio,
        validation.minimum_clearance_cm,
    )

    return LayoutEvaluation(
        layout_id=layout_id,
        layout_type=layout_type,
        placements=placements,
        validation=validation,
        layout_score=score,
        pros=pros,
        cons=cons,
    )


def validate_layout(
    placements: List[FurniturePlacement],
    room_width_cm: int,
    room_depth_cm: int,
    selected_items: Optional[List[CatalogItem]] = None,
) -> ValidationResult:
    reasons: List[str] = []
    room_area = _room_area(room_width_cm, room_depth_cm)
    furniture_area = _furniture_area(placements)
    occupancy_ratio = _calculate_occupancy_ratio(placements, room_width_cm, room_depth_cm)
    minimum_clearance = _minimum_clearance(placements)
    if not placements:
            reasons.append("No furniture placements generated")

    for placement in placements:
        if not _fits_room(placement, room_width_cm, room_depth_cm):
            reasons.append(f"{placement.item_name} does not fit within room boundaries")

    for i, item_a in enumerate(placements):
        for item_b in placements[i + 1 :]:
            if _rectangles_overlap(item_a, item_b):
                reasons.append(f"{item_a.item_name} overlaps with {item_b.item_name}")

    if minimum_clearance < MIN_CIRCULATION_CM:
        reasons.append(
            f"Minimum circulation clearance {minimum_clearance:.1f}cm is below required {MIN_CIRCULATION_CM}cm"
        )

    if occupancy_ratio > MAX_OCCUPANCY_RATIO:
        reasons.append(
            f"Occupancy ratio {occupancy_ratio:.2f} exceeds maximum {MAX_OCCUPANCY_RATIO:.2f}"
        )

    if selected_items is not None:
        valid_ids = {item.item_id for item in selected_items}
        for placement in placements:
            if placement.item_id not in valid_ids:
                reasons.append(f"Placement contains unauthorized item {placement.item_name}")

    valid = len(reasons) == 0
    status = ValidationStatus.VALID if valid else ValidationStatus.INVALID

    logger.debug(
        "validate_layout valid=%s reasons=%s occupancy=%.2f min_clearance=%.1f",
        valid,
        reasons,
        occupancy_ratio,
        minimum_clearance,
    )

    return ValidationResult(
        valid=valid,
        validation_status=status,
        reasons=reasons,
        occupancy_ratio=occupancy_ratio,
        circulation_score=_circulation_score(minimum_clearance) if valid else 0.0,
        minimum_clearance_cm=minimum_clearance,
        furniture_area_cm2=furniture_area,
        room_area_cm2=room_area,
    )


def _circulation_score(minimum_clearance: float) -> float:
    if minimum_clearance <= MIN_CIRCULATION_CM:
        return 0.0
    return min(CIRCULATION_WEIGHT, (minimum_clearance / MIN_CIRCULATION_CM) * CIRCULATION_WEIGHT)


def _occupancy_score(occupancy_ratio: float) -> float:
    delta = abs(occupancy_ratio - IDEAL_OCCUPANCY_RATIO)
    score = max(0.0, OCCUPANCY_WEIGHT * (1.0 - delta / (MAX_OCCUPANCY_RATIO - IDEAL_OCCUPANCY_RATIO)))
    return score


def _functional_fit_score(layout_type: str, placements: List[FurniturePlacement]) -> float:
    layout = _normalize_text(layout_type)
    categories = {placement.category.lower() for placement in placements}
    has_sofa = "sofa" in categories
    has_tv = "tv unit" in categories
    has_table = "coffee table" in categories or "dining table" in categories or "desk" in categories
    has_bed = "bed" in categories
    has_chair = any(cat in categories for cat in ["armchair", "dining chair", "office chair"])
    has_bookshelf = "bookshelf" in categories
    has_wardrobe = "wardrobe" in categories

    if "tv-focused" in layout:
        if has_sofa and has_tv:
            return FUNCTIONAL_WEIGHT
        if has_sofa or has_tv:
            return FUNCTIONAL_WEIGHT * 0.5
    if "conversation-focused" in layout:
        if has_sofa and has_chair and has_table:
            return FUNCTIONAL_WEIGHT
        if has_sofa and has_table:
            return FUNCTIONAL_WEIGHT * 0.75
    if "bed-focused" in layout:
        return FUNCTIONAL_WEIGHT if has_bed else FUNCTIONAL_WEIGHT * 0.25
    if "storage-focused" in layout:
        return FUNCTIONAL_WEIGHT if has_wardrobe or has_bookshelf else FUNCTIONAL_WEIGHT * 0.25
    if "work-focused" in layout:
        return FUNCTIONAL_WEIGHT if has_table and has_chair else FUNCTIONAL_WEIGHT * 0.5
    if "reading-focused" in layout:
        return FUNCTIONAL_WEIGHT if has_bookshelf and has_chair else FUNCTIONAL_WEIGHT * 0.75
    if "dining-centered" in layout:
        if has_table and has_chair:
            return FUNCTIONAL_WEIGHT
        if has_table:
            return FUNCTIONAL_WEIGHT * 0.5
    return FUNCTIONAL_WEIGHT * 0.6


def _constraint_fit_score(layout_type: str, placements: List[FurniturePlacement], user_constraints: Optional[List[str]]) -> float:
    if not user_constraints:
        return 0.0
    tokens = _normalize_tokens(user_constraints)
    text = " ".join([layout_type] + [placement.category for placement in placements]).lower()
    matches = sum(1 for token in tokens if token in text)
    return min(CONSTRAINT_WEIGHT, (matches / max(1, len(tokens))) * CONSTRAINT_WEIGHT)


def _simplicity_score(placements: List[FurniturePlacement]) -> float:
    count = len(placements)
    score = max(0.0, SIMPLICITY_WEIGHT - max(0.0, (count - 1) * 0.5))
    return score


def _score_layout(
    validation: ValidationResult,
    layout_type: str,
    placements: List[FurniturePlacement],
    user_constraints: Optional[List[str]] = None,
) -> float:
    if not validation.valid:
        return 0.0
    score = 0.0
    score += validation.circulation_score
    score += _occupancy_score(validation.occupancy_ratio)
    score += _functional_fit_score(layout_type, placements)
    score += _constraint_fit_score(layout_type, placements, user_constraints)
    score += _simplicity_score(placements)
    return round(score, 2)


def _generate_pros_cons(
    validation: ValidationResult,
    layout_type: str,
    placements: List[FurniturePlacement],
    user_constraints: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    pros: List[str] = []
    cons: List[str] = []

    if validation.valid:

        if 0.45 <= validation.occupancy_ratio <= 0.60:
            pros.append("Efficient space usage")
        else:
            pros.append("Low occupancy efficiency")

        if "tv-focused" in layout_type.lower() and any("tv unit" == item.category.lower() for item in placements):
            pros.append("TV alignment is supported")
        if "bed-focused" in layout_type.lower():
            pros.append("Bed placement is prioritized")
    else:
        cons.extend(validation.reasons[:3])

    if validation.occupancy_ratio > 0.60:
        cons.append("Higher occupancy ratio")
    if validation.minimum_clearance_cm >= MIN_CIRCULATION_CM * 1.25:
       pros.append("Excellent circulation")
    elif validation.minimum_clearance_cm >= MIN_CIRCULATION_CM:
       pros.append("Sufficient circulation")
    else:
       cons.append("Limited circulation space")
    if user_constraints and not _constraint_fit_score(layout_type, placements, user_constraints):
        cons.append("Does not fully match user constraints")

    return pros, cons


def _optional_item_priority(item: CatalogItem) -> Tuple[int, int]:
    category = _normalize_text(item.category)
    priority_map = {
        "rug": 5,
        "floor lamp": 5,
        "table lamp": 5,
        "pendant light": 5,
        "mirror": 5,
        "wall art": 5,
        "planter": 5,
        "cushions": 5,
        "side table": 4,
        "console": 4,
        "bookshelf": 3,
        "wardrobe": 2,
        "bedside table": 2,
        "coffee table": 3,
        "armchair": 3,
        "office chair": 3,
        "dining chair": 3,
        "desk": 2,
        "dining table": 1,
        "bed": 1,
        "sofa": 1,
        "tv unit": 1,
    }
    priority = priority_map.get(category, 5)
    area = int((item.width_cm or 0) * (item.depth_cm or 0))
    return priority, area


def _remove_lowest_priority_item(
    items: List[CatalogItem], protected_item_ids: Optional[Set[str]] = None
) -> Optional[CatalogItem]:
    if len(items) <= 1:
        return None
    protected_item_ids = protected_item_ids or set()
    optional_candidates = [
        item
        for item in items
        if item.item_id not in protected_item_ids and _optional_item_priority(item)[0] >= 3
    ]
    if not optional_candidates:
        return None
    sorted_candidates = sorted(
        optional_candidates,
        key=lambda item: (
            -_optional_item_priority(item)[0],
            _optional_item_priority(item)[1],
        ),
    )
    return sorted_candidates[0]


def plan_layout(
    room_type: str,
    room_width_cm: int,
    room_depth_cm: int,
    selected_items: List[CatalogItem],
    user_constraints: Optional[List[str]] = None,
    protected_item_ids: Optional[Set[str]] = None,
    door_position: Optional[Tuple[int, int]] = None,
    window_position: Optional[Tuple[int, int]] = None,
) -> LayoutPlanResult:
    logger.info(
        "plan_layout room_type=%s width=%d depth=%d items=%d",
        room_type,
        room_width_cm,
        room_depth_cm,
        len(selected_items),
    )

    if room_width_cm <= 0 or room_depth_cm <= 0:
        raise ValueError("Room dimensions must be positive")

    initial_candidates = _generate_candidate_layouts(
        room_type,
        room_width_cm,
        room_depth_cm,
        selected_items,
        user_constraints=user_constraints,
        door_position=door_position,
        window_position=window_position,
    )

    valid_layouts = [layout for layout in initial_candidates if layout.validation.valid]
    best_layout = max(valid_layouts, key=lambda layout: layout.layout_score) if valid_layouts else None
    removed_item_ids: List[str] = []
    replan_triggered = False
    failure_reasons: List[str] = []
    alternative_layouts = initial_candidates

    if not best_layout:
        removed = _remove_lowest_priority_item(selected_items, protected_item_ids=protected_item_ids)
        if removed:
            replan_triggered = True
            removed_item_ids.append(removed.item_id)
            reduced_items = [item for item in selected_items if item.item_id != removed.item_id]
            logger.info("replan removing item=%s", removed.item_id)
            second_candidates = _generate_candidate_layouts(
                room_type,
                room_width_cm,
                room_depth_cm,
                reduced_items,
                user_constraints=user_constraints,
                door_position=door_position,
                window_position=window_position,
            )
            alternative_layouts = second_candidates
            valid_layouts = [layout for layout in second_candidates if layout.validation.valid]
            best_layout = max(valid_layouts, key=lambda layout: layout.layout_score) if valid_layouts else None
            if not best_layout:
                chosen = max(second_candidates, key=lambda layout: layout.layout_score, default=None)
                best_layout = chosen
                if chosen and not chosen.validation.valid:
                    failure_reasons = chosen.validation.reasons
        else:
            failure_reasons = ["No candidate layouts could be generated."]

    valid_layout_count = sum(1 for layout in alternative_layouts if layout.validation.valid)
    if not best_layout and alternative_layouts:
        best_layout = max(alternative_layouts, key=lambda layout: layout.layout_score)
        if best_layout and not best_layout.validation.valid:
            failure_reasons = best_layout.validation.reasons

    logger.info(
        "layout_summary generated=%d valid=%d best_layout=%s replan=%s removed=%s",
        len(alternative_layouts),
        valid_layout_count,
        best_layout.layout_id if best_layout else None,
        replan_triggered,
        removed_item_ids,
    )

    return LayoutPlanResult(
        room_type=room_type,
        room_width_cm=room_width_cm,
        room_depth_cm=room_depth_cm,
        best_layout=best_layout,
        alternative_layouts=alternative_layouts,
        replan_triggered=replan_triggered,
        removed_item_ids=removed_item_ids,
        failure_reasons=failure_reasons,
        all_layouts_generated=len(alternative_layouts),
        valid_layout_count=valid_layout_count,
    )
