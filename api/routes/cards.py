"""
Card statistics endpoints.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Depends

from ..models import CardStatsResponse, CardCompareResponse, DateRange, CompareCardStats
from ..services import fetch_card_stats, fetch_card_stats_multi_format, get_patch_by_name
from ..main import get_db_cursor

router = APIRouter(prefix="/stats", tags=["cards"])


def parse_tier_list(tier_str: Optional[str]) -> Optional[list[int]]:
    """Parse comma-separated tier list into integers."""
    if not tier_str:
        return None
    try:
        return [int(t.strip()) for t in tier_str.split(',')]
    except ValueError:
        raise HTTPException(400, "Invalid tier format. Use comma-separated integers (e.g., '1,2')")


@router.get("/cards", response_model=CardStatsResponse)
def get_card_stats(
    format: str = Query(..., description="Format name (e.g., 'Movie Block (PC)')"),
    start: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    patch: Optional[str] = Query(None, description="Patch name (overrides start date)"),
    min_games: int = Query(10, ge=1, description="Minimum games for inclusion"),
    sort: str = Query('priority', regex='^(priority|winrate|games)$'),
    limit: int = Query(100, ge=1, le=5000),
    outcome_tier: Optional[str] = Query(None, description="Outcome tiers (comma-separated: 1,2,3)"),
    competitive_tier: Optional[str] = Query(None, description="Competitive tiers (comma-separated: 1,2,3,4)"),
    cursor = Depends(get_db_cursor),
):
    """
    Get card statistics for a format.
    
    - **format**: Required. The game format to query.
    - **start/end**: Date range filter.
    - **patch**: If provided, uses patch date as start date.
    - **outcome_tier**: Filter by outcome reliability (1=Decisive, 2=Late Concession, 3=Ambiguous)
    - **competitive_tier**: Filter by competitive level (1=Casual, 2=League, 3=Tournament, 4=Championship)
    - **sort**: 'priority' (default, by impact), 'winrate', or 'games'
    """
    outcome_tiers = parse_tier_list(outcome_tier)
    competitive_tiers = parse_tier_list(competitive_tier)
    
    # Resolve patch to date if provided
    patch_date = None
    if patch:
        patch_obj = get_patch_by_name(cursor, patch)
        if not patch_obj:
            raise HTTPException(404, f"Patch '{patch}' not found")
        patch_date = patch_obj.patch_date
    
    cards = fetch_card_stats(
        cursor,
        format_name=format,
        start_date=start,
        end_date=end,
        outcome_tiers=outcome_tiers,
        competitive_tiers=competitive_tiers,
        min_games=min_games,
        patch_date=patch_date,
        sort=sort,
        limit=limit,
    )
    
    return CardStatsResponse(
        format=format,
        date_range=DateRange(start=patch_date or start, end=end),
        outcome_tiers=outcome_tiers,
        competitive_tiers=competitive_tiers,
        total_cards=len(cards),
        cards=cards,
    )


@router.get("/cards/compare", response_model=CardCompareResponse)
def compare_card_stats(
    formats: str = Query(..., description="Comma-separated format names"),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    min_games: int = Query(10, ge=1),
    outcome_tier: Optional[str] = Query(None),
    competitive_tier: Optional[str] = Query(None),
    cursor = Depends(get_db_cursor),
):
    """
    Compare card statistics across multiple formats.
    
    Returns cards that appear in at least one of the specified formats.
    """
    format_list = [f.strip() for f in formats.split(',')]
    if len(format_list) < 2:
        raise HTTPException(400, "At least 2 formats required for comparison")
    if len(format_list) > 5:
        raise HTTPException(400, "Maximum 5 formats for comparison")
    
    outcome_tiers = parse_tier_list(outcome_tier)
    competitive_tiers = parse_tier_list(competitive_tier)
    
    stats_by_card = fetch_card_stats_multi_format(
        cursor,
        formats=format_list,
        start_date=start,
        end_date=end,
        outcome_tiers=outcome_tiers,
        competitive_tiers=competitive_tiers,
        min_games=min_games,
    )
    
    cards = [
        CompareCardStats(
            blueprint=blueprint,
            name=None,
            stats=format_stats,
        )
        for blueprint, format_stats in stats_by_card.items()
    ]
    
    # Sort by total games across all formats
    cards.sort(key=lambda c: sum(s.games for s in c.stats.values()), reverse=True)
    
    return CardCompareResponse(
        date_range=DateRange(start=start, end=end),
        outcome_tiers=outcome_tiers,
        competitive_tiers=competitive_tiers,
        cards=cards[:500],  # Limit response size
    )


@router.get("/stats/summary")
def get_stats_summary(cursor = Depends(get_db_cursor)):
    """Public summary stats (no auth required)."""
    cursor.execute("SELECT COUNT(*) FROM game_analysis")
    total_games = cursor.fetchone()[0]
    
    return {"total_games": total_games}