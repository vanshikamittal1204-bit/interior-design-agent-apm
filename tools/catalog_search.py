"""Catalog search tool for the interior design agent.

This tool uses the existing database access layer in utils/db.py exclusively.
It performs search and ranking operations over eligible catalog items.
"""

import logging
from typing import Dict, Iterable, List, Optional, Tuple

from utils.db import CatalogItem, DatabaseConnection

logger = logging.getLogger(__name__)


# Ranking weights
ROOM_MATCH_WEIGHT = 30.0
STYLE_MATCH_WEIGHT = 25.0
MUST_HAVE_MATCH_WEIGHT = 10.0
PRICE_EFFICIENCY_WEIGHT = 20.0
PRIORITY_BOOST_WEIGHT = 15.0


def _normalize_tokens(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return []
    return [value.strip().lower() for value in values if value and value.strip()]


def _match_tokens(source: str, tokens: List[str]) -> int:
    if not source or not tokens:
        return 0
    normalized_source = source.lower()
    return sum(1 for token in tokens if token and token in normalized_source)


def _item_priority_score(item: CatalogItem, priority_boosts: Optional[Dict[str, float]]) -> float:
    if not priority_boosts:
        return 0.0

    score = 0.0
    boosted_fields = [
        item.item_id,
        item.category,
        item.name or "",
        item.color_finish or "",
    ]
    boosted_fields.extend(item.room_types or [])
    boosted_fields.extend(item.style_tags or [])
    boosted_values = [field.lower() for field in boosted_fields if field]

    for key, boost in priority_boosts.items():
        key_text = str(key).strip().lower()
        if not key_text:
            continue
        if key_text in boosted_values:
            score += boost * PRIORITY_BOOST_WEIGHT
            continue
        if any(key_text in value for value in boosted_values):
            score += boost * PRIORITY_BOOST_WEIGHT
    return score


def _price_efficiency_score(item: CatalogItem, candidates: List[CatalogItem]) -> float:
    if not candidates:
        return 0.0

    prices = [candidate.price_inr for candidate in candidates if candidate.price_inr is not None]
    if not prices:
        return 0.0

    min_price = min(prices)
    max_price = max(prices)
    if min_price == max_price:
        return PRICE_EFFICIENCY_WEIGHT / 2.0

    normalized = (max_price - item.price_inr) / (max_price - min_price)
    return normalized * PRICE_EFFICIENCY_WEIGHT


def _must_have_score(item: CatalogItem, must_haves: Optional[List[str]]) -> float:
    tokens = _normalize_tokens(must_haves)
    if not tokens:
        return 0.0

    matches = 0
    matches += _match_tokens(item.category or "", tokens)
    matches += _match_tokens(item.name or "", tokens)
    matches += sum(_match_tokens(tag or "", tokens) for tag in item.style_tags or [])
    matches += _match_tokens(item.color_finish or "", tokens)
    return matches * MUST_HAVE_MATCH_WEIGHT


def _room_match_score(item: CatalogItem, room_type: Optional[str]) -> float:
    if not room_type:
        return 0.0
    return ROOM_MATCH_WEIGHT if item.matches_room_type(room_type) else 0.0


def _style_match_score(item: CatalogItem, style: Optional[str]) -> float:
    if not style:
        return 0.0
    return STYLE_MATCH_WEIGHT if item.matches_style(style) else 0.0


def _rank_item(item: CatalogItem,
               candidates: List[CatalogItem],
               room_type: Optional[str] = None,
               style: Optional[str] = None,
               must_haves: Optional[List[str]] = None,
               priority_boosts: Optional[Dict[str, float]] = None) -> float:
    score = 0.0
    score += _room_match_score(item, room_type)
    score += _style_match_score(item, style)
    score += _must_have_score(item, must_haves)
    score += _price_efficiency_score(item, candidates)
    score += _item_priority_score(item, priority_boosts)
    return score


def _filter_eligible_items(items: List[CatalogItem]) -> Tuple[List[CatalogItem], int]:
    total = len(items)
    filtered = [item for item in items if item.has_complete_dimensions()]
    filtered_count = total - len(filtered)
    return filtered, filtered_count


def _sort_ranked_items(ranked_items: List[Tuple[CatalogItem, float]]) -> List[CatalogItem]:
    return [item for item, score in sorted(ranked_items, key=lambda pair: pair[1], reverse=True)]


def _log_ranking(items: List[CatalogItem], scores: Dict[str, float], candidates: int, filtered: int) -> None:
    logger.info(
        "Catalog search candidates=%d filtered_missing_dimensions=%d final=%d",
        candidates,
        filtered,
        len(items),
    )
    for item in items:
        logger.debug("Catalog item=%s score=%.2f", item.item_id, scores[item.item_id])


def get_eligible_items(
    db: DatabaseConnection,
    room_type: Optional[str] = None,
    style: Optional[str] = None,
    category: Optional[str] = None,
    must_haves: Optional[List[str]] = None,
    priority_boosts: Optional[Dict[str, float]] = None,
) -> List[CatalogItem]:
    """Get ranked eligible catalog items using the DB layer only."""
    candidates = db.get_all_items()
    total_candidates = len(candidates)

    if category:
        candidates = [item for item in candidates if item.category.lower() == category.lower()]
    if room_type:
        candidates = [item for item in candidates if item.matches_room_type(room_type)]
    if style:
        candidates = [item for item in candidates if item.matches_style(style)]

    candidates, filtered_out = _filter_eligible_items(candidates)
    ranked_items = []
    scores: Dict[str, float] = {}
    for item in candidates:
        score = _rank_item(
            item,
            candidates,
            room_type=room_type,
            style=style,
            must_haves=must_haves,
            priority_boosts=priority_boosts,
        )
        scores[item.item_id] = score
        ranked_items.append((item, score))

    ranked = _sort_ranked_items(ranked_items)
    _log_ranking(ranked, scores, total_candidates, filtered_out)
    return ranked


def search_by_room_type(
    db: DatabaseConnection,
    room_type: str,
    must_haves: Optional[List[str]] = None,
    priority_boosts: Optional[Dict[str, float]] = None,
) -> List[CatalogItem]:
    """Search items applicable to a room type."""
    return get_eligible_items(
        db,
        room_type=room_type,
        must_haves=must_haves,
        priority_boosts=priority_boosts,
    )


def search_by_style(
    db: DatabaseConnection,
    style: str,
    must_haves: Optional[List[str]] = None,
    priority_boosts: Optional[Dict[str, float]] = None,
) -> List[CatalogItem]:
    """Search items that match a style preference."""
    return get_eligible_items(
        db,
        style=style,
        must_haves=must_haves,
        priority_boosts=priority_boosts,
    )


def search_by_category(
    db: DatabaseConnection,
    category: str,
    must_haves: Optional[List[str]] = None,
    priority_boosts: Optional[Dict[str, float]] = None,
) -> List[CatalogItem]:
    """Search items in a specific category."""
    return get_eligible_items(
        db,
        category=category,
        must_haves=must_haves,
        priority_boosts=priority_boosts,
    )


def search_by_room_and_style(
    db: DatabaseConnection,
    room_type: str,
    style: str,
    must_haves: Optional[List[str]] = None,
    priority_boosts: Optional[Dict[str, float]] = None,
) -> List[CatalogItem]:
    """Search items matching both room type and style."""
    return get_eligible_items(
        db,
        room_type=room_type,
        style=style,
        must_haves=must_haves,
        priority_boosts=priority_boosts,
    )
