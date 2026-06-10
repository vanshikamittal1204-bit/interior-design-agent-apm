"""
Database models and access layer for Interior Design Agent.

This module provides:
1. Pydantic data models for type-safe data handling
2. Database connection and access methods
3. Filtering and query helpers
4. Data validation and error handling
"""

import sqlite3
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum
import logging

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ============================================================================
# Enums for Validated Values
# ============================================================================


class RoomType(str, Enum):
    """Valid room types from database."""
    LIVING_ROOM = "Living Room"
    BEDROOM = "Bedroom"
    DINING = "Dining"
    STUDY = "Study"
    KIDS = "Kids"


class StyleTag(str, Enum):
    """Valid style tags from catalog."""
    SCANDINAVIAN = "Scandinavian"
    MINIMALIST = "Minimalist"
    CONTEMPORARY = "Contemporary"
    INDUSTRIAL = "Industrial"
    MID_CENTURY = "Mid-Century"
    BOHEMIAN = "Bohemian"
    COASTAL = "Coastal"
    JAPANDI = "Japandi"
    TRADITIONAL = "Traditional"


class StockStatus(int, Enum):
    """Stock availability status."""
    OUT_OF_STOCK = 0
    IN_STOCK = 1


# ============================================================================
# Pydantic Models
# ============================================================================


class CatalogItem(BaseModel):
    """
    Represents a single item in the interior design catalog.
    
    All prices are in Indian Rupees (INR).
    All dimensions are in centimeters (cm).
    """
    
    item_id: str = Field(..., description="Unique product identifier (e.g., SOF-001)")
    category: str = Field(..., description="Product category (e.g., Sofa, Coffee Table)")
    name: str = Field(..., description="Product display name")
    style_tags: Optional[List[str]] = Field(
        default=None, 
        description="List of applicable style tags (parsed from comma-separated string)"
    )
    price_inr: Optional[int] = Field(
        default=None,
        description="Price in Indian Rupees. NULL values must be filtered out."
    )
    width_cm: Optional[int] = Field(
        default=None,
        description="Product width in centimeters"
    )
    depth_cm: Optional[int] = Field(
        default=None,
        description="Product depth in centimeters"
    )
    height_cm: Optional[int] = Field(
        default=None,
        description="Product height in centimeters"
    )
    color_finish: Optional[str] = Field(
        default=None,
        description="Color and finish description"
    )
    in_stock: int = Field(
        default=StockStatus.IN_STOCK,
        description="Stock status: 1=in stock, 0=out of stock"
    )
    lead_time_days: Optional[int] = Field(
        default=None,
        description="Days to deliver if ordered (range: 7-120)"
    )
    room_types: Optional[List[str]] = Field(
        default=None,
        description="Applicable room types (parsed from comma-separated string)"
    )
    
    @field_validator("in_stock", mode="before")
    @classmethod
    def validate_stock_status(cls, v):
        """Ensure in_stock is 0 or 1."""
        if v not in (0, 1):
            raise ValueError(f"in_stock must be 0 or 1, got {v}")
        return v
    
    def has_complete_dimensions(self) -> bool:
        """Check if all dimensions are available."""
        return all(dim is not None for dim in [self.width_cm, self.depth_cm, self.height_cm])
    
    def has_price(self) -> bool:
        """Check if item has a price (not NULL)."""
        return self.price_inr is not None
    
    def is_in_stock(self) -> bool:
        """Check if item is currently in stock."""
        return self.in_stock == StockStatus.IN_STOCK
    
    def matches_style(self, style: str) -> bool:
        """Check if item has the specified style tag."""
        if not self.style_tags:
            return False
        return style.lower() in [tag.lower() for tag in self.style_tags]
    
    def matches_room_type(self, room_type: str) -> bool:
        """Check if item is applicable to the specified room type."""
        if not self.room_types:
            return False
        return room_type.lower() in [rt.lower() for rt in self.room_types]


class RoomBrief(BaseModel):
    """
    Represents a customer design brief for a room.
    
    All dimensions are in centimeters (cm).
    All budgets are in Indian Rupees (INR).
    """
    
    brief_id: str = Field(..., description="Unique brief identifier (e.g., BR-01)")
    room_type: RoomType = Field(..., description="Type of room")
    length_cm: int = Field(..., description="Room length in centimeters")
    width_cm: int = Field(..., description="Room width in centimeters")
    ceiling_cm: int = Field(..., description="Ceiling height in centimeters")
    budget_inr: int = Field(..., description="Total budget in Indian Rupees")
    style_preference: StyleTag = Field(..., description="Preferred design style")
    must_haves: Optional[List[str]] = Field(
        default=None,
        description="List of must-have items/categories (parsed from comma-separated string)"
    )
    constraints: Optional[str] = Field(
        default=None,
        description="Special constraints or room-specific notes"
    )
    customer_note: Optional[str] = Field(
        default=None,
        description="Additional customer context"
    )
    
    @field_validator("budget_inr", "length_cm", "width_cm", "ceiling_cm", mode="before")
    @classmethod
    def validate_positive(cls, v):
        """Ensure dimensions and budget are positive."""
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v
    
    def get_floor_area(self) -> float:
        """Calculate room floor area in square centimeters."""
        return self.length_cm * self.width_cm
    
    def get_floor_area_sqm(self) -> float:
        """Calculate room floor area in square meters."""
        return self.get_floor_area() / 10_000


# ============================================================================
# Database Access Layer
# ============================================================================


class DatabaseConnection:
    """
    Manages SQLite database connections and queries.
    
    Features:
    - Lazy connection (connects on first use)
    - Automatic error handling
    - Type-safe model conversions
    - Built-in filtering for data quality
    """
    
    def __init__(self, db_path: str = "data/interior_company_catalog.db"):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """Verify database file exists."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        logger.info(f"Database located at: {self.db_path}")
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row  # Access columns by name
            logger.info("Database connection established")
        return self._conn
    
    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Database connection closed")
    
    def _parse_csv_field(self, value: Optional[str]) -> Optional[List[str]]:
        """Parse comma-separated string into list.
        
        Args:
            value: Comma-separated string or None
            
        Returns:
            List of trimmed strings or None if input is None
        """
        if not value:
            return None
        return [item.strip() for item in value.split(",")]
    
    # ========================================================================
    # Catalog Query Methods
    # ========================================================================
    
    def get_all_items(self, 
                      exclude_out_of_stock: bool = True,
                      exclude_no_price: bool = True) -> List[CatalogItem]:
        """
        Get all catalog items with optional data quality filters.
        
        Args:
            exclude_out_of_stock: Filter out items with in_stock=0
            exclude_no_price: Filter out items with NULL price
            
        Returns:
            List of CatalogItem models
        """
        cursor = self.conn.cursor()
        
        # Build query with optional filters
        where_clauses = []
        if exclude_out_of_stock:
            where_clauses.append("in_stock = 1")
        if exclude_no_price:
            where_clauses.append("price_inr IS NOT NULL")
        
        where_sql = " AND ".join(where_clauses)
        where_clause = f" WHERE {where_sql}" if where_sql else ""
        
        cursor.execute(f"SELECT * FROM catalog{where_clause} ORDER BY item_id")
        return [self._row_to_catalog_item(row) for row in cursor.fetchall()]
    
    def get_item_by_id(self, item_id: str) -> Optional[CatalogItem]:
        """Get single item by ID.
        
        Args:
            item_id: Product identifier
            
        Returns:
            CatalogItem or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM catalog WHERE item_id = ?", (item_id,))
        row = cursor.fetchone()
        return self._row_to_catalog_item(row) if row else None
    
    def get_items_by_category(self, 
                             category: str,
                             exclude_out_of_stock: bool = True,
                             exclude_no_price: bool = True) -> List[CatalogItem]:
        """Get items by product category.
        
        Args:
            category: Product category
            exclude_out_of_stock: Filter out out-of-stock items
            exclude_no_price: Filter out items with NULL price
            
        Returns:
            List of matching CatalogItems
        """
        cursor = self.conn.cursor()
        
        where_clauses = ["category = ?"]
        params = [category]
        
        if exclude_out_of_stock:
            where_clauses.append("in_stock = 1")
        if exclude_no_price:
            where_clauses.append("price_inr IS NOT NULL")
        
        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"SELECT * FROM catalog WHERE {where_sql} ORDER BY name", params)
        
        return [self._row_to_catalog_item(row) for row in cursor.fetchall()]
    
    def get_items_by_room_type(self,
                              room_type: str,
                              exclude_out_of_stock: bool = True,
                              exclude_no_price: bool = True) -> List[CatalogItem]:
        """Get items applicable to a room type.
        
        Args:
            room_type: Room type filter
            exclude_out_of_stock: Filter out out-of-stock items
            exclude_no_price: Filter out items with NULL price
            
        Returns:
            List of matching CatalogItems
        """
        cursor = self.conn.cursor()
        
        where_clauses = ["room_types IS NOT NULL"]
        params = []
        
        if exclude_out_of_stock:
            where_clauses.append("in_stock = 1")
        if exclude_no_price:
            where_clauses.append("price_inr IS NOT NULL")
        
        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"SELECT * FROM catalog WHERE {where_sql} ORDER BY category, name", params)
        
        # Filter by room_type at application level (due to comma-separated values)
        results = []
        for row in cursor.fetchall():
            item = self._row_to_catalog_item(row)
            if item.matches_room_type(room_type):
                results.append(item)
        return results
    
    def get_items_by_style(self,
                          style: str,
                          exclude_out_of_stock: bool = True,
                          exclude_no_price: bool = True) -> List[CatalogItem]:
        """Get items matching a style tag.
        
        Args:
            style: Style preference
            exclude_out_of_stock: Filter out out-of-stock items
            exclude_no_price: Filter out items with NULL price
            
        Returns:
            List of matching CatalogItems
        """
        cursor = self.conn.cursor()
        
        where_clauses = ["style_tags IS NOT NULL"]
        params = []
        
        if exclude_out_of_stock:
            where_clauses.append("in_stock = 1")
        if exclude_no_price:
            where_clauses.append("price_inr IS NOT NULL")
        
        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"SELECT * FROM catalog WHERE {where_sql} ORDER BY category, name", params)
        
        # Filter by style at application level (due to comma-separated values)
        results = []
        for row in cursor.fetchall():
            item = self._row_to_catalog_item(row)
            if item.matches_style(style):
                results.append(item)
        return results
    
    def get_items_by_room_and_style(self,
                                   room_type: str,
                                   style: str,
                                   exclude_out_of_stock: bool = True,
                                   exclude_no_price: bool = True) -> List[CatalogItem]:
        """Get items matching both room type and style.
        
        Args:
            room_type: Room type filter
            style: Style preference
            exclude_out_of_stock: Filter out out-of-stock items
            exclude_no_price: Filter out items with NULL price
            
        Returns:
            List of matching CatalogItems
        """
        cursor = self.conn.cursor()
        
        where_clauses = ["room_types IS NOT NULL", "style_tags IS NOT NULL"]
        params = []
        
        if exclude_out_of_stock:
            where_clauses.append("in_stock = 1")
        if exclude_no_price:
            where_clauses.append("price_inr IS NOT NULL")
        
        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"SELECT * FROM catalog WHERE {where_sql} ORDER BY category, name", params)
        
        # Filter at application level
        results = []
        for row in cursor.fetchall():
            item = self._row_to_catalog_item(row)
            if item.matches_room_type(room_type) and item.matches_style(style):
                results.append(item)
        return results
    
    # ========================================================================
    # Room Brief Query Methods
    # ========================================================================
    
    def get_all_briefs(self) -> List[RoomBrief]:
        """Get all room briefs.
        
        Returns:
            List of all RoomBriefs
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM room_briefs ORDER BY brief_id")
        return [self._row_to_room_brief(row) for row in cursor.fetchall()]
    
    def get_brief_by_id(self, brief_id: str) -> Optional[RoomBrief]:
        """Get single brief by ID.
        
        Args:
            brief_id: Brief identifier
            
        Returns:
            RoomBrief or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM room_briefs WHERE brief_id = ?", (brief_id,))
        row = cursor.fetchone()
        return self._row_to_room_brief(row) if row else None
    
    def get_briefs_by_room_type(self, room_type: str) -> List[RoomBrief]:
        """Get briefs for specific room type.
        
        Args:
            room_type: Room type filter
            
        Returns:
            List of matching RoomBriefs
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM room_briefs WHERE room_type = ? ORDER BY brief_id",
                      (room_type,))
        return [self._row_to_room_brief(row) for row in cursor.fetchall()]
    
    # ========================================================================
    # Helper Methods for Model Conversion
    # ========================================================================
    
    def _row_to_catalog_item(self, row: sqlite3.Row) -> CatalogItem:
        """Convert database row to CatalogItem model.
        
        Args:
            row: sqlite3.Row from catalog table
            
        Returns:
            CatalogItem instance
        """
        return CatalogItem(
            item_id=row["item_id"],
            category=row["category"],
            name=row["name"],
            style_tags=self._parse_csv_field(row["style_tags"]),
            price_inr=row["price_inr"],
            width_cm=row["width_cm"],
            depth_cm=row["depth_cm"],
            height_cm=row["height_cm"],
            color_finish=row["color_finish"],
            in_stock=row["in_stock"],
            lead_time_days=row["lead_time_days"],
            room_types=self._parse_csv_field(row["room_types"]),
        )
    
    def _row_to_room_brief(self, row: sqlite3.Row) -> RoomBrief:
        """Convert database row to RoomBrief model.
        
        Args:
            row: sqlite3.Row from room_briefs table
            
        Returns:
            RoomBrief instance
        """
        return RoomBrief(
            brief_id=row["brief_id"],
            room_type=row["room_type"],
            length_cm=row["length_cm"],
            width_cm=row["width_cm"],
            ceiling_cm=row["ceiling_cm"],
            budget_inr=row["budget_inr"],
            style_preference=row["style_preference"],
            must_haves=self._parse_csv_field(row["must_haves"]),
            constraints=row["constraints"],
            customer_note=row["customer_note"],
        )


# ============================================================================
# Module-Level Convenience Functions
# ============================================================================


def get_db_connection(db_path: str = "data/interior_company_catalog.db") -> DatabaseConnection:
    """Factory function to create database connection.
    
    Args:
        db_path: Path to SQLite database
        
    Returns:
        DatabaseConnection instance
    """
    return DatabaseConnection(db_path)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    db = get_db_connection()
    
    # Load all items with quality filters
    items = db.get_all_items()
    print(f"Loaded {len(items)} items (excluding out-of-stock and NULL prices)")
    
    # Load briefs
    briefs = db.get_all_briefs()
    print(f"Loaded {len(briefs)} briefs")
    
    # Example: Get Living Room items that are Scandinavian style
    living_room_scandinavian = db.get_items_by_room_and_style("Living Room", "Scandinavian")
    print(f"Found {len(living_room_scandinavian)} Scandinavian items for Living Room")
    
    for item in living_room_scandinavian[:3]:
        print(f"  - {item.name} (₹{item.price_inr})")
    
    db.close()
