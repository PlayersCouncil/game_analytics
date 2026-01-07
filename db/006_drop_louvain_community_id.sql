-- Migration: Drop the vestigial community_id column from card_communities
-- The Louvain cluster number is only used for initial naming and isn't needed after that.
-- archetype_name is now always set (never null) so no fallback is needed.

-- First, update any null archetype names to use the community_id before we drop it
UPDATE card_communities 
SET archetype_name = CONCAT('Archetype #', community_id)
WHERE archetype_name IS NULL OR TRIM(archetype_name) = '';

-- Drop the unique index that includes community_id
ALTER TABLE card_communities DROP INDEX idx_format_side_community;

-- Drop the column
ALTER TABLE card_communities DROP COLUMN community_id;

-- Add a new unique index on format_name + side + archetype_name
-- This prevents duplicate names within a format/side
ALTER TABLE card_communities ADD UNIQUE INDEX idx_format_side_name (format_name, side, archetype_name);
