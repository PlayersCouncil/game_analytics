-- Migration: Add orphan pool flag to card_communities
-- 
-- The orphan pool is a special community that holds cards that:
--   - Don't meet threshold for any archetype
--   - Were removed from a community manually
--   - Came from a deleted community with no clear best fit
--
-- Each format/side pair should have exactly one orphan pool.
-- The orphan pool cannot be deleted or marked invalid.

ALTER TABLE card_communities 
ADD COLUMN is_orphan_pool BOOLEAN NOT NULL DEFAULT FALSE
AFTER is_valid;

-- Index for quick lookup
CREATE INDEX idx_cc_orphan_pool ON card_communities(format_name, side, is_orphan_pool);
