-- Migration: Add player spread tracking
-- Run this on production before deploying the new code

-- Create the new table for tracking unique players per card
CREATE TABLE IF NOT EXISTS card_stats_daily_players (
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
