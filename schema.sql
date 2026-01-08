-- ============================================================================
-- GEMP GAME ANALYTICS SCHEMA
-- Analytics layer for card performance tracking
-- 
-- Prerequisites: Existing GEMP database with game_history and player tables
-- ============================================================================

-- One row per processed game, linked 1:1 to game_history
CREATE TABLE game_analysis (
  game_id INT NOT NULL,
  
  -- Game metadata (denormalized for query efficiency)
  format_name VARCHAR(50) NOT NULL,
  game_date DATE NOT NULL,
  duration_seconds INT UNSIGNED,
  tournament_name VARCHAR(255),
  
  -- Players (denormalized from game_history)
  winner_player_id INT NOT NULL,
  loser_player_id INT NOT NULL,
  
  -- Classification tiers
  outcome_tier TINYINT NOT NULL COMMENT '1=Decisive, 2=Late Concession, 3=Ambiguous',
  competitive_tier TINYINT NOT NULL COMMENT '1=Casual, 2=League, 3=Tournament, 4=Championship',
  
  -- Game state at conclusion
  winner_site TINYINT UNSIGNED,
  loser_site TINYINT UNSIGNED,
  
  -- Processing metadata
  processing_version INT NOT NULL DEFAULT 1,
  processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  
  PRIMARY KEY (game_id),
  CONSTRAINT fk_ga_game FOREIGN KEY (game_id) REFERENCES game_history(id) ON DELETE CASCADE,
  CONSTRAINT fk_ga_winner FOREIGN KEY (winner_player_id) REFERENCES player(id),
  CONSTRAINT fk_ga_loser FOREIGN KEY (loser_player_id) REFERENCES player(id),
  
  -- Query pattern: "Card win rate in format Y over date range Z"
  INDEX idx_format_date (format_name, game_date),
  
  -- Query pattern: "Top cards by win rate in format Y, competitive tier >= N"
  INDEX idx_format_tier_date (format_name, competitive_tier, game_date),
  
  -- Re-processing: find games processed with old version
  INDEX idx_processing (processing_version)
  
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- One row per card per player per game
CREATE TABLE game_deck_cards (
  id INT NOT NULL AUTO_INCREMENT,
  game_id INT NOT NULL,
  player_id INT NOT NULL,
  
  -- Card identity (base blueprint ID, cosmetic variants pre-mapped)
  card_blueprint VARCHAR(20) NOT NULL,
  card_role ENUM('draw_deck', 'site', 'ring_bearer', 'ring') NOT NULL,
  card_count TINYINT UNSIGNED NOT NULL DEFAULT 1,
  
  -- Denormalized for query efficiency (set once at insert, never changes)
  is_winner BOOLEAN NOT NULL,
  
  -- Was any copy of this blueprint played by anyone in this game?
  -- NOTE: Until metadataVersion >= 3, attachments may be undercounted due to
  -- a bug where Attached zone cards weren't added to playedCards.
  was_played BOOLEAN NOT NULL DEFAULT FALSE,
  
  PRIMARY KEY (id),
  CONSTRAINT fk_gdc_game FOREIGN KEY (game_id) REFERENCES game_analysis(game_id) ON DELETE CASCADE,
  CONSTRAINT fk_gdc_player FOREIGN KEY (player_id) REFERENCES player(id),
  
  -- Prevent duplicate entries
  UNIQUE INDEX idx_natural_key (game_id, player_id, card_blueprint, card_role),
  
  -- Query pattern: "Card X win rate..." (most common entry point)
  INDEX idx_card (card_blueprint),
  
  -- Query pattern: "Card X win rate..." with pre-filtered wins
  INDEX idx_card_winner (card_blueprint, is_winner),
  
  -- Query pattern: "Player X's performance with card Y"
  INDEX idx_player_card (player_id, card_blueprint),
  
  -- Query pattern: "Cards commonly played alongside card X" (self-join support)
  INDEX idx_game_player (game_id, player_id),
  
  -- Query pattern: "What did the winning player run in game X" (archetype analysis)
  INDEX idx_game_winner (game_id, is_winner)
  
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- ============================================================================
-- PRE-COMPUTATION TABLES
-- Aggregated stats for fast API queries
-- ============================================================================

-- Daily card stats aggregated by tier combinations
CREATE TABLE card_stats_daily (
  card_blueprint VARCHAR(20) NOT NULL,
  format_name VARCHAR(50) NOT NULL,
  stat_date DATE NOT NULL,
  outcome_tier TINYINT NOT NULL COMMENT '1=Decisive, 2=Late Concession, 3=Ambiguous',
  competitive_tier TINYINT NOT NULL COMMENT '1=Casual, 2=League, 3=Tournament, 4=Championship',
  
  -- Inclusion-based stats
  deck_appearances INT NOT NULL DEFAULT 0,
  deck_wins INT NOT NULL DEFAULT 0,
  total_copies INT NOT NULL DEFAULT 0,
  
  -- Play-based stats (only counted when card was actually played)
  played_appearances INT NOT NULL DEFAULT 0,
  played_wins INT NOT NULL DEFAULT 0,
  
  PRIMARY KEY (card_blueprint, format_name, stat_date, outcome_tier, competitive_tier),
  INDEX idx_format_date (format_name, stat_date),
  INDEX idx_format_tiers (format_name, outcome_tier, competitive_tier)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Tracks which players included each card, enabling accurate COUNT(DISTINCT) across date ranges
CREATE TABLE card_stats_daily_players (
  card_blueprint VARCHAR(20) NOT NULL,
  format_name VARCHAR(50) NOT NULL,
  stat_date DATE NOT NULL,
  outcome_tier TINYINT NOT NULL,
  competitive_tier TINYINT NOT NULL,
  player_id INT NOT NULL,
  
  PRIMARY KEY (card_blueprint, format_name, stat_date, outcome_tier, competitive_tier, player_id),
  
  -- Query pattern: aggregate unique players for a card across date range
  INDEX idx_format_date_card (format_name, stat_date, card_blueprint),
  
  -- Foreign key for referential integrity
  CONSTRAINT fk_csdp_player FOREIGN KEY (player_id) REFERENCES player(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Balance patch markers for before/after analysis
CREATE TABLE balance_patches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  patch_name VARCHAR(100) NOT NULL UNIQUE,
  patch_date DATE NOT NULL,
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  
  INDEX idx_date (patch_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Pre-computation job tracking
CREATE TABLE stats_computation_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  computation_type ENUM('daily', 'full_rebuild') NOT NULL,
  started_at DATETIME NOT NULL,
  completed_at DATETIME,
  records_processed INT,
  status ENUM('running', 'completed', 'failed') NOT NULL,
  error_message TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- ============================================================================
-- CARD CATALOG
-- Card metadata for name lookups. Populated from HJSON via build_catalog.py
-- ============================================================================

CREATE TABLE card_catalog (
  blueprint VARCHAR(20) PRIMARY KEY,
  card_name VARCHAR(100),
  culture VARCHAR(30),
  card_type VARCHAR(30),
  side ENUM('free_peoples', 'shadow', 'other'),
  set_number SMALLINT,
  image_url VARCHAR(255),
  last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- ============================================================================
-- CORRELATION ANALYSIS
-- Pairwise card correlation data for archetype detection
-- ============================================================================

CREATE TABLE card_correlations (
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


-- ============================================================================
-- ARCHETYPE / COMMUNITY DETECTION
-- Detected card communities and deck assignments
-- ============================================================================

-- Detected card communities (archetypes)
CREATE TABLE card_communities (
  id INT AUTO_INCREMENT PRIMARY KEY,
  format_name VARCHAR(50) NOT NULL,
  side ENUM('free_peoples', 'shadow') NOT NULL,
  
  -- Stats about this community
  card_count INT NOT NULL,                -- How many cards in this community
  deck_count INT NOT NULL DEFAULT 0,      -- How many decks match this community
  avg_internal_lift FLOAT,                -- Average lift between cards in community
  
  -- Human curation
  archetype_name VARCHAR(100) NOT NULL,   -- Human-assigned name (required)
  is_valid BOOLEAN DEFAULT TRUE,          -- Human can mark as junk
  is_orphan_pool BOOLEAN NOT NULL DEFAULT FALSE,  -- Special pool for uncategorized cards
  notes TEXT,
  
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  -- Prevent duplicate names within a format/side
  UNIQUE INDEX idx_format_side_name (format_name, side, archetype_name),
  INDEX idx_archetype (archetype_name),
  INDEX idx_cc_orphan_pool (format_name, side, is_orphan_pool)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Which cards belong to which community
CREATE TABLE card_community_members (
  community_id INT NOT NULL,              -- References card_communities.id
  card_blueprint VARCHAR(20) NOT NULL,
  
  -- Card's role in the community
  membership_score FLOAT NOT NULL,        -- How central is this card (0-1)
  is_core BOOLEAN DEFAULT FALSE,          -- Appears in >70% of community decks
  membership_type ENUM('core', 'flex', 'custom') NOT NULL DEFAULT 'core',
                                          -- core: assigned by detection algorithm
                                          -- flex: added by post-processing (correlates with multiple core)
                                          -- custom: manually assigned by user
  
  PRIMARY KEY (community_id, card_blueprint),
  FOREIGN KEY (community_id) REFERENCES card_communities(id) ON DELETE CASCADE,
  INDEX idx_card (card_blueprint),
  INDEX idx_ccm_membership_type (membership_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;


-- Deck archetype assignments (computed after communities exist)
CREATE TABLE deck_archetypes (
  game_id INT NOT NULL,
  player_id INT NOT NULL,
  community_id INT NOT NULL,              -- Best matching community
  match_score FLOAT NOT NULL,             -- How well deck matches (0-1)
  
  PRIMARY KEY (game_id, player_id),
  FOREIGN KEY (community_id) REFERENCES card_communities(id) ON DELETE CASCADE,
  INDEX idx_community (community_id),
  INDEX idx_score (match_score DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;
