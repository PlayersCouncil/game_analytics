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


-- Optional: Card catalog for name lookups
-- Populated from HJSON via build_catalog.py
CREATE TABLE card_catalog (
  blueprint VARCHAR(20) PRIMARY KEY,
  card_name VARCHAR(100),
  subtitle VARCHAR(100),
  culture VARCHAR(30),
  card_type VARCHAR(30),
  side ENUM('free_peoples', 'shadow', 'site'),
  twilight_cost TINYINT,
  set_number SMALLINT,
  image_url VARCHAR(255),
  last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_bin;
