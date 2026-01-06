#!/usr/bin/env python3
"""
GEMP Archetype Detection

Uses graph community detection on card correlations to find natural card clusters.
These clusters are candidate archetypes that humans can then name and validate.

Algorithm:
1. Build graph: cards = nodes, correlations = edges (weighted by lift)
2. Run Louvain community detection to find natural clusters
3. For each community, identify core cards and compute stats
4. Find "flex" cards - cards that correlate with multiple core members but were
   assigned to a different community by Louvain
5. Store for human review

Card membership types:
- 'core': Cards assigned to this community by Louvain
- 'flex': Cards that correlate strongly with core members but belong elsewhere
- 'custom': Cards manually assigned by users (preserved across runs)

Usage:
    python detect_archetypes.py                           # All formats
    python detect_archetypes.py --format "Fellowship Block"
    python detect_archetypes.py --min-lift 1.5            # Stricter edge threshold
    python detect_archetypes.py --resolution 7.5          # More granular communities
    python detect_archetypes.py --flex-min-connections 4  # Stricter flex detection
    python detect_archetypes.py --no-flex                 # Skip flex detection
    python detect_archetypes.py --dry-run                 # Preview without inserting
"""

import argparse
import gc
import logging
import sys
from collections import defaultdict
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

try:
    import networkx as nx
    from networkx.algorithms import community as nx_community
except ImportError:
    print("ERROR: networkx required. Install with: pip install networkx")
    sys.exit(1)

from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('./logs/archetypes.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def build_correlation_graph(cursor, format_name: str, side: str, min_lift: float, min_together: int) -> nx.Graph:
    """
    Build a weighted graph from card correlations.
    
    Nodes = cards
    Edges = correlations with lift >= min_lift
    Edge weight = lift value
    """
    cursor.execute("""
        SELECT card_a, card_b, lift, together_count
        FROM card_correlations
        WHERE format_name = %s 
          AND side = %s
          AND lift >= %s
          AND together_count >= %s
    """, (format_name, side, min_lift, min_together))
    
    G = nx.Graph()
    
    for card_a, card_b, lift, together in cursor.fetchall():
        G.add_edge(card_a, card_b, weight=lift, together=together)
    
    logger.info(f"  Built graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def detect_communities(G: nx.Graph, resolution: float = 1.0) -> dict[str, int]:
    """
    Run Louvain community detection on the graph.
    
    Returns: {card_blueprint: community_id}
    
    Resolution parameter controls granularity:
    - Higher = more, smaller communities
    - Lower = fewer, larger communities
    """
    if G.number_of_nodes() == 0:
        return {}
    
    # Louvain returns a list of sets, each set is a community
    communities = nx_community.louvain_communities(G, weight='weight', resolution=resolution)
    
    # Convert to card -> community_id mapping
    card_to_community = {}
    for community_id, members in enumerate(communities):
        for card in members:
            card_to_community[card] = community_id
    
    logger.info(f"  Found {len(communities)} communities")
    
    # Log community sizes
    sizes = [len(c) for c in communities]
    sizes.sort(reverse=True)
    logger.info(f"  Largest communities: {sizes[:10]}")
    
    return card_to_community


def compute_community_stats(
    G: nx.Graph, 
    communities: dict[str, int],
    cursor,
    format_name: str,
    side: str,
) -> list[dict]:
    """
    Compute statistics for each community.
    
    Returns list of community info dicts.
    """
    # Group cards by community
    community_cards = defaultdict(list)
    for card, comm_id in communities.items():
        community_cards[comm_id].append(card)
    
    results = []
    
    for comm_id, cards in community_cards.items():
        # Skip tiny communities (likely noise)
        if len(cards) < 7:
            continue
        
        # Compute average internal lift
        internal_lifts = []
        for i, card_a in enumerate(cards):
            for card_b in cards[i+1:]:
                if G.has_edge(card_a, card_b):
                    internal_lifts.append(G[card_a][card_b]['weight'])
        
        avg_lift = sum(internal_lifts) / len(internal_lifts) if internal_lifts else 0
        
        # Compute membership scores (how connected each card is within community)
        membership_scores = {}
        for card in cards:
            # Count edges to other community members
            internal_edges = sum(1 for neighbor in G.neighbors(card) if neighbor in cards)
            max_possible = len(cards) - 1
            membership_scores[card] = internal_edges / max_possible if max_possible > 0 else 0
        
        results.append({
            'community_id': comm_id,
            'cards': cards,
            'card_count': len(cards),
            'avg_internal_lift': round(avg_lift, 2),
            'membership_scores': membership_scores,
        })
    
    # Sort by size descending
    results.sort(key=lambda x: x['card_count'], reverse=True)
    
    return results


def get_card_names(cursor, blueprints: list) -> dict[str, str]:
    """Fetch card names from catalog."""
    if not blueprints:
        return {}
    
    placeholders = ','.join(['%s'] * len(blueprints))
    cursor.execute(f"""
        SELECT blueprint, card_name 
        FROM card_catalog 
        WHERE blueprint IN ({placeholders})
    """, blueprints)
    
    return {row[0]: row[1] for row in cursor.fetchall()}


def insert_communities(
    cursor,
    conn,
    format_name: str,
    side: str,
    community_stats: list[dict],
    dry_run: bool = False,
) -> list[int]:
    """Insert detected communities into database. Returns list of db community IDs."""
    
    if dry_run:
        # Just preview
        logger.info(f"\n  DRY RUN: Would insert {len(community_stats)} communities")
        
        # Get card names for preview
        all_cards = []
        for comm in community_stats[:15]:  # Preview top 15
            all_cards.extend(comm['cards'])
        card_names = get_card_names(cursor, all_cards)
        
        for comm in community_stats[:15]:
            logger.info(f"\n  Community {comm['community_id']}: {comm['card_count']} cards, avg_lift={comm['avg_internal_lift']}")
            # Show top 10 cards by membership score
            top_cards = sorted(comm['membership_scores'].items(), key=lambda x: x[1], reverse=True)[:10]
            for card, score in top_cards:
                name = card_names.get(card, card)
                logger.info(f"    {card} ({name}): score={score:.2f}")
        return []
    
    # Clear existing communities for this format/side (only core/flex, preserve custom)
    cursor.execute("""
        DELETE ccm FROM card_community_members ccm
        JOIN card_communities cc ON ccm.community_id = cc.id
        WHERE cc.format_name = %s AND cc.side = %s AND ccm.membership_type IN ('core', 'flex')
    """, (format_name, side))
    
    cursor.execute("""
        DELETE cc FROM card_communities cc
        WHERE cc.format_name = %s AND cc.side = %s
          AND NOT EXISTS (
              SELECT 1 FROM card_community_members ccm 
              WHERE ccm.community_id = cc.id
          )
    """, (format_name, side))
    conn.commit()
    
    db_community_ids = []
    
    # Insert each community
    for comm in community_stats:
        # Insert community
        cursor.execute("""
            INSERT INTO card_communities 
                (format_name, side, community_id, card_count, avg_internal_lift)
            VALUES (%s, %s, %s, %s, %s)
        """, (format_name, side, comm['community_id'], comm['card_count'], comm['avg_internal_lift']))
        
        db_community_id = cursor.lastrowid
        db_community_ids.append(db_community_id)
        
        # Insert members as 'core' type
        member_data = [
            (db_community_id, card, score, score >= 0.5, 'core')
            for card, score in comm['membership_scores'].items()
        ]
        
        cursor.executemany("""
            INSERT INTO card_community_members 
                (community_id, card_blueprint, membership_score, is_core, membership_type)
            VALUES (%s, %s, %s, %s, %s)
        """, member_data)
    
    conn.commit()
    logger.info(f"  Inserted {len(community_stats)} communities for {format_name} {side}")
    return db_community_ids


def find_flex_cards(
    G: nx.Graph,
    community_stats: list[dict],
    communities: dict[str, int],
    min_core_connections: int = 3,
    min_avg_lift: float = 2.0,
) -> dict[int, list[tuple[str, float, int]]]:
    """
    Find flex cards - cards that correlate with multiple core members of communities
    they weren't assigned to by Louvain.
    
    Parameters:
        G: Correlation graph
        community_stats: List of community stat dicts (with 'cards', 'membership_scores')
        communities: Card -> community_id mapping from Louvain
        min_core_connections: Minimum core cards a flex card must connect to
        min_avg_lift: Minimum average lift to those core cards
    
    Returns:
        {community_id: [(card_blueprint, avg_lift, num_connections), ...]}
    """
    flex_by_community = defaultdict(list)
    
    for comm in community_stats:
        comm_id = comm['community_id']
        
        # Get core cards (membership_score >= 0.5)
        core_cards = {card for card, score in comm['membership_scores'].items() if score >= 0.5}
        
        if len(core_cards) < min_core_connections:
            continue  # Not enough core cards to meaningfully detect flex
        
        # Get all cards already in this community
        comm_cards = set(comm['cards'])
        
        # Find candidates: cards NOT in this community but in the graph
        all_graph_nodes = set(G.nodes())
        candidates = all_graph_nodes - comm_cards
        
        for candidate in candidates:
            # Count connections to core cards and compute average lift
            connections = []
            for core_card in core_cards:
                if G.has_edge(candidate, core_card):
                    lift = G[candidate][core_card].get('weight', 0)
                    connections.append(lift)
            
            if len(connections) >= min_core_connections:
                avg_lift = sum(connections) / len(connections)
                if avg_lift >= min_avg_lift:
                    flex_by_community[comm_id].append((candidate, avg_lift, len(connections)))
    
    # Sort by avg_lift descending within each community
    for comm_id in flex_by_community:
        flex_by_community[comm_id].sort(key=lambda x: x[1], reverse=True)
    
    return flex_by_community


def insert_flex_cards(
    cursor,
    conn,
    db_community_ids: list[int],
    community_stats: list[dict],
    flex_by_community: dict[int, list[tuple[str, float, int]]],
    dry_run: bool = False,
):
    """Insert flex cards into communities."""
    
    total_flex = sum(len(cards) for cards in flex_by_community.values())
    
    if dry_run:
        logger.info(f"\n  DRY RUN: Would add {total_flex} flex cards across {len(flex_by_community)} communities")
        
        # Get card names for preview
        all_flex_cards = [card for cards in flex_by_community.values() for card, _, _ in cards]
        card_names = get_card_names(cursor, all_flex_cards[:50])  # Limit for preview
        
        for comm in community_stats:
            comm_id = comm['community_id']
            if comm_id in flex_by_community:
                flex_cards = flex_by_community[comm_id][:5]  # Show top 5
                if flex_cards:
                    logger.info(f"\n  Community {comm_id} flex cards:")
                    for card, avg_lift, num_conn in flex_cards:
                        name = card_names.get(card, card)
                        logger.info(f"    + {card} ({name}): avg_lift={avg_lift:.2f}, connections={num_conn}")
        return
    
    # Map community_id to db_community_id
    comm_id_to_db_id = {
        comm['community_id']: db_id 
        for comm, db_id in zip(community_stats, db_community_ids)
    }
    
    flex_data = []
    for comm_id, flex_cards in flex_by_community.items():
        db_id = comm_id_to_db_id.get(comm_id)
        if db_id is None:
            continue
        
        for card, avg_lift, num_conn in flex_cards:
            # Compute membership score as proportion of core cards connected
            # (We'd need core count, but we can use avg_lift as proxy for score)
            membership_score = min(avg_lift / 5.0, 1.0)  # Normalize to 0-1 range
            flex_data.append((db_id, card, membership_score, False, 'flex'))
    
    if flex_data:
        cursor.executemany("""
            INSERT INTO card_community_members 
                (community_id, card_blueprint, membership_score, is_core, membership_type)
            VALUES (%s, %s, %s, %s, %s)
        """, flex_data)
        conn.commit()
    
    logger.info(f"  Added {len(flex_data)} flex cards")


def get_available_formats(cursor) -> list[str]:
    """Get list of formats with correlation data."""
    cursor.execute("""
        SELECT DISTINCT format_name 
        FROM card_correlations 
        ORDER BY format_name
    """)
    return [row[0] for row in cursor.fetchall()]


def main():
    parser = argparse.ArgumentParser(description='GEMP Archetype Detection')
    parser.add_argument('--format', type=str, help='Specific format to analyze')
    parser.add_argument('--min-lift', type=float, default=1.5,
                        help='Minimum lift for correlation edges (default: 1.5)')
    parser.add_argument('--min-together', type=int, default=50,
                        help='Minimum co-occurrences for edges (default: 50)')
    parser.add_argument('--resolution', type=float, default=1.0,
                        help='Louvain resolution: higher=more communities (default: 1.0)')
    parser.add_argument('--flex-min-connections', type=int, default=3,
                        help='Min core cards a flex card must connect to (default: 3)')
    parser.add_argument('--flex-min-lift', type=float, default=2.0,
                        help='Min average lift for flex card inclusion (default: 2.0)')
    parser.add_argument('--no-flex', action='store_true',
                        help='Skip flex card detection')
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
        # Determine formats to process
        if args.format:
            formats = [args.format]
        else:
            formats = get_available_formats(cursor)
        
        logger.info(f"Processing {len(formats)} formats")
        
        for format_name in formats:
            logger.info(f"\n=== Processing {format_name} ===")
            
            for side in ['free_peoples', 'shadow']:
                logger.info(f"\n--- {side.replace('_', ' ').title()} ---")
                
                try:
                    # Build graph from correlations
                    G = build_correlation_graph(
                        cursor, format_name, side,
                        args.min_lift, args.min_together
                    )
                    
                    if G.number_of_nodes() < 10:
                        logger.info("  Too few cards for meaningful communities, skipping")
                        continue
                    
                    # Detect communities
                    communities = detect_communities(G, resolution=args.resolution)
                    
                    if not communities:
                        logger.info("  No communities detected")
                        continue
                    
                    # Compute stats
                    stats = compute_community_stats(G, communities, cursor, format_name, side)
                    
                    # Store core communities
                    db_ids = insert_communities(cursor, conn, format_name, side, stats, args.dry_run)
                    
                    # Find and insert flex cards
                    if not args.no_flex:
                        flex_cards = find_flex_cards(
                            G, stats, communities,
                            min_core_connections=args.flex_min_connections,
                            min_avg_lift=args.flex_min_lift
                        )
                        if flex_cards:
                            insert_flex_cards(cursor, conn, db_ids, stats, flex_cards, args.dry_run)
                    
                    # Cleanup
                    del G, communities, stats
                    gc.collect()
                    
                except Exception as e:
                    logger.error(f"Error processing {format_name} {side}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
        
        logger.info("\nArchetype detection complete!")
    
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
