# Interior Design Catalog Database Analysis

## Overview

The SQLite database `interior_company_catalog.db` contains 2 tables:
- **catalog**: 72 furniture and decor items across 26 categories
- **room_briefs**: 14 room design requests with specifications

## Database Schema

### Table: `catalog`

**Purpose**: Central product inventory with physical attributes, pricing, and applicability.

**Columns**:

| Column | Type | Nullable | Primary Key | Purpose |
|--------|------|----------|-------------|---------|
| item_id | TEXT | NO | YES | Unique product identifier (e.g., SOF-001) |
| category | TEXT | NO | NO | Product category (e.g., Sofa, Coffee Table) |
| name | TEXT | NO | NO | Product name (e.g., Nordby 3-Seater Fabric Sofa) |
| style_tags | TEXT | YES | NO | Comma-separated style classifications (e.g., "Scandinavian,Minimalist") |
| price_inr | INTEGER | YES | NO | Product price in Indian Rupees. **5 items are NULL - FILTER THESE OUT** |
| width_cm | INTEGER | YES | NO | Product width in centimeters |
| depth_cm | INTEGER | YES | NO | Product depth in centimeters |
| height_cm | INTEGER | YES | NO | Product height in centimeters |
| color_finish | TEXT | YES | NO | Visual description of color/finish (e.g., "Oatmeal grey") |
| in_stock | INTEGER | YES | NO | Stock status: 1 (in stock) or 0 (out of stock). 66 in-stock, 6 out-of-stock |
| lead_time_days | INTEGER | YES | NO | Days to deliver if ordered. Range: 7-120 days, Average: 24 days |
| room_types | TEXT | YES | NO | Comma-separated applicable room types (e.g., "Living Room") |

**Data Characteristics**:

- **Total Products**: 72
- **Categories**: 26 (Sofa: 8, Dining Chair/Table: 8, Coffee Table: 4, Armchair: 4, etc.)
- **Stock Status**:
  - In stock: 66 items
  - Out of stock: 6 items
- **Price Range**: ₹3,200 - ₹280,000 (Average: ₹36,654)
- **Dimensions**:
  - Width: 30-340 cm (Avg: 130 cm)
  - Depth: 1-213 cm (Avg: 77 cm)
  - Height: 1-280 cm (Avg: 88 cm)
- **Lead Time**: 7-120 days (Average: 24 days)
- **Style Tags**: 10 unique styles (Scandinavian, Minimalist, Contemporary, Industrial, Mid-Century, Bohemian, Coastal, Japandi, Traditional, plus empty tags)
- **Color Finishes**: 63 unique descriptions
- **Room Types**: 5 categories (Living Room, Bedroom, Dining, Study, Kids)

**Nullable Fields** (data quality concerns):
- `style_tags`: Some items missing style classification
- `price_inr`: 5 items (7% of catalog) lack pricing - **must be filtered out**
- `width_cm`, `depth_cm`, `height_cm`: Some items missing dimensions
- `color_finish`: Some items missing color information
- `in_stock`: All items have stock status
- `lead_time_days`: All items have lead time
- `room_types`: Most items have room type applicable

---

### Table: `room_briefs`

**Purpose**: Customer requirements and room specifications for design briefs.

**Columns**:

| Column | Type | Nullable | Primary Key | Purpose |
|--------|------|----------|-------------|---------|
| brief_id | TEXT | NO | YES | Unique brief identifier (e.g., BR-01) |
| room_type | TEXT | YES | NO | Type of room (Living Room, Bedroom, Dining, Study, Kids) |
| length_cm | INTEGER | YES | NO | Room length in centimeters |
| width_cm | INTEGER | YES | NO | Room width in centimeters |
| ceiling_cm | INTEGER | YES | NO | Ceiling height in centimeters |
| budget_inr | INTEGER | YES | NO | Budget constraint in Indian Rupees |
| style_preference | TEXT | YES | NO | Desired style (e.g., Scandinavian, Contemporary) |
| must_haves | TEXT | YES | NO | Comma-separated required items (e.g., "3-seater sofa, coffee table, TV unit") |
| constraints | TEXT | YES | NO | Special constraints or notes |
| customer_note | TEXT | YES | NO | Additional customer context |

**Data Characteristics**:

- **Total Briefs**: 14
- **Room Type Distribution**:
  - Living Room: 8 briefs (primary focus for MVP)
  - Bedroom: 2 briefs
  - Dining: 2 briefs
  - Study: 1 brief
  - Kids: 1 brief
- **Budget Range**: ₹20,000 - ₹500,000 (Average: ₹196,429)
- **Room Dimensions**:
  - Length: 240-520 cm (Avg: 394 cm)
  - Width: 210-400 cm (Avg: 320 cm)
  - Ceiling Height: 270-310 cm (Avg: 291 cm)
- **Style Preferences**: 8 styles (Scandinavian, Contemporary, Minimalist, Bohemian, Industrial, Mid-Century, Coastal, Traditional)

**Nullable Fields** (data quality):
- **NO NULL VALUES**: All briefs have complete information

**Distribution for MVP**:
- 8 Living Room briefs (100% coverage for MVP scope)
- Budget: ₹20,000 - ₹500,000 (wide range testing)

---

## Relationships

**Primary Key Relationship**: None explicitly defined in schema.
- Implicit: Items with matching `room_types` values can be used in briefs with matching `room_type`
- Style matching: Items with `style_tags` matching brief's `style_preference`

---

## Fields by Use Case

### 1. Room Filtering
Used to find items applicable to a room type:
- **catalog.room_types**: Comma-separated list of applicable rooms
- **room_briefs.room_type**: Required room type
- **Strategy**: Parse `room_types`, check if brief's `room_type` exists

**Example**:
```
catalog item: room_types = "Living Room"
brief: room_type = "Living Room"
→ Item is applicable
```

### 2. Style Filtering
Used to find items matching desired aesthetic:
- **catalog.style_tags**: Comma-separated style tags
- **room_briefs.style_preference**: Desired style
- **Strategy**: Parse `style_tags`, check if brief's `style_preference` exists

**Example**:
```
catalog item: style_tags = "Scandinavian,Minimalist"
brief: style_preference = "Scandinavian"
→ Item matches style preference
```

### 3. Budget Calculations
Used to ensure total cost doesn't exceed budget:
- **catalog.price_inr**: Per-item cost (5 items are NULL - filter these)
- **room_briefs.budget_inr**: Total available budget
- **Strategy**: Sum selected items' prices, ensure `total <= budget`

**Constraints**:
- Must exclude items with NULL prices
- Items flagged as out-of-stock may have alternative lead times (skip if budget sensitive)

### 4. Stock Validation
Used to ensure items are available:
- **catalog.in_stock**: Flag (1 = in stock, 0 = out of stock)
- **catalog.lead_time_days**: Days to delivery if ordered
- **Strategy**:
  - Filter to `in_stock = 1` for immediate availability
  - Consider lead times for customer preference
  - Flag out-of-stock items (6 items) as unavailable unless explicitly requested

**Constraints**:
- 6 items are currently out of stock (should generally be excluded)
- Lead times range 7-120 days (may influence customer satisfaction)

### 5. Dimension Validation
Used to ensure items fit in the room:
- **catalog dimensions**: `width_cm`, `depth_cm`, `height_cm`
- **room_briefs dimensions**: `length_cm`, `width_cm`, `ceiling_cm`
- **Strategy**: Validate selected items don't exceed room constraints
  - For furniture with footprint: item `width_cm + depth_cm` should fit within room
  - For wall-mounted items: check `height_cm` vs ceiling
  - For tall items (wardrobes, shelves): ensure fit below ceiling

**Constraints**:
- Some catalog items have NULL dimensions (cannot validate fit - exclude or handle carefully)
- Need layout algorithm to check spatial feasibility
- MVP simplification: Accept if item dimensions don't exceed room dimensions

---

## Data Quality Issues

### Critical Issues (Must Handle)

1. **Missing Prices** (5 items, 7%):
   - Items: `price_inr IS NULL`
   - Impact: Cannot budget these items
   - Mitigation: Filter out products with NULL price during planning

2. **Missing Dimensions** (Some items):
   - Impact: Cannot validate room fit for affected items
   - Mitigation: Log items that fail dimension check, exclude from recommendations

3. **Out-of-Stock Items** (6 items):
   - Items: `in_stock = 0`
   - Impact: Not available for immediate order
   - Mitigation: Filter by `in_stock = 1` unless customer requests alternatives

### Minor Issues (Nice-to-Have)

- Some items have empty `style_tags` (not a blocker, treat as "unclassified")
- Variations in dimension coverage (some missing specific dimensions)

---

## Proposed Data Access Patterns

### For the Planner Component

#### 1. Get Room Brief
```python
get_brief(brief_id: str) -> RoomBrief
# Returns complete brief with parsed requirements
```

#### 2. Get Applicable Items
```python
get_items_by_room(room_type: str) -> List[CatalogItem]
# Filter by room_types matching room_type
# Exclude out-of-stock and NULL price items
```

#### 3. Get Items by Style
```python
get_items_by_style(style: str) -> List[CatalogItem]
# Filter by style_tags containing style
# May include NULL-style items as fallback
```

#### 4. Get Items by Category
```python
get_items_by_category(category: str) -> List[CatalogItem]
# Direct category match
```

#### 5. Validate Room Fit
```python
validate_room_fit(brief: RoomBrief, items: List[CatalogItem]) -> FitResult
# Check dimensions, return spatial feasibility
```

#### 6. Calculate Total Cost
```python
calculate_cost(items: List[CatalogItem]) -> int
# Sum prices, raise if any item has NULL price
```

#### 7. Get Budget Remaining
```python
get_budget_remaining(brief: RoomBrief, items: List[CatalogItem]) -> int
# Budget - total cost
```

---

## Schema Normalization Notes

**Current State**: Denormalized (comma-separated lists stored as strings)

**Why**: 
- Simplifies MVP (no join tables needed)
- Adequate for current scale (72 items, 14 briefs)

**If Scaling Beyond MVP**, Consider:
- Create `item_styles` join table (item_id → style_tag)
- Create `item_room_types` join table (item_id → room_type)
- Normalize style and room type into separate tables for reuse
- Would allow better querying and data integrity constraints

---

## SQL Optimization Tips

1. **Filter Early**: Apply `WHERE in_stock = 1 AND price_inr IS NOT NULL` for all queries
2. **Index**: Consider index on `(room_type)` and `(category)` for faster lookups
3. **Pagination**: Not critical for 72 items, but useful for UI
4. **Caching**: Cache parsed style_tags and room_types at application startup

---

## Summary

| Aspect | Details |
|--------|---------|
| **Total Products** | 72 items, 26 categories |
| **Total Briefs** | 14 briefs (8 Living Room) |
| **Price Coverage** | 94% (67/72 items have prices) |
| **In-Stock Coverage** | 92% (66/72 items in stock) |
| **Dimension Coverage** | ~90% (most items have w/d/h) |
| **Style Coverage** | Diverse (10 unique styles) |
| **Room Type Coverage** | 5 types (Living Room primary) |
| **Recommended MVP Scope** | Living Room only |
| **Critical Filters** | `in_stock=1 AND price_inr IS NOT NULL` |
