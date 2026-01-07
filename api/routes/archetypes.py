"""
Card community / archetype API endpoints.
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, Query, Header, HTTPException

from ..main import get_db_cursor, get_db

router = APIRouter(tags=["archetypes"])

# Admin key from environment
ADMIN_KEY = os.environ.get('GEMP_ANALYTICS_ADMIN_KEY', '')


def verify_admin(x_admin_key: Optional[str] = Header(None)):
    """Dependency to verify admin access."""
    if not ADMIN_KEY:
        raise HTTPException(status_code=500, detail="Admin key not configured")
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return True


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
            cc.is_orphan_pool,
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
    
    # Sort orphan pools last, then by card count
    query += " ORDER BY cc.is_orphan_pool ASC, cc.card_count DESC"
    
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
            "is_orphan_pool": row[9],
            "notes": row[10],
            "created_at": row[11].isoformat() if row[11] else None,
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
            cc.is_orphan_pool,
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
        "is_orphan_pool": row[9],
        "notes": row[10],
    }
    
    # Get member cards with names
    cursor.execute("""
        SELECT 
            ccm.card_blueprint,
            ccm.membership_score,
            ccm.is_core,
            ccm.membership_type,
            cat.card_name,
            cat.culture,
            cat.card_type,
            cat.image_url
        FROM card_community_members ccm
        LEFT JOIN card_catalog cat ON ccm.card_blueprint = cat.blueprint
        WHERE ccm.community_id = %s
        ORDER BY ccm.membership_type ASC, ccm.membership_score DESC
    """, (community_id,))
    
    members = []
    for row in cursor.fetchall():
        members.append({
            "blueprint": row[0],
            "membership_score": row[1],
            "is_core": row[2],
            "membership_type": row[3],
            "name": row[4],
            "culture": row[5],
            "card_type": row[6],
            "image_url": row[7],
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
    _admin = Depends(verify_admin),
):
    """
    Update community metadata (name, validity, notes).
    Requires admin key.
    """
    # Check if this is an orphan pool
    cursor.execute("""
        SELECT is_orphan_pool FROM card_communities WHERE id = %s
    """, (community_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    
    is_orphan_pool = row[0]
    
    # Orphan pool restrictions
    if is_orphan_pool:
        if is_valid is not None and not is_valid:
            raise HTTPException(status_code=400, detail="Cannot mark orphan pool as invalid")
    
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


@router.delete("/communities/{community_id}/reallocate")
def delete_and_reallocate(
    community_id: int,
    db = Depends(get_db),
    _admin = Depends(verify_admin),
):
    """
    Delete a community and reallocate its cards to best-fit communities.
    
    Cards are moved to their best-fit community if one is clearly better than
    alternatives (15% margin), otherwise they go to the orphan pool.
    
    Requires admin key.
    """
    conn, cursor = db
    
    # Get community info
    cursor.execute("""
        SELECT format_name, side, is_orphan_pool 
        FROM card_communities 
        WHERE id = %s
    """, (community_id,))
    
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    
    format_name, side, is_orphan_pool = row
    
    if is_orphan_pool:
        raise HTTPException(status_code=400, detail="Cannot delete the orphan pool")
    
    # Get cards from this community (only core cards - flex are just removed)
    cursor.execute("""
        SELECT card_blueprint FROM card_community_members 
        WHERE community_id = %s AND membership_type = 'core'
    """, (community_id,))
    cards_to_reallocate = [row[0] for row in cursor.fetchall()]
    
    if not cards_to_reallocate:
        # No core cards, just delete the community
        cursor.execute("DELETE FROM card_community_members WHERE community_id = %s", (community_id,))
        cursor.execute("DELETE FROM card_communities WHERE id = %s", (community_id,))
        conn.commit()
        return {"success": True, "deleted": True, "reallocated": 0, "orphaned": 0}
    
    # Get other communities for this format/side (excluding orphan pool for now)
    cursor.execute("""
        SELECT id, community_id FROM card_communities 
        WHERE format_name = %s AND side = %s AND id != %s AND is_orphan_pool = FALSE
    """, (format_name, side, community_id))
    other_communities = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Get core cards for each other community
    community_cores = {}
    for other_id in other_communities:
        cursor.execute("""
            SELECT card_blueprint FROM card_community_members 
            WHERE community_id = %s AND is_core = TRUE
        """, (other_id,))
        community_cores[other_id] = set(row[0] for row in cursor.fetchall())
    
    # Get or create orphan pool
    cursor.execute("""
        SELECT id FROM card_communities 
        WHERE format_name = %s AND side = %s AND is_orphan_pool = TRUE
    """, (format_name, side))
    orphan_row = cursor.fetchone()
    if orphan_row:
        orphan_pool_id = orphan_row[0]
    else:
        cursor.execute("""
            INSERT INTO card_communities 
                (format_name, side, community_id, card_count, avg_internal_lift, 
                 archetype_name, is_valid, is_orphan_pool)
            VALUES (%s, %s, -1, 0, 0, 'Orphaned Cards', TRUE, TRUE)
        """, (format_name, side))
        orphan_pool_id = cursor.lastrowid
    
    reallocated = 0
    orphaned = 0
    
    for card_bp in cards_to_reallocate:
        # Get correlations for this card with all other cards
        cursor.execute("""
            SELECT card_b, lift FROM card_correlations 
            WHERE format_name = %s AND side = %s AND card_a = %s
            UNION
            SELECT card_a, lift FROM card_correlations 
            WHERE format_name = %s AND side = %s AND card_b = %s
        """, (format_name, side, card_bp, format_name, side, card_bp))
        
        card_correlations = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Compute average lift to each community's core cards
        community_scores = {}
        for comm_id, core_cards in community_cores.items():
            if not core_cards:
                continue
            lifts = [card_correlations.get(core_card, 0) for core_card in core_cards]
            avg_lift = sum(lifts) / len(lifts) if lifts else 0
            if avg_lift > 0:
                community_scores[comm_id] = avg_lift
        
        # Find best fit with 15% margin
        best_community = None
        if community_scores:
            sorted_scores = sorted(community_scores.items(), key=lambda x: x[1], reverse=True)
            best_id, best_score = sorted_scores[0]
            
            # Check for clear winner (15% margin or only one option)
            if len(sorted_scores) == 1:
                best_community = best_id
            elif best_score > 0:
                second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0
                # 15% margin means best must be at least 1.15x the second
                if second_score == 0 or best_score >= second_score * 1.15:
                    best_community = best_id
        
        if best_community:
            # Check if already a member of target community
            cursor.execute("""
                SELECT community_id FROM card_community_members 
                WHERE community_id = %s AND card_blueprint = %s
            """, (best_community, card_bp))
            if cursor.fetchone():
                # Already exists, just count as reallocated (will be removed from source)
                reallocated += 1
            else:
                # Add as custom card to best community (manually reallocated)
                cursor.execute("""
                    INSERT INTO card_community_members 
                        (community_id, card_blueprint, membership_score, is_core, membership_type)
                    VALUES (%s, %s, %s, FALSE, 'custom')
                """, (best_community, card_bp, min(best_score / 5.0, 1.0)))
                reallocated += 1
        else:
            # Check if already in orphan pool
            cursor.execute("""
                SELECT community_id FROM card_community_members 
                WHERE community_id = %s AND card_blueprint = %s
            """, (orphan_pool_id, card_bp))
            if not cursor.fetchone():
                # Move to orphan pool
                cursor.execute("""
                    INSERT INTO card_community_members 
                        (community_id, card_blueprint, membership_score, is_core, membership_type)
                    VALUES (%s, %s, 0, FALSE, 'core')
                """, (orphan_pool_id, card_bp))
            orphaned += 1
    
    # Delete the original community and its members
    cursor.execute("DELETE FROM card_community_members WHERE community_id = %s", (community_id,))
    cursor.execute("DELETE FROM card_communities WHERE id = %s", (community_id,))
    
    # Update orphan pool card count
    cursor.execute("""
        UPDATE card_communities 
        SET card_count = (SELECT COUNT(*) FROM card_community_members WHERE community_id = %s)
        WHERE id = %s
    """, (orphan_pool_id, orphan_pool_id))
    
    conn.commit()
    
    return {
        "success": True,
        "deleted": True,
        "reallocated": reallocated,
        "orphaned": orphaned,
        "total_cards": len(cards_to_reallocate)
    }


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


@router.get("/card-communities/{blueprint}")
def get_card_community_associations(
    blueprint: str,
    format_name: str = Query(..., description="Format to query"),
    exclude_community_id: Optional[int] = Query(None, description="Exclude this community (the one we're viewing)"),
    limit: int = Query(5, description="Max communities to return"),
    cursor = Depends(get_db_cursor),
):
    """
    Get communities this card is associated with (via correlations with their members).
    
    Returns top N communities where this card correlates strongly with community members,
    even if the card isn't officially in that community.
    """
    # Get the card's side first
    cursor.execute("""
        SELECT side FROM card_catalog WHERE blueprint = %s
    """, (blueprint,))
    row = cursor.fetchone()
    if not row:
        return {"blueprint": blueprint, "communities": []}
    
    card_side = row[0]
    
    # Find communities where this card has high average lift with members
    # We calculate: for each community, average lift between this card and community members
    query = """
        SELECT 
            cc.id,
            cc.community_id,
            cc.archetype_name,
            cc.card_count,
            COUNT(DISTINCT ccm.card_blueprint) as connected_cards,
            AVG(corr.lift) as avg_lift,
            MAX(corr.lift) as max_lift
        FROM card_communities cc
        JOIN card_community_members ccm ON cc.id = ccm.community_id
        LEFT JOIN card_correlations corr ON (
            corr.format_name = cc.format_name
            AND corr.side = cc.side
            AND (
                (corr.card_a = %s AND corr.card_b = ccm.card_blueprint)
                OR (corr.card_b = %s AND corr.card_a = ccm.card_blueprint)
            )
        )
        WHERE cc.format_name = %s
          AND cc.side = %s
          AND cc.is_valid = TRUE
          AND corr.lift IS NOT NULL
    """
    params = [blueprint, blueprint, format_name, card_side]
    
    if exclude_community_id:
        query += " AND cc.id != %s"
        params.append(exclude_community_id)
    
    query += """
        GROUP BY cc.id, cc.community_id, cc.archetype_name, cc.card_count
        HAVING connected_cards >= 3
        ORDER BY avg_lift DESC
        LIMIT %s
    """
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    communities = []
    for row in rows:
        communities.append({
            "id": row[0],
            "community_id": row[1],
            "archetype_name": row[2],
            "card_count": row[3],
            "connected_cards": row[4],
            "avg_lift": round(row[5], 2) if row[5] else 0,
            "max_lift": round(row[6], 2) if row[6] else 0,
        })
    
    return {"blueprint": blueprint, "communities": communities}


@router.get("/card-memberships/{blueprint}")
def get_card_memberships(
    blueprint: str,
    format_name: str = Query(..., description="Format to query"),
    cursor = Depends(get_db_cursor),
):
    """
    Get all communities this card is currently a member of.
    """
    cursor.execute("""
        SELECT 
            cc.id,
            cc.community_id,
            cc.archetype_name,
            cc.side,
            cc.is_orphan_pool,
            ccm.membership_score,
            ccm.is_core,
            ccm.membership_type
        FROM card_community_members ccm
        JOIN card_communities cc ON ccm.community_id = cc.id
        WHERE ccm.card_blueprint = %s AND cc.format_name = %s
        ORDER BY ccm.membership_score DESC
    """, (blueprint, format_name))
    
    memberships = []
    for row in cursor.fetchall():
        memberships.append({
            "community_id": row[0],
            "community_num": row[1],
            "archetype_name": row[2],
            "side": row[3],
            "is_orphan_pool": row[4],
            "membership_score": row[5],
            "is_core": row[6],
            "membership_type": row[7],
        })
    
    return {"blueprint": blueprint, "format_name": format_name, "memberships": memberships}


@router.post("/communities/{community_id}/cards/{blueprint}")
def add_card_to_community(
    community_id: int,
    blueprint: str,
    membership_type: str = Query("flex", description="Type: flex or custom"),
    db = Depends(get_db),
    _admin = Depends(verify_admin),
):
    """
    Add a card to a community. Requires admin key.
    
    - flex: Card correlates with this archetype but wasn't assigned by Louvain
    - custom: Manually assigned by user
    """
    conn, cursor = db
    
    if membership_type not in ('flex', 'custom'):
        raise HTTPException(status_code=400, detail="membership_type must be 'flex' or 'custom'")
    
    # Check community exists
    cursor.execute("SELECT format_name, side FROM card_communities WHERE id = %s", (community_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    
    format_name, side = row
    
    # Check card exists and matches side
    cursor.execute("SELECT side FROM card_catalog WHERE blueprint = %s", (blueprint,))
    card_row = cursor.fetchone()
    if not card_row:
        raise HTTPException(status_code=404, detail="Card not found")
    if card_row[0] != side:
        raise HTTPException(status_code=400, detail=f"Card side ({card_row[0]}) doesn't match community side ({side})")
    
    # Check if already a member
    cursor.execute("""
        SELECT community_id, membership_type FROM card_community_members 
        WHERE community_id = %s AND card_blueprint = %s
    """, (community_id, blueprint))
    existing = cursor.fetchone()
    
    if existing:
        # Already exists - update membership type if different
        if existing[1] != membership_type:
            cursor.execute("""
                UPDATE card_community_members 
                SET membership_type = %s
                WHERE community_id = %s AND card_blueprint = %s
            """, (membership_type, community_id, blueprint))
            conn.commit()
            return {"success": True, "membership_score": None, "updated": True}
        else:
            # Already exists with same type - just succeed
            return {"success": True, "membership_score": None, "already_exists": True}
    
    # Calculate membership score based on correlations with community core cards
    cursor.execute("""
        SELECT ccm.card_blueprint FROM card_community_members ccm
        WHERE ccm.community_id = %s AND ccm.is_core = TRUE
    """, (community_id,))
    core_cards = [row[0] for row in cursor.fetchall()]
    
    if core_cards:
        placeholders = ','.join(['%s'] * len(core_cards))
        cursor.execute(f"""
            SELECT AVG(lift) FROM card_correlations
            WHERE format_name = %s AND side = %s
              AND ((card_a = %s AND card_b IN ({placeholders}))
                OR (card_b = %s AND card_a IN ({placeholders})))
        """, [format_name, side, blueprint] + core_cards + [blueprint] + core_cards)
        avg_lift = cursor.fetchone()[0] or 0
        membership_score = min(avg_lift / 5.0, 1.0)
    else:
        membership_score = 0.5  # Default for empty/orphan communities
    
    # Insert
    cursor.execute("""
        INSERT INTO card_community_members 
            (community_id, card_blueprint, membership_score, is_core, membership_type)
        VALUES (%s, %s, %s, FALSE, %s)
    """, (community_id, blueprint, membership_score, membership_type))
    
    # Update community card count
    cursor.execute("""
        UPDATE card_communities 
        SET card_count = (SELECT COUNT(*) FROM card_community_members WHERE community_id = %s)
        WHERE id = %s
    """, (community_id, community_id))
    
    conn.commit()
    
    return {"success": True, "membership_score": membership_score}


@router.delete("/communities/{community_id}/cards/{blueprint}")
def remove_card_from_community(
    community_id: int,
    blueprint: str,
    db = Depends(get_db),
    _admin = Depends(verify_admin),
):
    """
    Remove a card from a community. Requires admin key.
    
    - If card is core type, it gets moved to the orphan pool
    - If card is flex or custom type, it's simply removed
    """
    conn, cursor = db
    
    # Get community info
    cursor.execute("""
        SELECT format_name, side, is_orphan_pool FROM card_communities WHERE id = %s
    """, (community_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    
    format_name, side, is_orphan_pool = row
    
    # Get membership info
    cursor.execute("""
        SELECT membership_type FROM card_community_members 
        WHERE community_id = %s AND card_blueprint = %s
    """, (community_id, blueprint))
    member_row = cursor.fetchone()
    if not member_row:
        raise HTTPException(status_code=404, detail="Card not in this community")
    
    membership_type = member_row[0]
    moved_to_orphan = False
    
    # Remove from current community
    cursor.execute("""
        DELETE FROM card_community_members 
        WHERE community_id = %s AND card_blueprint = %s
    """, (community_id, blueprint))
    
    # If core card (and not already in orphan pool), move to orphan pool
    if membership_type == 'core' and not is_orphan_pool:
        # Get or create orphan pool
        cursor.execute("""
            SELECT id FROM card_communities 
            WHERE format_name = %s AND side = %s AND is_orphan_pool = TRUE
        """, (format_name, side))
        orphan_row = cursor.fetchone()
        
        if orphan_row:
            orphan_pool_id = orphan_row[0]
        else:
            cursor.execute("""
                INSERT INTO card_communities 
                    (format_name, side, community_id, card_count, avg_internal_lift, 
                     archetype_name, is_valid, is_orphan_pool)
                VALUES (%s, %s, -1, 0, 0, 'Orphaned Cards', TRUE, TRUE)
            """, (format_name, side))
            orphan_pool_id = cursor.lastrowid
        
        # Add to orphan pool
        cursor.execute("""
            INSERT INTO card_community_members 
                (community_id, card_blueprint, membership_score, is_core, membership_type)
            VALUES (%s, %s, 0, FALSE, 'core')
        """, (orphan_pool_id, blueprint))
        
        # Update orphan pool count
        cursor.execute("""
            UPDATE card_communities 
            SET card_count = (SELECT COUNT(*) FROM card_community_members WHERE community_id = %s)
            WHERE id = %s
        """, (orphan_pool_id, orphan_pool_id))
        
        moved_to_orphan = True
    
    # Update original community card count
    cursor.execute("""
        UPDATE card_communities 
        SET card_count = (SELECT COUNT(*) FROM card_community_members WHERE community_id = %s)
        WHERE id = %s
    """, (community_id, community_id))
    
    conn.commit()
    
    return {"success": True, "moved_to_orphan": moved_to_orphan}


@router.post("/communities/{target_community_id}/cards/{blueprint}/move")
def move_card_to_community(
    target_community_id: int,
    blueprint: str,
    source_community_id: int = Query(..., description="Community to move from"),
    as_custom: bool = Query(True, description="Mark as custom (manual assignment)"),
    db = Depends(get_db),
    _admin = Depends(verify_admin),
):
    """
    Move a card from one community to another. Requires admin key.
    
    The card will be marked as 'custom' type in the target community
    to indicate it was manually assigned.
    """
    conn, cursor = db
    
    if source_community_id == target_community_id:
        raise HTTPException(status_code=400, detail="Source and target communities are the same")
    
    # Get source community info
    cursor.execute("""
        SELECT format_name, side FROM card_communities WHERE id = %s
    """, (source_community_id,))
    source_row = cursor.fetchone()
    if not source_row:
        raise HTTPException(status_code=404, detail="Source community not found")
    
    format_name, side = source_row
    
    # Verify target community exists and matches
    cursor.execute("""
        SELECT format_name, side FROM card_communities WHERE id = %s
    """, (target_community_id,))
    target_row = cursor.fetchone()
    if not target_row:
        raise HTTPException(status_code=404, detail="Target community not found")
    if target_row[0] != format_name or target_row[1] != side:
        raise HTTPException(status_code=400, detail="Target community must be same format and side")
    
    # Verify card is in source community
    cursor.execute("""
        SELECT membership_score FROM card_community_members 
        WHERE community_id = %s AND card_blueprint = %s
    """, (source_community_id, blueprint))
    member_row = cursor.fetchone()
    if not member_row:
        raise HTTPException(status_code=404, detail="Card not in source community")
    
    old_score = member_row[0]
    
    # Check if already in target
    cursor.execute("""
        SELECT community_id FROM card_community_members 
        WHERE community_id = %s AND card_blueprint = %s
    """, (target_community_id, blueprint))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="Card already in target community")
    
    # Remove from source
    cursor.execute("""
        DELETE FROM card_community_members 
        WHERE community_id = %s AND card_blueprint = %s
    """, (source_community_id, blueprint))
    
    # Calculate new membership score for target
    cursor.execute("""
        SELECT ccm.card_blueprint FROM card_community_members ccm
        WHERE ccm.community_id = %s AND ccm.is_core = TRUE
    """, (target_community_id,))
    core_cards = [row[0] for row in cursor.fetchall()]
    
    if core_cards:
        placeholders = ','.join(['%s'] * len(core_cards))
        cursor.execute(f"""
            SELECT AVG(lift) FROM card_correlations
            WHERE format_name = %s AND side = %s
              AND ((card_a = %s AND card_b IN ({placeholders}))
                OR (card_b = %s AND card_a IN ({placeholders})))
        """, [format_name, side, blueprint] + core_cards + [blueprint] + core_cards)
        avg_lift = cursor.fetchone()[0] or 0
        membership_score = min(avg_lift / 5.0, 1.0)
    else:
        membership_score = old_score  # Preserve if no core cards
    
    # Add to target
    new_type = 'custom' if as_custom else 'flex'
    cursor.execute("""
        INSERT INTO card_community_members 
            (community_id, card_blueprint, membership_score, is_core, membership_type)
        VALUES (%s, %s, %s, FALSE, %s)
    """, (target_community_id, blueprint, membership_score, new_type))
    
    # Update both community counts
    cursor.execute("""
        UPDATE card_communities 
        SET card_count = (SELECT COUNT(*) FROM card_community_members WHERE community_id = %s)
        WHERE id = %s
    """, (source_community_id, source_community_id))
    
    cursor.execute("""
        UPDATE card_communities 
        SET card_count = (SELECT COUNT(*) FROM card_community_members WHERE community_id = %s)
        WHERE id = %s
    """, (target_community_id, target_community_id))
    
    conn.commit()
    
    return {"success": True, "new_membership_score": membership_score}


@router.get("/search-cards")
def search_cards_in_communities(
    format_name: str = Query(..., description="Format to query"),
    query: str = Query(..., min_length=3, description="Search query (min 3 chars)"),
    cursor = Depends(get_db_cursor),
):
    """
    Search for cards by name within a format and return which communities they belong to.
    
    Returns cards matching the query and their core community membership.
    Case-insensitive and accent-insensitive search.
    """
    search_term = f"%{query}%"
    
    # Find cards matching the query that are core members of communities in this format
    # Use COLLATE for case and accent insensitive search
    cursor.execute("""
        SELECT DISTINCT
            cat.blueprint,
            cat.card_name,
            cat.side,
            cc.id as community_id,
            cc.archetype_name,
            cc.is_orphan_pool
        FROM card_catalog cat
        JOIN card_community_members ccm ON cat.blueprint = ccm.card_blueprint
        JOIN card_communities cc ON ccm.community_id = cc.id
        WHERE cc.format_name = %s
          AND cc.is_valid = TRUE
          AND ccm.membership_type = 'core'
          AND cat.card_name COLLATE utf8mb4_unicode_ci LIKE %s COLLATE utf8mb4_unicode_ci
        ORDER BY cat.card_name
        LIMIT 50
    """, (format_name, search_term))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "blueprint": row[0],
            "name": row[1],
            "side": row[2],
            "community_id": row[3],
            "archetype_name": row[4],
            "is_orphan_pool": row[5],
        })
    
    return {"query": query, "format_name": format_name, "results": results}
