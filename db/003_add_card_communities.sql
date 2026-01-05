-- Migration: Add card community / archetype detection tables
-- Run this before running detect_archetypes.py

-- Detected card communities (before human naming)
CREATE TABLE IF NOT EXISTS card_communities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    format_name VARCHAR(50) NOT NULL,
    side ENUM('free_peoples', 'shadow') NOT NULL,
    community_id INT NOT NULL,              -- Algorithm-assigned ID (0, 1, 2...)
    
    -- Stats about this community
    card_count INT NOT NULL,                -- How many cards in this community
    deck_count INT NOT NULL DEFAULT 0,      -- How many decks match this community
    avg_internal_lift FLOAT,                -- Average lift between cards in community
    
    -- Human curation
    archetype_name VARCHAR(100),            -- NULL until human names it
    is_valid BOOLEAN DEFAULT TRUE,          -- Human can mark as junk
    notes TEXT,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE INDEX idx_format_side_community (format_name, side, community_id),
    INDEX idx_archetype (archetype_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Which cards belong to which community
CREATE TABLE IF NOT EXISTS card_community_members (
    community_id INT NOT NULL,              -- References card_communities.id
    card_blueprint VARCHAR(20) NOT NULL,
    
    -- Card's role in the community
    membership_score FLOAT NOT NULL,        -- How central is this card (0-1)
    is_core BOOLEAN DEFAULT FALSE,          -- Appears in >70% of community decks
    
    PRIMARY KEY (community_id, card_blueprint),
    FOREIGN KEY (community_id) REFERENCES card_communities(id) ON DELETE CASCADE,
    INDEX idx_card (card_blueprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Deck archetype assignments (computed after communities exist)
CREATE TABLE IF NOT EXISTS deck_archetypes (
    game_id INT NOT NULL,
    player_id INT NOT NULL,
    community_id INT NOT NULL,              -- Best matching community
    match_score FLOAT NOT NULL,             -- How well deck matches (0-1)
    
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (community_id) REFERENCES card_communities(id) ON DELETE CASCADE,
    INDEX idx_community (community_id),
    INDEX idx_score (match_score DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;
