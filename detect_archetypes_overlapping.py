#!/usr/bin/env python3
"""
GEMP Overlapping Archetype Detection

Uses DEMON (Democratic Estimate of the Modular Organization of a Network) to find
overlapping card communities. Unlike Louvain, cards can belong to multiple archetypes.

This better reflects CCG reality where:
- Splash cards appear in multiple strategies
- Hybrid decks exist
- Key cards anchor multiple archetypes

Algorithm:
1. Build graph: cards = nodes, correlations = edges (weighted by lift)
2. Run DEMON to find overlapping communities
3. For each community, compute stats and membership
4. Store for human review (cards may appear in multiple communities)

Usage:
    python detect_archetypes_overlapping.py                        # All formats
    python detect_archetypes_overlapping.py --format "Fellowship Block"
    python detect_archetypes_overlapping.py --epsilon 0.25         # Merge threshold
    python detect_archetypes_overlapping.py --dry-run              # Preview

DEMON parameters:
    --epsilon: Merge threshold (0-1). Higher = more merging = fewer communities.
               Default 0.25 is a good starting point.
    --min-community: Minimum community size. Default 3 (DEMON's default).
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
except ImportError:
    print("ERROR: networkx required. Install with: pip install networkx")
    sys.exit(1)

try:
    from cdlib import algorithms as cd_algorithms
    from cdlib import NodeClustering
except ImportError:
    print("ERROR: cdlib required. Install with: pip install cdlib")
    sys.exit(1)

from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('./logs/archetypes_overlapping.log'),
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
    
    # Log high-degree nodes (potential super-connectors that distort communities)
    if G.number_of_nodes() > 0:
        degrees = sorted(G.degree(), key=lambda x: x[1], reverse=True)
        avg_degree = sum(d for _, d in degrees) / len(degrees)
        logger.info(f"  Average degree: {avg_degree:.1f}")
        
        # Cards with degree > 3x average are suspicious
        high_degree_threshold = avg_degree * 3
        high_degree = [(n, d) for n, d in degrees if d > high_degree_threshold]
        if high_degree:
            logger.info(f"  High-degree nodes (>{high_degree_threshold:.0f} edges):")
            for node, deg in high_degree[:5]:
                logger.info(f"    {node}: {deg} edges")
    
    return G


def detect_communities_demon(G: nx.Graph, epsilon: float = 0.25, min_community: int = 3) -> list[set]:
    """
    Run DEMON community detection on the graph.
    
    Returns: list of sets, each set contains card blueprints in that community.
    Cards can appear in multiple sets (overlapping).
    
    Parameters:
        epsilon: Merge threshold (0-1). Higher = more aggressive merging.
        min_community: Minimum community size to keep.
    """
    if G.number_of_nodes() == 0:
        return []
    
    # DEMON requires the graph to be connected for best results
    # Work on largest connected component if graph is disconnected
    if not nx.is_connected(G):
        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        logger.info(f"  Using largest connected component: {G.number_of_nodes()} nodes")
    
    try:
        # Run DEMON
        result: NodeClustering = cd_algorithms.demon(G, epsilon=epsilon, min_com_size=min_community)
        communities = result.communities
        
        # Convert to list of sets
        community_sets = [set(c) for c in communities]
        
        logger.info(f"  Found {len(community_sets)} overlapping communities")
        
        # Log community sizes
        sizes = [len(c) for c in community_sets]
        sizes.sort(reverse=True)
        logger.info(f"  Largest communities: {sizes[:10]}")
        
        # Count overlapping cards
        all_cards = set()
        overlap_count = 0
        card_appearances = defaultdict(int)
        for comm in community_sets:
            for card in comm:
                card_appearances[card] += 1
                all_cards.add(card)
        
        multi_community_cards = sum(1 for c in card_appearances.values() if c > 1)
        logger.info(f"  Cards in multiple communities: {multi_community_cards}/{len(all_cards)}")
        
        # Log super-connectors (cards in many communities)
        super_connectors = [(card, count) for card, count in card_appearances.items() if count >= 5]
        if super_connectors:
            super_connectors.sort(key=lambda x: x[1], reverse=True)
            logger.info(f"  Super-connectors (in 5+ communities):")
            for card, count in super_connectors[:10]:
                logger.info(f"    {card}: {count} communities")
        
        return community_sets
        
    except Exception as e:
        logger.error(f"  DEMON failed: {e}")
        return []


def compute_community_stats(
    G: nx.Graph, 
    communities: list[set],
    cursor,
    format_name: str,
    side: str,
    min_cards: int = 7,
    min_membership: float = 0.0,
) -> list[dict]:
    """
    Compute statistics for each community.
    
    Returns list of community info dicts.
    
    Parameters:
        min_membership: Minimum membership score to keep a card in a community.
                       Cards below this threshold are filtered out.
    """
    results = []
    
    for comm_id, cards in enumerate(communities):
        cards = list(cards)
        
        # First compute membership scores for all cards
        membership_scores = {}
        for card in cards:
            # Count edges to other community members
            internal_edges = sum(1 for neighbor in G.neighbors(card) if neighbor in cards)
            max_possible = len(cards) - 1
            membership_scores[card] = internal_edges / max_possible if max_possible > 0 else 0
        
        # Filter by minimum membership if specified
        if min_membership > 0:
            cards = [c for c in cards if membership_scores[c] >= min_membership]
            # Recompute scores with filtered set
            if len(cards) >= min_cards:
                membership_scores = {}
                for card in cards:
                    internal_edges = sum(1 for neighbor in G.neighbors(card) if neighbor in cards)
                    max_possible = len(cards) - 1
                    membership_scores[card] = internal_edges / max_possible if max_possible > 0 else 0
        
        # Skip tiny communities (likely noise)
        if len(cards) < min_cards:
            continue
        
        # Compute average internal lift
        internal_lifts = []
        for i, card_a in enumerate(cards):
            for card_b in cards[i+1:]:
                if G.has_edge(card_a, card_b):
                    internal_lifts.append(G[card_a][card_b]['weight'])
        
        avg_lift = sum(internal_lifts) / len(internal_lifts) if internal_lifts else 0
        
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
):
    """Insert detected communities into database."""
    
    if dry_run:
        # Just preview
        logger.info(f"\n  DRY RUN: Would insert {len(community_stats)} communities")
        
        # Get card names for preview
        all_cards = []
        for comm in community_stats[:15]:  # Preview top 15
            all_cards.extend(comm['cards'])
        card_names = get_card_names(cursor, all_cards)
        
        # Track which cards appear in multiple communities
        card_communities = defaultdict(list)
        for comm in community_stats:
            for card in comm['cards']:
                card_communities[card].append(comm['community_id'])
        
        for comm in community_stats[:15]:
            logger.info(f"\n  Community {comm['community_id']}: {comm['card_count']} cards, avg_lift={comm['avg_internal_lift']}")
            # Show top 10 cards by membership score
            top_cards = sorted(comm['membership_scores'].items(), key=lambda x: x[1], reverse=True)[:10]
            for card, score in top_cards:
                name = card_names.get(card, card)
                other_comms = [c for c in card_communities[card] if c != comm['community_id']]
                overlap_note = f" [also in: {other_comms}]" if other_comms else ""
                logger.info(f"    {card} ({name}): score={score:.2f}{overlap_note}")
        return
    
    # Clear existing communities for this format/side
    cursor.execute("""
        DELETE cc FROM card_communities cc
        WHERE cc.format_name = %s AND cc.side = %s
    """, (format_name, side))
    conn.commit()
    
    # Insert each community
    for comm in community_stats:
        # Insert community
        cursor.execute("""
            INSERT INTO card_communities 
                (format_name, side, community_id, card_count, avg_internal_lift)
            VALUES (%s, %s, %s, %s, %s)
        """, (format_name, side, comm['community_id'], comm['card_count'], comm['avg_internal_lift']))
        
        db_community_id = cursor.lastrowid
        
        # Insert members
        member_data = [
            (db_community_id, card, score, score >= 0.5)  # is_core if score >= 0.5
            for card, score in comm['membership_scores'].items()
        ]
        
        cursor.executemany("""
            INSERT INTO card_community_members 
                (community_id, card_blueprint, membership_score, is_core)
            VALUES (%s, %s, %s, %s)
        """, member_data)
    
    conn.commit()
    logger.info(f"  Inserted {len(community_stats)} communities for {format_name} {side}")


def get_available_formats(cursor) -> list[str]:
    """Get list of formats with correlation data."""
    cursor.execute("""
        SELECT DISTINCT format_name 
        FROM card_correlations 
        ORDER BY format_name
    """)
    return [row[0] for row in cursor.fetchall()]


def main():
    parser = argparse.ArgumentParser(description='GEMP Overlapping Archetype Detection (DEMON)')
    parser.add_argument('--format', type=str, help='Specific format to analyze')
    parser.add_argument('--min-lift', type=float, default=1.5,
                        help='Minimum lift for correlation edges (default: 1.5)')
    parser.add_argument('--min-together', type=int, default=50,
                        help='Minimum co-occurrences for edges (default: 50)')
    parser.add_argument('--epsilon', type=float, default=0.25,
                        help='DEMON merge threshold 0-1: higher=fewer communities (default: 0.25)')
    parser.add_argument('--min-community', type=int, default=3,
                        help='DEMON minimum community size (default: 3)')
    parser.add_argument('--min-cards', type=int, default=7,
                        help='Minimum cards to keep a community (default: 7)')
    parser.add_argument('--min-membership', type=float, default=0.0,
                        help='Minimum membership score to keep card in community (default: 0, try 0.3)')
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
        
        logger.info(f"Processing {len(formats)} formats with DEMON (epsilon={args.epsilon}, min_membership={args.min_membership})")
        
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
                    
                    # Detect overlapping communities with DEMON
                    communities = detect_communities_demon(
                        G, 
                        epsilon=args.epsilon,
                        min_community=args.min_community
                    )
                    
                    if not communities:
                        logger.info("  No communities detected")
                        continue
                    
                    # Compute stats
                    stats = compute_community_stats(
                        G, communities, cursor, format_name, side,
                        min_cards=args.min_cards,
                        min_membership=args.min_membership
                    )
                    
                    # Store
                    insert_communities(cursor, conn, format_name, side, stats, args.dry_run)
                    
                    # Cleanup
                    del G, communities, stats
                    gc.collect()
                    
                except Exception as e:
                    logger.error(f"Error processing {format_name} {side}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
        
        logger.info("\nOverlapping archetype detection complete!")
    
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
