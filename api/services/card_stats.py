"""
Card statistics service - queries pre-computed stats.
"""

from datetime import date
from typing import Optional

from ..models import CardStats, FormatCardStats


def build_stats_query(
    format_name: str,
    start_date: Optional[date],
    end_date: Optional[date],
    outcome_tiers: Optional[list[int]],
    competitive_tiers: Optional[list[int]],
    min_games: int,
    patch_date: Optional[date],
) -> tuple[str, list]:
    """
    Build SQL query for card stats with filters.
    
    Returns (sql, params) tuple.
    """
    conditions = ["format_name = %s"]
    params = [format_name]
    
    # Date range - patch_date overrides start_date
    if patch_date:
        conditions.append("stat_date >= %s")
        params.append(patch_date)
    elif start_date:
        conditions.append("stat_date >= %s")
        params.append(start_date)
    
    if end_date:
        conditions.append("stat_date <= %s")
        params.append(end_date)
    
    # Tier filters
    if outcome_tiers:
        placeholders = ','.join(['%s'] * len(outcome_tiers))
        conditions.append(f"outcome_tier IN ({placeholders})")
        params.extend(outcome_tiers)
    
    if competitive_tiers:
        placeholders = ','.join(['%s'] * len(competitive_tiers))
        conditions.append(f"competitive_tier IN ({placeholders})")
        params.extend(competitive_tiers)
    
    where_clause = " AND ".join(conditions)
    
    # Aggregate across all matching days and tier combinations
    sql = f"""
        SELECT 
            card_blueprint,
            SUM(deck_appearances) as games,
            SUM(total_copies) as copies,
            SUM(deck_wins) as wins,
            SUM(played_appearances) as played_games,
            SUM(played_wins) as played_wins
        FROM card_stats_daily
        WHERE {where_clause}
        GROUP BY card_blueprint
        HAVING SUM(deck_appearances) >= %s
    """
    params.append(min_games)
    
    return sql, params


def fetch_card_stats(
    cursor,
    format_name: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    outcome_tiers: Optional[list[int]] = None,
    competitive_tiers: Optional[list[int]] = None,
    min_games: int = 10,
    patch_date: Optional[date] = None,
    sort: str = 'priority',
    limit: int = 100,
) -> list[CardStats]:
    """
    Fetch aggregated card stats from pre-computed daily table.
    """
    sql, params = build_stats_query(
        format_name, start_date, end_date, 
        outcome_tiers, competitive_tiers, min_games, patch_date
    )
    
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    
    # Process into CardStats objects
    results = []
    for row in rows:
        blueprint, games, copies, wins, played_games, played_wins = row
        
        inclusion_wr = wins / games if games > 0 else 0.0
        played_wr = played_wins / played_games if played_games > 0 else None
        priority = games * (inclusion_wr - 0.5)
        
        results.append(CardStats(
            blueprint=blueprint,
            name=None,  # Would need card_catalog lookup
            games=games,
            copies=copies,
            inclusion_wr=round(inclusion_wr, 4),
            played_games=played_games,
            played_wr=round(played_wr, 4) if played_wr is not None else None,
            priority=round(priority, 2),
        ))
    
    # Sort
    if sort == 'priority':
        # Sort by absolute priority (distance from 50% matters, either direction)
        results.sort(key=lambda x: abs(x.priority), reverse=True)
    elif sort == 'winrate':
        results.sort(key=lambda x: x.inclusion_wr, reverse=True)
    elif sort == 'games':
        results.sort(key=lambda x: x.games, reverse=True)
    
    return results[:limit]


def fetch_card_stats_multi_format(
    cursor,
    formats: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    outcome_tiers: Optional[list[int]] = None,
    competitive_tiers: Optional[list[int]] = None,
    min_games: int = 10,
) -> dict[str, dict[str, FormatCardStats]]:
    """
    Fetch card stats for multiple formats, keyed by blueprint then format.
    
    Returns: {blueprint: {format_name: FormatCardStats}}
    """
    result = {}
    
    for format_name in formats:
        stats = fetch_card_stats(
            cursor, format_name, start_date, end_date,
            outcome_tiers, competitive_tiers, min_games,
            sort='games', limit=10000  # Get all cards
        )
        
        for card in stats:
            if card.blueprint not in result:
                result[card.blueprint] = {}
            
            result[card.blueprint][format_name] = FormatCardStats(
                games=card.games,
                copies=card.copies,
                inclusion_wr=card.inclusion_wr,
                played_games=card.played_games,
                played_wr=card.played_wr,
                priority=card.priority,
            )
    
    return result
