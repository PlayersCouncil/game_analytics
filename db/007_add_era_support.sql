-- Migration: Add era/patch support to correlations and communities
-- 
-- This migration adds patch_id foreign keys to card_correlations and card_communities,
-- enabling per-era analysis. After running this migration:
-- 1. Ensure at least one patch exists in balance_patches
-- 2. Re-run compute_correlations.py to regenerate correlations per patch
-- 3. Re-run detect_archetypes.py to regenerate communities per patch
--
-- WARNING: This migration will DELETE all existing correlations and communities
-- since they lack patch associations. They must be regenerated.

-- ============================================================================
-- STEP 1: Clear existing data (will be regenerated with patch associations)
-- ============================================================================

-- Delete community members first (foreign key constraint)
DELETE FROM card_community_members;

-- Delete deck archetype assignments
DELETE FROM deck_archetypes;

-- Delete communities
DELETE FROM card_communities;

-- Delete correlations
DELETE FROM card_correlations;


-- ============================================================================
-- STEP 2: Modify card_correlations table
-- ============================================================================

-- Add patch_id column
ALTER TABLE card_correlations 
ADD COLUMN patch_id INT NOT NULL AFTER side;

-- Drop old primary key and indexes
ALTER TABLE card_correlations DROP PRIMARY KEY;
ALTER TABLE card_correlations DROP INDEX idx_card_a_lift;
ALTER TABLE card_correlations DROP INDEX idx_card_b_lift;
ALTER TABLE card_correlations DROP INDEX idx_format_lift;

-- Add new primary key including patch_id
ALTER TABLE card_correlations 
ADD PRIMARY KEY (card_a, card_b, format_name, side, patch_id);

-- Add foreign key constraint
ALTER TABLE card_correlations
ADD CONSTRAINT fk_corr_patch FOREIGN KEY (patch_id) REFERENCES balance_patches(id) ON DELETE CASCADE;

-- Add new indexes that include patch_id
CREATE INDEX idx_card_a_patch_lift ON card_correlations (card_a, format_name, side, patch_id, lift DESC);
CREATE INDEX idx_card_b_patch_lift ON card_correlations (card_b, format_name, side, patch_id, lift DESC);
CREATE INDEX idx_format_patch_lift ON card_correlations (format_name, side, patch_id, lift DESC);


-- ============================================================================
-- STEP 3: Modify card_communities table
-- ============================================================================

-- Add patch_id column
ALTER TABLE card_communities 
ADD COLUMN patch_id INT NOT NULL AFTER side;

-- Drop old unique index
ALTER TABLE card_communities DROP INDEX idx_format_side_name;
ALTER TABLE card_communities DROP INDEX idx_cc_orphan_pool;

-- Add foreign key constraint
ALTER TABLE card_communities
ADD CONSTRAINT fk_comm_patch FOREIGN KEY (patch_id) REFERENCES balance_patches(id) ON DELETE CASCADE;

-- Add new indexes that include patch_id
CREATE UNIQUE INDEX idx_format_side_patch_name ON card_communities (format_name, side, patch_id, archetype_name);
CREATE INDEX idx_cc_orphan_pool ON card_communities (format_name, side, patch_id, is_orphan_pool);
CREATE INDEX idx_cc_patch ON card_communities (patch_id);
