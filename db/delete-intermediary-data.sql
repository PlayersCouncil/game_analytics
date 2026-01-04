

-- Run this to wipe out any entries that aren't needed anymore

DELETE FROM game_deck_cards 
WHERE game_id IN (
    SELECT game_id FROM game_analysis 
    WHERE game_date < DATE_SUB(CURDATE(), INTERVAL 90 DAY)
)
LIMIT 1000000;
	
SELECT COUNT(*) FROM game_deck_cards;



-- 1. Remaining game_deck_cards should only be recent
SELECT MIN(ga.game_date) AS oldest_deck_card_date
FROM game_deck_cards gdc
INNER JOIN game_analysis ga ON ga.game_id = gdc.game_id;
-- Should be ~90 days ago

-- 2. game_analysis still intact (shouldn't have touched it)
SELECT COUNT(*) AS total_games, 
       MIN(game_date) AS oldest, 
       MAX(game_date) AS newest 
FROM game_analysis;

-- 3. card_stats_daily still intact (the actual data the UI uses)
SELECT COUNT(*) AS stat_rows,
       MIN(stat_date) AS oldest,
       MAX(stat_date) AS newest
FROM card_stats_daily;

-- 4. Quick functional check - should return data
SELECT card_blueprint, SUM(deck_appearances) as games
FROM card_stats_daily
WHERE format_name = 'Movie Block (PC)'
GROUP BY card_blueprint
ORDER BY games DESC
LIMIT 5;




-- read how big the table is now
SELECT table_name, 
       ROUND(data_length / 1024 / 1024, 2) AS data_mb,
       ROUND(index_length / 1024 / 1024, 2) AS index_mb
FROM information_schema.tables 
WHERE table_schema = 'gemp_db' 
  AND table_name = 'game_deck_cards';
  
 
 -- Use this to force innodb to reclaim the space saved
 OPTIMIZE TABLE game_deck_cards;
 