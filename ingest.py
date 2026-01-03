#!/usr/bin/env python3
"""
GEMP Game Analytics Ingestion Script

Reads JSON game summaries and populates analytics database tables.
Designed to be run as a daily cron job or manually for backfill.

Usage:
    python ingest.py                    # Process all unprocessed games
    python ingest.py --limit 1000       # Process up to 1000 games
    python ingest.py --dry-run          # Validate without inserting
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

from config import Config
from blueprint_normalizer import BlueprintNormalizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ingest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Processing version - increment when classification logic changes
PROCESSING_VERSION = 1

TARGET_FORMATS = frozenset([
    "Fellowship Block (PC)",
    "Movie Block (PC)",
    "Expanded (PC)",
    "Fellowship Block",
    "Movie Block",
    "Expanded",
    "Towers Standard",
    "Towers Block",
    "Limited - FOTR",
    "Limited - TTT",
    "Limited - ROTK",
    "Limited - WOTR",
    "Limited - TH",
])

DECISIVE_REASONS = frozenset([
    "Surviving to end of Regroup phase on site 9",
    "Surviving to Regroup phase on site 9",
    "The Ring-Bearer is corrupted by a card effect",
    "The Ring-Bearer is corrupted",
    "The Ring-Bearer is dead",
])

CONCESSION_REASONS = frozenset([
    "Concession",
    "Player decision timed-out",
    "Player run out of time",
])

AMBIGUOUS_REASONS = frozenset([
    "Corrupted before game started",
    "Bot got stuck on a decision",
    "Possible loop detected",
    "Invalid decision",
    "Game cancelled due to error",
    "Last remaining player in game",  # Catch-all, check other reason first
])


@dataclass
class GameRecord:
    """Represents a game from game_history that needs processing."""
    game_id: int
    winner: str
    loser: str
    winner_id: int
    loser_id: int
    win_recording_id: str
    lose_recording_id: str
    win_reason: str
    lose_reason: str
    format_name: str
    tournament: Optional[str]
    start_date: datetime
    end_date: datetime


@dataclass
class ProcessedGame:
    """Represents a fully processed game ready for insertion."""
    game_id: int
    format_name: str
    game_date: datetime
    duration_seconds: int
    tournament_name: Optional[str]
    winner_player_id: int
    loser_player_id: int
    outcome_tier: int
    competitive_tier: int
    winner_site: Optional[int]
    loser_site: Optional[int]
    winner_cards: list  # [(blueprint, role, count), ...]
    loser_cards: list
    played_blueprints: set  # Set of normalized blueprints that were actually played


def classify_outcome_tier(win_reason: str, lose_reason: str, winner_site: Optional[int]) -> int:
    """
    Classify game outcome reliability.
    
    Tier 1 (Decisive): Clear game-ending condition
    Tier 2 (Late Concession): Concession/timeout at site 6+
    Tier 3 (Ambiguous): Early quit, bot issues, unclear
    
    Checks both win_reason and lose_reason since "Last remaining player in game"
    is a catch-all that doesn't indicate why the game actually ended.
    """
    reasons = (win_reason, lose_reason)
    
    # Decisive takes priority - check both reasons
    if any(r in DECISIVE_REASONS for r in reasons):
        return 1
    
    # Concession - check both reasons
    if any(r in CONCESSION_REASONS for r in reasons):
        site = winner_site or 0
        return 2 if site >= 6 else 3
    
    # Ambiguous (includes "Last remaining player in game" as fallback)
    if any(r in AMBIGUOUS_REASONS for r in reasons):
        return 3
    
    # Unknown reason - log warning, default to ambiguous
    logger.warning(f"Unknown win/lose reasons: {win_reason} / {lose_reason}")
    return 3


def classify_competitive_tier(tournament_name: Optional[str], cursor) -> int:
    """
    Classify competitive context.
    
    Tier 1: Casual
    Tier 2: League
    Tier 3: Tournament
    Tier 4: Championship (tournament_id contains 'wc')
    """
    if not tournament_name or tournament_name.startswith("Casual"):
        return 1
    
    # Check tournaments first
    cursor.execute(
        "SELECT tournament_id FROM tournament WHERE name = %s LIMIT 1",
        (tournament_name,)
    )
    row = cursor.fetchone()
    if row:
        tournament_id = (row[0] or "").lower()
        if 'wc' in tournament_id:
            return 4
        return 3
    
    # Check leagues
    cursor.execute(
        "SELECT 1 FROM league WHERE name = %s LIMIT 1",
        (tournament_name,)
    )
    if cursor.fetchone():
        return 2
    
    logger.warning(f"Unknown tournament type: {tournament_name}")
    return 1


def extract_deck_cards(deck_data: dict, normalizer: BlueprintNormalizer) -> list:
    """
    Extract and normalize cards from deck data.
    
    Returns list of (card_blueprint, card_role, count) tuples.
    """
    cards = []
    
    # Draw deck - count duplicates
    draw_deck = deck_data.get('drawDeck', [])
    draw_counts = Counter(draw_deck)
    for card_id, count in draw_counts.items():
        normalized = normalizer.normalize(card_id)
        cards.append((normalized, 'draw_deck', count))
    
    # Sites (adventure deck)
    for card_id in deck_data.get('adventureDeck', []):
        normalized = normalizer.normalize(card_id)
        cards.append((normalized, 'site', 1))
    
    # Ring-bearer
    ring_bearer = deck_data.get('ringBearer')
    if ring_bearer:
        normalized = normalizer.normalize(ring_bearer)
        cards.append((normalized, 'ring_bearer', 1))
    
    # Ring
    ring = deck_data.get('ring')
    if ring:
        normalized = normalizer.normalize(ring)
        cards.append((normalized, 'ring', 1))
    
    return cards


def extract_played_blueprints(summary: dict, normalizer: BlueprintNormalizer) -> set:
    """
    Extract normalized blueprints of cards that were actually played.
    
    playedCards contains indices into allCards.
    
    NOTE: Until MetadataVersion >= 3, attachments may be undercounted due to
    a bug where Attached zone cards weren't added to playedCards.
    """
    all_cards = summary.get('allCards', {})
    played_indices = summary.get('playedCards', [])
    
    played_blueprints = set()
    for idx in played_indices:
        # allCards keys are strings
        blueprint = all_cards.get(str(idx))
        if blueprint:
            played_blueprints.add(normalizer.normalize(blueprint))
    
    return played_blueprints


def construct_summary_path(game: GameRecord, base_path: Path) -> Path:
    """
    Construct path to JSON summary file.
    
    Format: /replay/summaries/YYYY/MM/{winner}_vs_{loser}_{win_id}_{lose_id}.json
    """
    year = game.start_date.strftime('%Y')
    month = game.start_date.strftime('%m')
    filename = f"{game.winner}_vs_{game.loser}_{game.win_recording_id}_{game.lose_recording_id}.json"
    
    return base_path / "summaries" / year / month / filename


def load_summary(path: Path) -> Optional[dict]:
    """Load and validate JSON summary file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate metadata version
        if data.get('MetadataVersion', data.get('metadataVersion', 0)) < 2:
            logger.debug(f"Skipping {path}: MetadataVersion < 2")
            return None
        
        return data
    
    except json.JSONDecodeError as e:
        logger.warning(f"Malformed JSON in {path}: {e}")
        return None
    except FileNotFoundError:
        logger.warning(f"Summary file not found: {path}")
        return None
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        return None


def get_unprocessed_games(cursor, limit: Optional[int] = 500) -> list:
    """
    Query game_history for games not yet in game_analysis.
    Filters to target formats.
    """
    format_placeholders = ','.join(['%s'] * len(TARGET_FORMATS))
    
    query = f"""
        SELECT 
            gh.id,
            gh.winner,
            gh.loser,
            gh.winnerId,
            gh.loserId,
            gh.win_recording_id,
            gh.lose_recording_id,
            gh.win_reason,
            gh.lose_reason,
            gh.format_name,
            gh.tournament,
            gh.start_date,
            gh.end_date
        FROM game_history gh
        LEFT JOIN game_analysis ga ON gh.id = ga.game_id
        WHERE ga.game_id IS NULL
          AND gh.format_name IN ({format_placeholders})
          AND gh.win_recording_id IS NOT NULL
          AND gh.lose_recording_id IS NOT NULL
        ORDER BY gh.start_date ASC
    """
    
    if limit:
        query += f" LIMIT {int(limit)}"
    
    cursor.execute(query, tuple(TARGET_FORMATS))
    
    games = []
    for row in cursor.fetchall():
        games.append(GameRecord(
            game_id=row[0],
            winner=row[1],
            loser=row[2],
            winner_id=row[3],
            loser_id=row[4],
            win_recording_id=row[5],
            lose_recording_id=row[6],
            win_reason=row[7],
            lose_reason=row[8],
            format_name=row[9],
            tournament=row[10],
            start_date=row[11],
            end_date=row[12],
        ))
    
    return games


def process_game(
    game: GameRecord,
    summary: dict,
    normalizer: BlueprintNormalizer,
    cursor
) -> Optional[ProcessedGame]:
    """
    Process a single game into analytics format.
    Returns None if processing fails.
    """
    try:
        replay_info = summary.get('gameReplayInfo', {})
        decks = summary.get('decks', {})
        
        # Extract site info
        winner_site = replay_info.get('winner_site')
        loser_site = replay_info.get('loser_site')
        
        # Calculate duration
        duration_seconds = None
        if game.end_date and game.start_date:
            delta = game.end_date - game.start_date
            duration_seconds = int(delta.total_seconds())
        
        # Classify tiers
        outcome_tier = classify_outcome_tier(game.win_reason, game.lose_reason, winner_site)
        competitive_tier = classify_competitive_tier(game.tournament, cursor)
        
        # Extract deck cards
        winner_deck = decks.get(game.winner, {})
        loser_deck = decks.get(game.loser, {})
        
        winner_cards = extract_deck_cards(winner_deck, normalizer)
        loser_cards = extract_deck_cards(loser_deck, normalizer)
        
        if not winner_cards and not loser_cards:
            logger.warning(f"Game {game.game_id}: No deck data found")
            return None
        
        # Extract played cards (which blueprints actually saw play)
        played_blueprints = extract_played_blueprints(summary, normalizer)
        
        return ProcessedGame(
            game_id=game.game_id,
            format_name=game.format_name,
            game_date=game.start_date.date() if game.start_date else None,
            duration_seconds=duration_seconds,
            tournament_name=game.tournament,
            winner_player_id=game.winner_id,
            loser_player_id=game.loser_id,
            outcome_tier=outcome_tier,
            competitive_tier=competitive_tier,
            winner_site=winner_site,
            loser_site=loser_site,
            winner_cards=winner_cards,
            loser_cards=loser_cards,
            played_blueprints=played_blueprints,
        )
    
    except Exception as e:
        logger.error(f"Error processing game {game.game_id}: {e}")
        return None


def insert_batch(conn, cursor, processed_games: list, dry_run: bool = False):
    """Insert a batch of processed games into the database."""
    if not processed_games:
        return
    
    if dry_run:
        logger.info(f"DRY RUN: Would insert {len(processed_games)} games")
        return
    
    try:
        # Insert game_analysis rows
        analysis_sql = """
            INSERT INTO game_analysis (
                game_id, format_name, game_date, duration_seconds,
                tournament_name, winner_player_id, loser_player_id,
                outcome_tier, competitive_tier, winner_site, loser_site,
                processing_version, processed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
        """
        
        analysis_data = [
            (
                g.game_id, g.format_name, g.game_date, g.duration_seconds,
                g.tournament_name, g.winner_player_id, g.loser_player_id,
                g.outcome_tier, g.competitive_tier, g.winner_site, g.loser_site,
                PROCESSING_VERSION
            )
            for g in processed_games
        ]
        
        cursor.executemany(analysis_sql, analysis_data)
        
        # Insert game_deck_cards rows
        cards_sql = """
            INSERT INTO game_deck_cards (
                game_id, player_id, card_blueprint, card_role, card_count, is_winner, was_played
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        cards_data = []
        for g in processed_games:
            for blueprint, role, count in g.winner_cards:
                was_played = blueprint in g.played_blueprints
                cards_data.append((
                    g.game_id, g.winner_player_id, blueprint, role, count, True, was_played
                ))
            for blueprint, role, count in g.loser_cards:
                was_played = blueprint in g.played_blueprints
                cards_data.append((
                    g.game_id, g.loser_player_id, blueprint, role, count, False, was_played
                ))
        
        if cards_data:
            cursor.executemany(cards_sql, cards_data)
        
        conn.commit()
        logger.info(f"Inserted {len(processed_games)} games, {len(cards_data)} card rows")
    
    except MySQLError as e:
        conn.rollback()
        logger.error(f"Database error during batch insert: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description='GEMP Game Analytics Ingestion')
    parser.add_argument('--limit', type=int, help='Maximum games to process')
    parser.add_argument('--batch-size', type=int, default=500, help='Batch size for commits')
    parser.add_argument('--dry-run', action='store_true', help='Validate without inserting')
    parser.add_argument('--config', default='config.ini', help='Config file path')
    args = parser.parse_args()
    
    # Load configuration
    config = Config(args.config)
    
    # Initialize blueprint normalizer
    normalizer = BlueprintNormalizer(config.mapping_file)
    logger.info(f"Loaded {len(normalizer.mapping)} blueprint mappings")
    
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
        # Get unprocessed games
        games = get_unprocessed_games(cursor, args.limit)
        logger.info(f"Found {len(games)} unprocessed games in target formats")
        
        if not games:
            logger.info("No games to process")
            return
        
        # Process in batches
        processed_batch = []
        stats = {'processed': 0, 'skipped': 0, 'errors': 0}
        
        for i, game in enumerate(games):
            # Load summary file
            summary_path = construct_summary_path(game, Path(config.replay_base_path))
            summary = load_summary(summary_path)
            
            if summary is None:
                stats['skipped'] += 1
                continue
            
            # Process game
            processed = process_game(game, summary, normalizer, cursor)
            
            if processed is None:
                stats['errors'] += 1
                continue
            
            processed_batch.append(processed)
            stats['processed'] += 1
            
            # Commit batch
            if len(processed_batch) >= args.batch_size:
                insert_batch(conn, cursor, processed_batch, args.dry_run)
                processed_batch = []
            
            # Progress logging
            if (i + 1) % 1000 == 0:
                logger.info(f"Progress: {i + 1}/{len(games)} games checked")
        
        # Final batch
        if processed_batch:
            insert_batch(conn, cursor, processed_batch, args.dry_run)
        
        logger.info(
            f"Complete. Processed: {stats['processed']}, "
            f"Skipped: {stats['skipped']}, Errors: {stats['errors']}"
        )
    
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
