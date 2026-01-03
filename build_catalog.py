#!/usr/bin/env python3
"""
Build card catalog from GEMP HJSON definitions and PC_Cards.js image mappings.

Usage:
    python build_catalog.py [--resources /path/to/gemp-resources] [--js /path/to/gemp-js]
    
Populates the card_catalog table with:
- Card metadata (name, culture, type, side, twilight) from HJSON
- Image URLs from PC_Cards.js or procedural generation for Decipher cards
"""

import argparse
import json
import hjson
import os
import re
import sys
from pathlib import Path

import mysql.connector

from config import get_db_config


# ---------------------------------------------------------------------------
# HJSON Parsing
# ---------------------------------------------------------------------------

def parse_hjson_file(filepath: Path) -> dict:
    """
    Parse an HJSON file into a dict of blueprint -> card data.
    
    HJSON is JSON with relaxed syntax:
    - Comments (// and /* */)
    - Unquoted keys
    - Trailing commas
    - Multi-line strings
    """
    content = filepath.read_text(encoding='utf-8')
        
    try:
        data = hjson.loads(content)
        return data
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse {filepath}: {e}", file=sys.stderr)
        return {}


def extract_card_info(blueprint_id: str, card_data: dict) -> dict:
    """Extract relevant fields from a card's HJSON data."""
    # Get set number from blueprint
    parts = blueprint_id.split('_')
    set_number = int(parts[0]) if parts else 0
    
    # Normalize side
    side_raw = card_data.get('side', '').lower().replace(' ', '_')
    if 'free' in side_raw:
        side = 'free_peoples'
    elif 'shadow' in side_raw:
        side = 'shadow'
    else:
        side = 'other'
    
    return {
        'blueprint': blueprint_id,
        'card_name': get_name(card_data),
        'culture': card_data.get('culture', ''),
        'card_type': card_data.get('type', ''),
        'side': side,
        'set_number': set_number,
    }
    
def get_name(card_data: dict) -> str:
    title = card_data.get('title', '')
    subtitle = card_data.get('subtitle', '')
    unique = card_data.get('unique', 'false')
    
    dots = ''
    
    if(unique == "3"):
        dots = "∴"
    elif(unique == "2"):
        dots = ":"
    elif(unique == "true" or unique == "1"):
        dots = "•"
        
    name = dots + title
    
    if(subtitle != ''):
        name += ", " + subtitle
        
    return name


def load_all_hjson(resources_path: Path) -> dict:
    """Load all HJSON files from the cards directory structure."""
    cards_dir = resources_path / 'cards'
    if not cards_dir.exists():
        print(f"Warning: Cards directory not found: {cards_dir}", file=sys.stderr)
        return {}
    
    all_cards = {}
    hjson_files = list(cards_dir.rglob('*.hjson'))
    print(f"Found {len(hjson_files)} HJSON files")
    
    for hjson_file in hjson_files:
        file_data = parse_hjson_file(hjson_file)
        for blueprint_id, card_data in file_data.items():
            if isinstance(card_data, dict):
                all_cards[blueprint_id] = extract_card_info(blueprint_id, card_data)
    
    print(f"Loaded {len(all_cards)} cards from HJSON")
    return all_cards


# ---------------------------------------------------------------------------
# Image URL Resolution
# ---------------------------------------------------------------------------

def parse_pc_cards_js(js_path: Path) -> dict:
    """
    Parse PC_Cards.js to extract blueprint -> image URL mappings.
    
    The file contains JavaScript objects like:
        var PCCards = {
            '103_113': 'https://i.lotrtcgpc.net/sets/v03/LOTR-ENV3S113.0_card.jpg',
            ...
        }
    """
    pc_cards_file = js_path / 'PC_Cards.js'
    if not pc_cards_file.exists():
        print(f"Warning: PC_Cards.js not found at {pc_cards_file}", file=sys.stderr)
        return {}
    
    content = pc_cards_file.read_text(encoding='utf-8')
    
    # Extract all 'blueprint': 'url' pairs
    # Pattern matches: '1_23': 'https://...'
    pattern = r"'(\d+_\d+)'\s*:\s*'([^']+)'"
    matches = re.findall(pattern, content)
    
    url_map = {blueprint: url for blueprint, url in matches}
    print(f"Loaded {len(url_map)} image URLs from PC_Cards.js")
    return url_map


def generate_decipher_url(blueprint_id: str) -> str:
    """
    Generate procedural URL for Decipher cards.
    
    Format: https://i.lotrtcgpc.net/decipher/LOTR{set:02d}{card:03d}.jpg
    Example: 5_10 -> https://i.lotrtcgpc.net/decipher/LOTR05010.jpg
    """
    parts = blueprint_id.split('_')
    if len(parts) != 2:
        return ''
    
    try:
        set_no = int(parts[0])
        card_no = int(parts[1])
    except ValueError:
        return ''
    
    # V-cards (set >= 100) shouldn't use procedural URLs
    if set_no >= 100:
        return ''
    
    return f"https://i.lotrtcgpc.net/decipher/LOTR{set_no:02d}{card_no:03d}.jpg"


def resolve_image_urls(cards: dict, pc_cards_urls: dict) -> dict:
    """Add image_url to each card, using PC_Cards.js or procedural generation."""
    for blueprint, card_info in cards.items():
        if blueprint in pc_cards_urls:
            card_info['image_url'] = pc_cards_urls[blueprint]
        else:
            card_info['image_url'] = generate_decipher_url(blueprint)
    
    return cards


# ---------------------------------------------------------------------------
# Database Operations
# ---------------------------------------------------------------------------

def upsert_catalog(cards: dict):
    """Insert or update cards in the card_catalog table."""
    config = get_db_config()
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    
    # Upsert each card
    upsert_sql = """
        INSERT INTO card_catalog 
            (blueprint, card_name, culture, card_type, side, set_number, image_url)
        VALUES 
            (%(blueprint)s, %(card_name)s, %(culture)s, %(card_type)s, 
             %(side)s, %(set_number)s, %(image_url)s)
        ON DUPLICATE KEY UPDATE
            card_name = VALUES(card_name),
            culture = VALUES(culture),
            card_type = VALUES(card_type),
            side = VALUES(side),
            set_number = VALUES(set_number),
            image_url = VALUES(image_url),
            last_updated = CURRENT_TIMESTAMP
    """
    
    count = 0
    for blueprint, card_info in cards.items():
        try:
            cursor.execute(upsert_sql, card_info)
            count += 1
        except mysql.connector.Error as e:
            print(f"Warning: Failed to upsert {blueprint}: {e}", file=sys.stderr)
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"Upserted {count} cards to card_catalog")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Build card catalog from HJSON and PC_Cards.js')
    parser.add_argument('--resources', type=Path, 
                        default=Path(os.environ.get('GEMP_RESOURCES_PATH', '/gemp-resources')),
                        help='Path to GEMP resources directory (contains cards/ folder)')
    parser.add_argument('--js', type=Path,
                        default=Path(os.environ.get('GEMP_JS_PATH', '/gemp-js')),
                        help='Path to GEMP JS directory (contains PC_Cards.js)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse files but do not write to database')
    
    args = parser.parse_args()
    
    print(f"Loading HJSON from: {args.resources}")
    print(f"Loading PC_Cards.js from: {args.js}")
    
    # Load card metadata from HJSON
    cards = load_all_hjson(args.resources)
    if not cards:
        print("No cards loaded from HJSON. Check paths.", file=sys.stderr)
        sys.exit(1)
    
    # Load image URL overrides from PC_Cards.js
    pc_cards_urls = parse_pc_cards_js(args.js)
    
    # Resolve image URLs
    cards = resolve_image_urls(cards, pc_cards_urls)
    
    # Count cards with/without images
    with_images = sum(1 for c in cards.values() if c.get('image_url'))
    print(f"Cards with image URLs: {with_images}/{len(cards)}")
    
    if args.dry_run:
        print("Dry run - not writing to database")
        # Print a few samples
        for i, (bp, card) in enumerate(cards.items()):
            if i >= 5:
                break
            print(f"  {bp}: {card['card_name']} ({card['culture']}) -> {card.get('image_url', 'NO URL')[:60]}...")
    else:
        upsert_catalog(cards)
    
    print("Done!")


if __name__ == '__main__':
    main()
