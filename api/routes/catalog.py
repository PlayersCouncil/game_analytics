"""
Card catalog API routes.

Serves card metadata (names, images, cultures) for UI enrichment.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ..main import get_db_cursor


router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("")
def get_catalog(
    cursor = Depends(get_db_cursor),
    side: Optional[str] = Query(None, description="Filter by side: free_peoples, shadow, site"),
    culture: Optional[str] = Query(None, description="Filter by culture"),
    set_number: Optional[int] = Query(None, description="Filter by set number"),
):
    """
    Get full card catalog or filtered subset.
    
    Returns a dict keyed by blueprint for easy client-side lookup.
    Response is cacheable - catalog changes rarely.
    """
    sql = """
        SELECT blueprint, card_name, culture, card_type, 
               side, set_number, image_url
        FROM card_catalog
        WHERE 1=1
    """
    params = []
    
    if side:
        sql += " AND side = %s"
        params.append(side)
    
    if culture:
        sql += " AND culture = %s"
        params.append(culture)
    
    if set_number is not None:
        sql += " AND set_number = %s"
        params.append(set_number)
    
    sql += " ORDER BY set_number, blueprint"
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    
    # Build dict keyed by blueprint for O(1) lookups on client
    catalog = {}
    for row in rows:
        blueprint = row[0]
        catalog[blueprint] = {
            "name": row[1],
            "culture": row[2],
            "type": row[3],
            "side": row[4],
            "set": row[5],
            "image": row[6],
        }
    
    return {
        "total": len(catalog),
        "cards": catalog
    }


@router.get("/{blueprint}")
def get_card(
    blueprint: str,
    cursor = Depends(get_db_cursor),
):
    """Get single card by blueprint ID."""
    cursor.execute("""
        SELECT blueprint, card_name, subtitle, culture, card_type,
               side, twilight_cost, set_number, image_url
        FROM card_catalog
        WHERE blueprint = %s
    """, (blueprint,))
    
    row = cursor.fetchone()
    if not row:
        return {"error": "Card not found", "blueprint": blueprint}
    
    return {
        "blueprint": row[0],
        "name": row[1],
        "culture": row[2],
        "type": row[3],
        "side": row[4],
        "set": row[5],
        "image": row[6],
    }
