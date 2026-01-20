#!/usr/bin/env python3
"""
GEMP Card Correlation Analysis

Computes pairwise card correlations from deck data.
Identifies cards that appear together more often than chance would predict.

Correlations are computed per-patch (era), using only games from that patch's date range.

Usage:
    python compute_correlations.py                      # Compute for all patches and formats
    python compute_correlations.py --patch "V3 Release" # Specific patch only
    python compute_correlations.py --format "Expanded (PC)"  # Specific format
    python compute_correlations.py --min-appearances 100     # Higher threshold
    python compute_correlations.py --min-lift 1.5            # Only store high-lift pairs
    python compute_correlations.py --dry-run                 # Preview without inserting
"""

import argparse
import gc
import logging
import sys
from collections import defaultdict
from datetime import datetime, date
from itertools import combinations
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('./logs/correlations.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_card_sides(cursor) -> dict[str, str]:
    """
    Load card side mappings from card_catalog.
    Returns {blueprint: 'free_peoples'|'shadow'|None}
    """
    cursor.execute("""
        SELECT blueprint, side, culture 
        FROM card_catalog
    """)
    
    sides = {}
    for blueprint, side, culture in cursor.fetchall():
        sides[blueprint] = side
    
    return sides


def get_patches(cursor) -> list[dict]:
    """
    Load all patches ordered by date.
    Returns list of {id, patch_name, patch_date, start_date, end_date}
    where end_date is the day before the next patch (or None for latest).
    """
    cursor.execute("""
        SELECT id, patch_name, patch_date
        FROM balance_patches
        ORDER BY patch_date ASC
    """)
    
    rows = cursor.fetchall()
    if not rows:
        return []
    
    patches = []
    for i, (patch_id, name, patch_date) in enumerate(rows):
        # End date is day before next patch, or None if this is the latest
        if i + 1 < len(rows):
            next_patch_date = rows[i + 1][2]
            # end_date is inclusive, so day before next patch
            from datetime import timedelta
            end_date = next_patch_date - timedelta(days=1)
        else:
            end_date = None  # Latest patch - no end date
        
        patches.append({
            'id': patch_id,
            'patch_name': name,
            'patch_date': patch_date,
            'start_date': patch_date,
            'end_date': end_date,
        })
    
    return patches


def get_patch_by_name(cursor, patch_name: str) -> Optional[dict]:
    """Get a specific patch by name, with computed date range."""
    patches = get_patches(cursor)
    for patch in patches:
        if patch['patch_name'] == patch_name:
            return patch
    return None


def get_deck_cards_for_side(
    cursor, 
    format_name: str, 
    card_sides: dict, 
    target_side: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """
    Load deck data for a format, filtered to one side and optionally a date range.
    Uses chunked processing to avoid OOM on large formats.
    
    Args:
        cursor: Database cursor
        format_name: Format to query
        card_sides: Blueprint -> side mapping
        target_side: 'free_peoples' or 'shadow'
        start_date: Optional start of date range (inclusive)
        end_date: Optional end of date range (inclusive), None means up to today
    
    Returns:
        decks: {deck_id: set(blueprints)}
    
    deck_id is an integer for memory efficiency
    """
    # Build date filter clause
    date_filter = ""
    date_params = []
    if start_date:
        date_filter += " AND ga.game_date >= %s"
        date_params.append(start_date)
    if end_date:
        date_filter += " AND ga.game_date <= %s"
        date_params.append(end_date)
    
    # First get the game_id range for this format (with date filter)
    range_query = f"""
        SELECT MIN(game_id), MAX(game_id), COUNT(*)
        FROM game_analysis ga
        WHERE format_name = %s {date_filter}
    """
    cursor.execute(range_query, [format_name] + date_params)
    min_id, max_id, game_count = cursor.fetchone()
    
    if not min_id:
        return {}
    
    date_range_str = ""
    if start_date or end_date:
        date_range_str = f" (date range: {start_date or 'start'} to {end_date or 'now'})"
    logger.info(f"  Format has {game_count:,} games (IDs {min_id} to {max_id}){date_range_str}")
    
    decks = defaultdict(set)
    
    # Map (game_id, player_id) -> integer for memory efficiency
    deck_id_map = {}
    next_deck_id = 0
    
    # Process in chunks of 10000 games
    chunk_size = 10000
    current_min = min_id
    
    while current_min <= max_id:
        current_max = current_min + chunk_size
        
        chunk_query = f"""
            SELECT gdc.game_id, gdc.player_id, gdc.card_blueprint
            FROM game_deck_cards gdc
            JOIN game_analysis ga ON gdc.game_id = ga.game_id
            WHERE ga.format_name = %s
              AND gdc.card_role = 'draw_deck'
              AND ga.game_id >= %s
              AND ga.game_id < %s
              {date_filter}
        """
        cursor.execute(chunk_query, [format_name, current_min, current_max] + date_params)
        
        rows = cursor.fetchall()
        
        for game_id, player_id, blueprint in rows:
            side = card_sides.get(blueprint)
            if side != target_side:
                continue
                
            key = (game_id, player_id)
            if key not in deck_id_map:
                deck_id_map[key] = next_deck_id
                next_deck_id += 1
            deck_id = deck_id_map[key]
            
            decks[deck_id].add(blueprint)
        
        current_min = current_max
    
    del deck_id_map  # Free the mapping, no longer needed
    
    return dict(decks)


def compute_card_counts(decks: dict) -> dict[str, set]:
    """
    Compute which decks contain each card.
    
    Returns: {blueprint: set(deck_ids)}
    """
    card_to_decks = defaultdict(set)
    
    for deck_id, cards in decks.items():
        for card in cards:
            card_to_decks[card].add(deck_id)
    
    return dict(card_to_decks)


def compute_correlations(
    card_to_decks: dict[str, set],
    total_decks: int,
    min_appearances: int,
    min_lift: float,
):
    """
    Compute pairwise correlations for all card pairs.
    
    Yields batches of tuples:
        (card_a, card_b, together, a_count, b_count, total, jaccard, lift)
    """
    # Filter to cards meeting minimum appearance threshold
    filtered_cards = {
        card: decks 
        for card, decks in card_to_decks.items() 
        if len(decks) >= min_appearances
    }
    
    logger.info(f"  {len(filtered_cards)} cards meet min_appearances={min_appearances}")
    
    if len(filtered_cards) < 2:
        return
    
    cards = sorted(filtered_cards.keys())
    total_pairs = len(cards) * (len(cards) - 1) // 2
    
    logger.info(f"  Computing {total_pairs:,} card pairs...")
    
    batch = []
    batch_size = 10000
    processed = 0
    found = 0
    
    for i, card_a in enumerate(cards):
        decks_a = filtered_cards[card_a]
        a_count = len(decks_a)
        
        for card_b in cards[i+1:]:
            decks_b = filtered_cards[card_b]
            b_count = len(decks_b)
            
            # Intersection
            together = len(decks_a & decks_b)
            
            if together == 0:
                processed += 1
                continue
            
            # Jaccard: intersection / union
            union = a_count + b_count - together
            jaccard = together / union if union > 0 else 0
            
            # Lift: P(A∩B) / (P(A) × P(B))
            expected = (a_count * b_count) / total_decks
            lift = together / expected if expected > 0 else 0
            
            # Filter by minimum lift
            if lift >= min_lift:
                batch.append((
                    card_a, card_b, together, a_count, b_count,
                    total_decks, round(jaccard, 4), round(lift, 4)
                ))
                found += 1
                
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            
            processed += 1
            if processed % 500000 == 0:
                logger.info(f"    Processed {processed:,}/{total_pairs:,} pairs, found {found:,}...")
    
    # Yield remaining
    if batch:
        yield batch
    
    logger.info(f"  Found {found:,} correlations with lift >= {min_lift}")


def insert_correlations(
    cursor, 
    conn,
    format_name: str, 
    side: str,
    patch_id: int,
    correlation_batches,
    dry_run: bool = False
):
    """Insert correlation data into database from batch generator."""
    
    # Clear existing correlations for this format/side/patch
    if not dry_run:
        cursor.execute("""
            DELETE FROM card_correlations 
            WHERE format_name = %s AND side = %s AND patch_id = %s
        """, (format_name, side, patch_id))
        conn.commit()
    
    insert_sql = """
        INSERT INTO card_correlations (
            card_a, card_b, format_name, side, patch_id,
            together_count, card_a_count, card_b_count, total_decks,
            jaccard, lift, computed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """
    
    total_inserted = 0
    
    for batch in correlation_batches:
        if not batch:
            continue
            
        if dry_run:
            if total_inserted == 0:
                # Show top by lift from first batch
                sorted_corr = sorted(batch, key=lambda x: x[7], reverse=True)[:10]
                logger.info(f"  DRY RUN: Top correlations preview:")
                for c in sorted_corr:
                    logger.info(f"    {c[0]} + {c[1]}: lift={c[7]:.2f}, together={c[2]}")
            total_inserted += len(batch)
            continue
        
        data = [
            (c[0], c[1], format_name, side, patch_id, c[2], c[3], c[4], c[5], c[6], c[7])
            for c in batch
        ]
        cursor.executemany(insert_sql, data)
        conn.commit()
        
        total_inserted += len(batch)
        logger.info(f"    Inserted batch, total: {total_inserted:,} rows...")
    
    if dry_run:
        logger.info(f"  DRY RUN: Would insert {total_inserted:,} correlations")
    else:
        logger.info(f"  Inserted {total_inserted:,} correlations for {format_name} {side}")


def get_available_formats(cursor) -> list[str]:
    """Get list of formats with data."""
    cursor.execute("""
        SELECT DISTINCT format_name 
        FROM game_analysis 
        ORDER BY format_name
    """)
    return [row[0] for row in cursor.fetchall()]


def main():
    parser = argparse.ArgumentParser(description='GEMP Card Correlation Analysis')
    parser.add_argument('--format', type=str, help='Specific format to analyze')
    parser.add_argument('--patch', type=str, help='Specific patch/era to compute (default: all patches)')
    parser.add_argument('--min-appearances', type=int, default=50,
                        help='Minimum deck appearances for a card (default: 50)')
    parser.add_argument('--min-lift', type=float, default=1.2,
                        help='Minimum lift to store (default: 1.2)')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Preview without inserting')
    parser.add_argument('--config', default='config.ini', help='Config file path')
    args = parser.parse_args()
    
    # Load configuration
    config = Config(args.config)
    
    # Connect to database
    try:
        conn = mysql.connector.connect(
            host=config.db_host,
            port=config.db_port,
            user=config.db_user,
            password=config.db_password,
            database=config.db_name
        )
        cursor = conn.cursor()
        logger.info("Connected to database")
    except MySQLError as e:
        logger.error(f"Database connection failed: {e}")
        sys.exit(1)
    
    try:
        # Load patches
        if args.patch:
            patch = get_patch_by_name(cursor, args.patch)
            if not patch:
                logger.error(f"Patch '{args.patch}' not found in balance_patches")
                sys.exit(1)
            patches_to_process = [patch]
        else:
            patches_to_process = get_patches(cursor)
        
        if not patches_to_process:
            logger.error("No patches found in balance_patches table. "
                        "Please create at least one patch before computing correlations.")
            sys.exit(1)
        
        logger.info(f"Processing {len(patches_to_process)} patch(es)")
        
        # Load card side mappings
        card_sides = get_card_sides(cursor)
        logger.info(f"Loaded side info for {len(card_sides)} cards")
        
        # Determine formats to process
        if args.format:
            formats = [args.format]
        else:
            formats = get_available_formats(cursor)
        
        logger.info(f"Processing {len(formats)} formats")
        
        for patch in patches_to_process:
            patch_id = patch['id']
            patch_name = patch['patch_name']
            start_date = patch['start_date']
            end_date = patch['end_date']
            
            logger.info(f"\n{'='*60}")
            logger.info(f"PATCH: {patch_name} ({start_date} to {end_date or 'now'})")
            logger.info(f"{'='*60}")
            
            for format_name in formats:
                logger.info(f"\n=== Processing {format_name} ===")
                
                try:
                    # Process Free Peoples (load, compute, insert, free)
                    logger.info("Loading Free Peoples decks...")
                    fp_decks = get_deck_cards_for_side(
                        cursor, format_name, card_sides, 'free_peoples',
                        start_date, end_date
                    )
                    fp_deck_count = len(fp_decks)
                    logger.info(f"  Loaded {fp_deck_count} FP decks")
                    
                    if fp_decks:
                        logger.info("Computing Free Peoples correlations...")
                        fp_card_counts = compute_card_counts(fp_decks)
                        del fp_decks  # Free deck data before computing correlations

                        gc.collect()
                        
                        insert_correlations(
                            cursor, conn, format_name, 'free_peoples', patch_id,
                            compute_correlations(
                                fp_card_counts, fp_deck_count,
                                args.min_appearances, args.min_lift
                            ),
                            args.dry_run
                        )
                        del fp_card_counts
                        gc.collect()
                    else:
                        del fp_decks
                    
                    # Process Shadow (load, compute, insert, free)
                    logger.info("Loading Shadow decks...")
                    shadow_decks = get_deck_cards_for_side(
                        cursor, format_name, card_sides, 'shadow',
                        start_date, end_date
                    )
                    shadow_deck_count = len(shadow_decks)
                    logger.info(f"  Loaded {shadow_deck_count} Shadow decks")
                    
                    if shadow_decks:
                        logger.info("Computing Shadow correlations...")
                        shadow_card_counts = compute_card_counts(shadow_decks)
                        del shadow_decks  # Free deck data before computing correlations

                        gc.collect()
                        
                        insert_correlations(
                            cursor, conn, format_name, 'shadow', patch_id,
                            compute_correlations(
                                shadow_card_counts, shadow_deck_count,
                                args.min_appearances, args.min_lift
                            ),
                            args.dry_run
                        )
                        del shadow_card_counts
                        gc.collect()
                    else:
                        del shadow_decks
                    
                    logger.info(f"  Completed {format_name}")
                        
                except Exception as e:
                    logger.error(f"Error processing {format_name}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
        
        logger.info("\nCorrelation computation complete!")
    
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
