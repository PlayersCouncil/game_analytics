#!/usr/bin/env python3
"""
GEMP Game Analytics Pre-computation Script

Aggregates raw game_deck_cards data into card_stats_daily for fast API queries.
Designed to be run daily via cron or triggered manually.

Usage:
    python precompute.py                      # Compute stats for yesterday
    python precompute.py --date 2024-01-15    # Compute stats for specific date
    python precompute.py --rebuild            # Full rebuild of all stats
    python precompute.py --dry-run            # Show what would be computed
"""

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('precompute.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def log_computation_start(cursor, computation_type: str) -> int:
    """Log the start of a computation job, return log ID."""
    cursor.execute("""
        INSERT INTO stats_computation_log (computation_type, started_at, status)
        VALUES (%s, NOW(), 'running')
    """, (computation_type,))
    return cursor.lastrowid


def log_computation_end(cursor, log_id: int, records: int, status: str, error: str = None):
    """Log the completion of a computation job."""
    cursor.execute("""
        UPDATE stats_computation_log 
        SET completed_at = NOW(), records_processed = %s, status = %s, error_message = %s
        WHERE id = %s
    """, (records, status, error, log_id))


def compute_daily_stats(cursor, target_date: date, dry_run: bool = False) -> int:
    """
    Compute card stats for a specific date.
    
    Returns number of rows upserted.
    """
    logger.info(f"Computing stats for {target_date}")
    
    # Aggregate query - groups by card, format, date, and both tier dimensions
    aggregate_sql = """
        SELECT 
            gdc.card_blueprint,
            ga.format_name,
            ga.game_date,
            ga.outcome_tier,
            ga.competitive_tier,
            COUNT(*) as deck_appearances,
            SUM(CASE WHEN gdc.is_winner THEN 1 ELSE 0 END) as deck_wins,
            SUM(gdc.card_count) as total_copies,
            SUM(CASE WHEN gdc.was_played THEN 1 ELSE 0 END) as played_appearances,
            SUM(CASE WHEN gdc.was_played AND gdc.is_winner THEN 1 ELSE 0 END) as played_wins
        FROM game_deck_cards gdc
        JOIN game_analysis ga ON gdc.game_id = ga.game_id
        WHERE ga.game_date = %s
        GROUP BY gdc.card_blueprint, ga.format_name, ga.game_date, ga.outcome_tier, ga.competitive_tier
    """
    
    cursor.execute(aggregate_sql, (target_date,))
    rows = cursor.fetchall()
    
    if dry_run:
        logger.info(f"DRY RUN: Would upsert {len(rows)} stat rows for {target_date}")
        return len(rows)
    
    if not rows:
        logger.info(f"No games found for {target_date}")
        return 0
    
    # Upsert into card_stats_daily
    upsert_sql = """
        INSERT INTO card_stats_daily (
            card_blueprint, format_name, stat_date, outcome_tier, competitive_tier,
            deck_appearances, deck_wins, total_copies,
            played_appearances, played_wins
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            deck_appearances = VALUES(deck_appearances),
            deck_wins = VALUES(deck_wins),
            total_copies = VALUES(total_copies),
            played_appearances = VALUES(played_appearances),
            played_wins = VALUES(played_wins)
    """
    
    cursor.executemany(upsert_sql, rows)
    logger.info(f"Upserted {len(rows)} stat rows for {target_date}")
    
    return len(rows)


def get_all_game_dates(cursor) -> list:
    """Get all distinct game dates from game_analysis."""
    cursor.execute("SELECT DISTINCT game_date FROM game_analysis ORDER BY game_date")
    return [row[0] for row in cursor.fetchall()]


def rebuild_all_stats(conn, cursor, dry_run: bool = False) -> int:
    """
    Full rebuild of all daily stats.
    
    Clears card_stats_daily and recomputes from scratch.
    """
    logger.info("Starting full rebuild of card_stats_daily")
    
    if not dry_run:
        cursor.execute("DELETE FROM card_stats_daily")
        logger.info("Cleared existing stats")
    
    dates = get_all_game_dates(cursor)
    logger.info(f"Found {len(dates)} dates to process")
    
    total_rows = 0
    for i, target_date in enumerate(dates):
        rows = compute_daily_stats(cursor, target_date, dry_run)
        total_rows += rows
        
        # Commit periodically to avoid long transactions
        if not dry_run and (i + 1) % 30 == 0:
            conn.commit()
            logger.info(f"Progress: {i + 1}/{len(dates)} dates processed")
    
    if not dry_run:
        conn.commit()
    
    logger.info(f"Full rebuild complete. Total rows: {total_rows}")
    return total_rows


def main():
    parser = argparse.ArgumentParser(description='GEMP Analytics Pre-computation')
    parser.add_argument('--date', type=str, help='Specific date to compute (YYYY-MM-DD)')
    parser.add_argument('--rebuild', action='store_true', help='Full rebuild of all stats')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be computed')
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
        if args.rebuild:
            # Full rebuild
            computation_type = 'full_rebuild'
            log_id = None
            if not args.dry_run:
                log_id = log_computation_start(cursor, computation_type)
                conn.commit()
            
            try:
                total_rows = rebuild_all_stats(conn, cursor, args.dry_run)
                if log_id:
                    log_computation_end(cursor, log_id, total_rows, 'completed')
                    conn.commit()
            except Exception as e:
                if log_id:
                    log_computation_end(cursor, log_id, 0, 'failed', str(e))
                    conn.commit()
                raise
        
        else:
            # Single day computation
            if args.date:
                target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
            else:
                # Default to yesterday
                target_date = date.today() - timedelta(days=1)
            
            computation_type = 'daily'
            log_id = None
            if not args.dry_run:
                log_id = log_computation_start(cursor, computation_type)
                conn.commit()
            
            try:
                rows = compute_daily_stats(cursor, target_date, args.dry_run)
                if not args.dry_run:
                    conn.commit()
                if log_id:
                    log_computation_end(cursor, log_id, rows, 'completed')
                    conn.commit()
            except Exception as e:
                if log_id:
                    log_computation_end(cursor, log_id, 0, 'failed', str(e))
                    conn.commit()
                raise
    
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
