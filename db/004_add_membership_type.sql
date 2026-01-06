-- Migration: Add membership_type to card_community_members
-- 
-- membership_type values:
--   'core'   - Cards assigned by Louvain algorithm (or the primary detection algorithm)
--   'flex'   - Cards added by post-processing because they correlate with multiple core members
--   'custom' - Cards manually assigned by users via submitted archetypes
--
-- Run this migration before deploying the updated detect_archetypes.py

ALTER TABLE card_community_members 
ADD COLUMN membership_type ENUM('core', 'flex', 'custom') NOT NULL DEFAULT 'core'
AFTER is_core;

-- Update existing data (all current entries are from Louvain, so mark as 'core')
UPDATE card_community_members SET membership_type = 'core' WHERE membership_type = 'core';

-- Add index for filtering by type
CREATE INDEX idx_ccm_membership_type ON card_community_members(membership_type);
