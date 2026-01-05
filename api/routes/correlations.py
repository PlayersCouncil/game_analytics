"""
Card correlation API endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query

from ..main import get_db_cursor
from ..models import CorrelationResponse, CardCorrelation

router = APIRouter(tags=["correlations"])


@router.get("/correlations/{blueprint}", response_model=CorrelationResponse)
def get_card_correlations(
    blueprint: str,
    format_name: str = Query(..., description="Format to query"),
    side: Optional[str] = Query(None, description="Filter by side (free_peoples/shadow)"),
    min_lift: float = Query(1.5, description="Minimum lift threshold"),
    limit: int = Query(50, description="Maximum results"),
    cursor = Depends(get_db_cursor),
):
    """
    Get cards that correlate with a specific card.
    
    Returns cards sorted by lift (how much more often they appear together than chance).
    - lift > 1.0 means they appear together more than expected
    - lift = 1.0 means independent (no correlation)
    - lift < 1.0 means they appear together less than expected
    """
    # Query correlations where this card is either card_a or card_b
    query = """
        SELECT 
            CASE WHEN card_a = %s THEN card_b ELSE card_a END as correlated_card,
            together_count,
            CASE WHEN card_a = %s THEN card_a_count ELSE card_b_count END as target_count,
            CASE WHEN card_a = %s THEN card_b_count ELSE card_a_count END as correlated_count,
            total_decks,
            jaccard,
            lift,
            side
        FROM card_correlations
        WHERE format_name = %s
          AND (card_a = %s OR card_b = %s)
          AND lift >= %s
    """
    params = [blueprint, blueprint, blueprint, format_name, blueprint, blueprint, min_lift]
    
    if side:
        query += " AND side = %s"
        params.append(side)
    
    query += " ORDER BY lift DESC LIMIT %s"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    correlations = [
        CardCorrelation(
            blueprint=row[0],
            together_count=row[1],
            target_count=row[2],
            correlated_count=row[3],
            total_decks=row[4],
            jaccard=row[5],
            lift=row[6],
            side=row[7],
        )
        for row in rows
    ]
    
    return CorrelationResponse(
        target_blueprint=blueprint,
        format_name=format_name,
        correlations=correlations,
    )


@router.get("/correlations", response_model=CorrelationResponse)
def get_top_correlations(
    format_name: str = Query(..., description="Format to query"),
    side: str = Query(..., description="Side (free_peoples/shadow)"),
    min_lift: float = Query(2.0, description="Minimum lift threshold"),
    min_together: int = Query(20, description="Minimum times appearing together"),
    limit: int = Query(100, description="Maximum results"),
    cursor = Depends(get_db_cursor),
):
    """
    Get top correlated card pairs in a format.
    
    Useful for discovering potential archetypes.
    """
    cursor.execute("""
        SELECT 
            card_a,
            card_b,
            together_count,
            card_a_count,
            card_b_count,
            total_decks,
            jaccard,
            lift
        FROM card_correlations
        WHERE format_name = %s
          AND side = %s
          AND lift >= %s
          AND together_count >= %s
        ORDER BY lift DESC
        LIMIT %s
    """, (format_name, side, min_lift, min_together, limit))
    
    rows = cursor.fetchall()
    
    # Format as pairs
    correlations = [
        CardCorrelation(
            blueprint=f"{row[0]} + {row[1]}",  # Show as pair
            together_count=row[2],
            target_count=row[3],
            correlated_count=row[4],
            total_decks=row[5],
            jaccard=row[6],
            lift=row[7],
            side=side,
        )
        for row in rows
    ]
    
    return CorrelationResponse(
        target_blueprint=None,
        format_name=format_name,
        correlations=correlations,
    )
