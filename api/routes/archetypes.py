"""
Card community / archetype API endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException

from ..main import get_db_cursor

router = APIRouter(tags=["archetypes"])


@router.get("/communities")
def list_communities(
    format_name: str = Query(..., description="Format to query"),
    side: Optional[str] = Query(None, description="Filter by side (free_peoples/shadow)"),
    include_invalid: bool = Query(False, description="Include communities marked as invalid"),
    cursor = Depends(get_db_cursor),
):
    """
    List all detected communities for a format.
    """
    query = """
        SELECT 
            cc.id,
            cc.format_name,
            cc.side,
            cc.community_id,
            cc.card_count,
            cc.deck_count,
            cc.avg_internal_lift,
            cc.archetype_name,
            cc.is_valid,
            cc.notes,
            cc.created_at
        FROM card_communities cc
        WHERE cc.format_name = %s
    """
    params = [format_name]
    
    if side:
        query += " AND cc.side = %s"
        params.append(side)
    
    if not include_invalid:
        query += " AND cc.is_valid = TRUE"
    
    query += " ORDER BY cc.card_count DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    communities = []
    for row in rows:
        communities.append({
            "id": row[0],
            "format_name": row[1],
            "side": row[2],
            "community_id": row[3],
            "card_count": row[4],
            "deck_count": row[5],
            "avg_internal_lift": row[6],
            "archetype_name": row[7],
            "is_valid": row[8],
            "notes": row[9],
            "created_at": row[10].isoformat() if row[10] else None,
        })
    
    return {"format_name": format_name, "communities": communities}


@router.get("/communities/{community_id}")
def get_community_detail(
    community_id: int,
    cursor = Depends(get_db_cursor),
):
    """
    Get detailed info about a community including all member cards.
    """
    # Get community info
    cursor.execute("""
        SELECT 
            cc.id,
            cc.format_name,
            cc.side,
            cc.community_id,
            cc.card_count,
            cc.deck_count,
            cc.avg_internal_lift,
            cc.archetype_name,
            cc.is_valid,
            cc.notes
        FROM card_communities cc
        WHERE cc.id = %s
    """, (community_id,))
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    
    community = {
        "id": row[0],
        "format_name": row[1],
        "side": row[2],
        "community_id": row[3],
        "card_count": row[4],
        "deck_count": row[5],
        "avg_internal_lift": row[6],
        "archetype_name": row[7],
        "is_valid": row[8],
        "notes": row[9],
    }
    
    # Get member cards with names
    cursor.execute("""
        SELECT 
            ccm.card_blueprint,
            ccm.membership_score,
            ccm.is_core,
            cat.card_name,
            cat.culture,
            cat.card_type,
            cat.image_url
        FROM card_community_members ccm
        LEFT JOIN card_catalog cat ON ccm.card_blueprint = cat.blueprint
        WHERE ccm.community_id = %s
        ORDER BY ccm.membership_score DESC
    """, (community_id,))
    
    members = []
    for row in cursor.fetchall():
        members.append({
            "blueprint": row[0],
            "membership_score": row[1],
            "is_core": row[2],
            "name": row[3],
            "culture": row[4],
            "card_type": row[5],
            "image_url": row[6],
        })
    
    community["members"] = members
    
    return community


@router.put("/communities/{community_id}")
def update_community(
    community_id: int,
    archetype_name: Optional[str] = Query(None),
    is_valid: Optional[bool] = Query(None),
    notes: Optional[str] = Query(None),
    cursor = Depends(get_db_cursor),
):
    """
    Update community metadata (name, validity, notes).
    """
    # Build update query dynamically
    updates = []
    params = []
    
    if archetype_name is not None:
        updates.append("archetype_name = %s")
        params.append(archetype_name if archetype_name else None)
    
    if is_valid is not None:
        updates.append("is_valid = %s")
        params.append(is_valid)
    
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes if notes else None)
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    params.append(community_id)
    
    cursor.execute(f"""
        UPDATE card_communities 
        SET {', '.join(updates)}
        WHERE id = %s
    """, params)
    
    # Need to commit - get connection from cursor
    cursor._connection.commit()
    
    return {"success": True, "updated_fields": len(updates)}


@router.get("/communities/{community_id}/correlations")
def get_community_correlations(
    community_id: int,
    limit: int = Query(50, description="Max correlations to return"),
    cursor = Depends(get_db_cursor),
):
    """
    Get correlations between cards within this community.
    Useful for understanding internal structure.
    """
    # Get community info first
    cursor.execute("""
        SELECT format_name, side 
        FROM card_communities 
        WHERE id = %s
    """, (community_id,))
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    
    format_name, side = row
    
    # Get member cards
    cursor.execute("""
        SELECT card_blueprint 
        FROM card_community_members 
        WHERE community_id = %s
    """, (community_id,))
    
    members = [r[0] for r in cursor.fetchall()]
    
    if len(members) < 2:
        return {"correlations": []}
    
    # Get correlations between members
    placeholders = ','.join(['%s'] * len(members))
    cursor.execute(f"""
        SELECT 
            cc.card_a,
            cc.card_b,
            cc.lift,
            cc.together_count,
            cat_a.card_name as name_a,
            cat_b.card_name as name_b
        FROM card_correlations cc
        LEFT JOIN card_catalog cat_a ON cc.card_a = cat_a.blueprint
        LEFT JOIN card_catalog cat_b ON cc.card_b = cat_b.blueprint
        WHERE cc.format_name = %s
          AND cc.side = %s
          AND cc.card_a IN ({placeholders})
          AND cc.card_b IN ({placeholders})
        ORDER BY cc.lift DESC
        LIMIT %s
    """, [format_name, side] + members + members + [limit])
    
    correlations = []
    for row in cursor.fetchall():
        correlations.append({
            "card_a": row[0],
            "card_b": row[1],
            "lift": row[2],
            "together_count": row[3],
            "name_a": row[4],
            "name_b": row[5],
        })
    
    return {"community_id": community_id, "correlations": correlations}


@router.get("/formats-with-communities")
def list_formats_with_communities(
    cursor = Depends(get_db_cursor),
):
    """
    List formats that have community data.
    """
    cursor.execute("""
        SELECT DISTINCT format_name 
        FROM card_communities 
        ORDER BY format_name
    """)
    
    return {"formats": [row[0] for row in cursor.fetchall()]}
