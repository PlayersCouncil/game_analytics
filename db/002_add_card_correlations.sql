-- Migration: Add card correlation analysis tables
-- Run this before running compute_correlations.py

-- Pairwise card correlation data
CREATE TABLE IF NOT EXISTS card_correlations (
    card_a VARCHAR(20) NOT NULL,
    card_b VARCHAR(20) NOT NULL,
    format_name VARCHAR(50) NOT NULL,
    side ENUM('free_peoples', 'shadow') NOT NULL,
    
    -- Raw counts
    together_count INT NOT NULL,          -- decks containing both
    card_a_count INT NOT NULL,            -- decks containing A
    card_b_count INT NOT NULL,            -- decks containing B
    total_decks INT NOT NULL,             -- total decks in format/side
    
    -- Derived metrics
    jaccard FLOAT NOT NULL,               -- intersection / union
    lift FLOAT NOT NULL,                  -- P(A∩B) / (P(A) × P(B)) - key metric
    
    -- Metadata
    computed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (card_a, card_b, format_name, side),
    
    -- Query pattern: "what correlates with card X?"
    INDEX idx_card_a_lift (card_a, format_name, side, lift DESC),
    INDEX idx_card_b_lift (card_b, format_name, side, lift DESC),
    
    -- Query pattern: "highest lift pairs in format"
    INDEX idx_format_lift (format_name, side, lift DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Future: archetype definitions (leaving schema here for reference)
-- CREATE TABLE IF NOT EXISTS archetypes (
--     id INT AUTO_INCREMENT PRIMARY KEY,
--     name VARCHAR(100) NOT NULL,
--     format_name VARCHAR(50) NOT NULL,
--     side ENUM('free_peoples', 'shadow') NOT NULL,
--     description TEXT,
--     is_active BOOLEAN DEFAULT TRUE,
--     created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
--     
--     UNIQUE INDEX idx_name_format (name, format_name)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;
-- 
-- CREATE TABLE IF NOT EXISTS archetype_cards (
--     archetype_id INT NOT NULL,
--     card_blueprint VARCHAR(20) NOT NULL,
--     role ENUM('anchor', 'core', 'flex') NOT NULL,  -- anchor = defining, core = high correlation, flex = sometimes included
--     weight FLOAT DEFAULT 1.0,
--     
--     PRIMARY KEY (archetype_id, card_blueprint),
--     FOREIGN KEY (archetype_id) REFERENCES archetypes(id) ON DELETE CASCADE
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;
