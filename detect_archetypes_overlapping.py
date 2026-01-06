#!/usr/bin/env python3
"""
GEMP Overlapping Archetype Detection

Uses overlapping community detection algorithms to find card clusters where
cards can belong to multiple archetypes. This better reflects CCG reality where:
- Splash cards appear in multiple strategies
- Hybrid decks exist
- Key cards anchor multiple archetypes

Available algorithms:
- DEMON: Democratic Estimate of the Modular Organization of a Network
- SLPA: Speaker-listener Label Propagation Algorithm  
- ANGEL: Similar to DEMON with different merging strategy
- ANCHOR: Domain-aware - builds communities around most-played cards

Usage:
    python detect_archetypes_overlapping.py                        # DEMON (default)
    python detect_archetypes_overlapping.py --algorithm slpa       # Use SLPA
    python detect_archetypes_overlapping.py --algorithm anchor     # Use anchor-based
    python detect_archetypes_overlapping.py --max-degree 80        # Remove super-connectors
    python detect_archetypes_overlapping.py --seed 42              # Reproducible results
    python detect_archetypes_overlapping.py --dry-run              # Preview

Anchor algorithm (recommended):
    python detect_archetypes_overlapping.py --algorithm anchor \\
        --num-anchors 25 --correlation-threshold 2.5 --dry-run

Key parameters:
    --algorithm: demon, slpa, angel, or anchor
    --max-degree: Remove cards with more than N correlations (super-connectors)
    --seed: Random seed for reproducibility
    --num-anchors: How many top-played cards to use as anchors
    --correlation-threshold: Min lift to include card in anchor's community
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

# Available algorithms
ALGORITHMS = ['demon', 'slpa', 'angel', 'anchor']


def detect_communities_anchor(
    cursor, 
    G: nx.Graph, 
    format_name: str, 
    side: str, 
    num_anchors: int = 20,
    correlation_threshold: float = 2.0,
    min_community: int = 7,
) -> list[set]:
    """
    Anchor-based community detection.
    
    1. Find most-played cards as anchors
    2. For each anchor, find cards that correlate strongly with it
    3. Cards can belong to multiple anchor communities
    
    This is domain-aware: communities are centered around popular cards,
    which tend to be deck-defining rather than peripheral.
    """
    # Get most-played cards for this format/side
    cursor.execute("""
        SELECT csd.card_blueprint, SUM(csd.deck_appearances) as total_games
        FROM card_stats_daily csd
        JOIN card_catalog cc ON csd.card_blueprint = cc.blueprint
        WHERE csd.format_name = %s AND cc.side = %s
        GROUP BY csd.card_blueprint
        ORDER BY total_games DESC
        LIMIT %s
    """, (format_name, side, num_anchors * 2))  # Get extra in case some aren't in graph
    
    anchor_candidates = [(row[0], row[1]) for row in cursor.fetchall()]
    
    # Filter to cards actually in our correlation graph
    graph_nodes = set(G.nodes())
    anchors = [(bp, games) for bp, games in anchor_candidates if bp in graph_nodes][:num_anchors]
    
    logger.info(f"  Using {len(anchors)} anchors (most-played cards)")
    for bp, games in anchors[:5]:
        logger.info(f"    {bp}: {games} games")
    
    communities = []
    used_cards = set()  # Track which cards have been assigned
    
    for anchor_bp, anchor_games in anchors:
        # Find all cards that correlate with this anchor above threshold
        community_cards = {anchor_bp}
        card_scores = {anchor_bp: float('inf')}  # Anchor has infinite "score"
        
        for neighbor in G.neighbors(anchor_bp):
            edge_data = G[anchor_bp][neighbor]
            lift = edge_data.get('weight', 1.0)
            if lift >= correlation_threshold:
                community_cards.add(neighbor)
                card_scores[neighbor] = lift
        
        if len(community_cards) >= min_community:
            communities.append({
                'cards': community_cards,
                'anchor': anchor_bp,
                'anchor_games': anchor_games,
                'scores': card_scores,
            })
            used_cards.update(community_cards)
    
    logger.info(f"  Found {len(communities)} anchor-based communities")
    logger.info(f"  Cards assigned: {len(used_cards)}/{len(graph_nodes)}")
    
    # Log overlap
    card_appearances = defaultdict(int)
    for comm in communities:
        for card in comm['cards']:
            card_appearances[card] += 1
    
    multi = sum(1 for c in card_appearances.values() if c > 1)
    logger.info(f"  Cards in multiple communities: {multi}/{len(used_cards)}")
    
    return communities

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


def build_correlation_graph(cursor, format_name: str, side: str, min_lift: float, min_together: int, max_degree: int = 0) -> nx.Graph:
    """
    Build a weighted graph from card correlations.
    
    Nodes = cards
    Edges = correlations with lift >= min_lift
    Edge weight = lift value
    
    If max_degree > 0, removes super-connector nodes after building.
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
    removed_connectors = []
    if G.number_of_nodes() > 0:
        degrees = sorted(G.degree(), key=lambda x: x[1], reverse=True)
        avg_degree = sum(d for _, d in degrees) / len(degrees)
        logger.info(f"  Average degree: {avg_degree:.1f}")
        
        # Remove super-connectors if max_degree specified
        if max_degree > 0:
            to_remove = [(n, d) for n, d in degrees if d > max_degree]
            if to_remove:
                removed_connectors = to_remove
                logger.info(f"  Removing {len(to_remove)} super-connectors (degree > {max_degree}):")
                for node, deg in to_remove[:10]:
                    logger.info(f"    {node}: {deg} edges")
                G.remove_nodes_from([n for n, _ in to_remove])
                logger.info(f"  Graph after removal: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        else:
            # Just log high-degree nodes without removing
            high_degree_threshold = avg_degree * 3
            high_degree = [(n, d) for n, d in degrees if d > high_degree_threshold]
            if high_degree:
                logger.info(f"  High-degree nodes (>{high_degree_threshold:.0f} edges):")
                for node, deg in high_degree[:5]:
                    logger.info(f"    {node}: {deg} edges")
    
    return G


def detect_communities_overlapping(G: nx.Graph, algorithm: str = 'demon', epsilon: float = 0.25, min_community: int = 3, iterations: int = 20, seed: int = None) -> list[set]:
    """
    Run overlapping community detection on the graph.
    
    Returns: list of sets, each set contains card blueprints in that community.
    Cards can appear in multiple sets (overlapping).
    
    Parameters:
        algorithm: 'demon', 'slpa', or 'angel'
        epsilon: Merge threshold for DEMON/ANGEL (0-1). Higher = more aggressive merging.
        min_community: Minimum community size to keep.
        iterations: Number of iterations for SLPA (default 20).
        seed: Random seed for reproducibility.
    """
    if G.number_of_nodes() == 0:
        return []
    
    # Set random seed for reproducibility
    if seed is not None:
        import random
        import numpy as np
        random.seed(seed)
        np.random.seed(seed)
        logger.info(f"  Using random seed: {seed}")
    
    # DEMON requires the graph to be connected for best results
    # Work on largest connected component if graph is disconnected
    if not nx.is_connected(G):
        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        logger.info(f"  Using largest connected component: {G.number_of_nodes()} nodes")
    
    try:
        # Run selected algorithm
        if algorithm == 'demon':
            logger.info(f"  Running DEMON (epsilon={epsilon}, min_com_size={min_community})")
            result: NodeClustering = cd_algorithms.demon(G, epsilon=epsilon, min_com_size=min_community)
        elif algorithm == 'slpa':
            # SLPA: Speaker-listener Label Propagation
            # t = iterations, r = threshold for label inclusion
            # Lower r = more labels kept = more communities/overlap
            # Higher r = fewer labels = fewer communities
            logger.info(f"  Running SLPA (iterations={iterations}, threshold={epsilon})")
            result: NodeClustering = cd_algorithms.slpa(G, t=iterations, r=epsilon)
        elif algorithm == 'angel':
            # ANGEL: similar to DEMON with different merging strategy
            logger.info(f"  Running ANGEL (threshold={epsilon}, min_community={min_community})")
            result: NodeClustering = cd_algorithms.angel(G, threshold=epsilon, min_community_size=min_community)
        else:
            logger.error(f"  Unknown algorithm: {algorithm}")
            return []
            
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
        logger.error(f"  {algorithm.upper()} failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
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
            # Show anchor info if available
            anchor_info = ""
            if 'anchor' in comm:
                anchor_name = card_names.get(comm['anchor'], comm['anchor'])
                anchor_info = f" [anchor: {anchor_name}, {comm.get('anchor_games', '?')} games]"
            
            logger.info(f"\n  Community {comm['community_id']}: {comm['card_count']} cards, avg_lift={comm['avg_internal_lift']}{anchor_info}")
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
    parser.add_argument('--max-degree', type=int, default=0,
                        help='Remove super-connectors with more than N edges (default: 0 = disabled, try 80)')
    parser.add_argument('--algorithm', type=str, default='demon', choices=ALGORITHMS,
                        help='Overlapping algorithm: demon, slpa, angel (default: demon)')
    parser.add_argument('--epsilon', type=float, default=0.25,
                        help='Threshold: DEMON/ANGEL merge (higher=fewer), SLPA label inclusion (lower=more) (default: 0.25)')
    parser.add_argument('--iterations', type=int, default=20,
                        help='SLPA iterations (default: 20)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility (default: None = random)')
    parser.add_argument('--min-community', type=int, default=3,
                        help='DEMON minimum community size (default: 3)')
    parser.add_argument('--min-cards', type=int, default=7,
                        help='Minimum cards to keep a community (default: 7)')
    parser.add_argument('--num-anchors', type=int, default=20,
                        help='Number of anchor cards for anchor algorithm (default: 20)')
    parser.add_argument('--correlation-threshold', type=float, default=2.0,
                        help='Min lift to include card in anchor community (default: 2.0)')
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
        
        logger.info(f"Processing {len(formats)} formats with {args.algorithm.upper()} (max_degree={args.max_degree}, min_membership={args.min_membership})")
        
        for format_name in formats:
            logger.info(f"\n=== Processing {format_name} ===")
            
            for side in ['free_peoples', 'shadow']:
                logger.info(f"\n--- {side.replace('_', ' ').title()} ---")
                
                try:
                    # Build graph from correlations
                    G = build_correlation_graph(
                        cursor, format_name, side,
                        args.min_lift, args.min_together, args.max_degree
                    )
                    
                    if G.number_of_nodes() < 10:
                        logger.info("  Too few cards for meaningful communities, skipping")
                        continue
                    
                    # Detect communities based on algorithm
                    if args.algorithm == 'anchor':
                        # Anchor-based detection (returns different structure)
                        anchor_communities = detect_communities_anchor(
                            cursor, G, format_name, side,
                            num_anchors=args.num_anchors,
                            correlation_threshold=args.correlation_threshold,
                            min_community=args.min_cards
                        )
                        
                        if not anchor_communities:
                            logger.info("  No communities detected")
                            continue
                        
                        # Convert anchor format to standard format for stats/storage
                        communities = [set(c['cards']) for c in anchor_communities]
                        
                        # Compute stats (will recalculate membership scores)
                        stats = compute_community_stats(
                            G, communities, cursor, format_name, side,
                            min_cards=args.min_cards,
                            min_membership=args.min_membership
                        )
                        
                        # Inject anchor info into stats
                        for i, (stat, anchor_comm) in enumerate(zip(stats, anchor_communities)):
                            stat['anchor'] = anchor_comm['anchor']
                            stat['anchor_games'] = anchor_comm['anchor_games']
                    else:
                        # Graph-based algorithms (DEMON, SLPA, ANGEL)
                        communities = detect_communities_overlapping(
                            G, 
                            algorithm=args.algorithm,
                            epsilon=args.epsilon,
                            min_community=args.min_community,
                            iterations=args.iterations,
                            seed=args.seed
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
