-- Repair the placeholder's technical numeric value.  The source workbook owns
-- 0.0 for its real 'Not Placement' level, so the placeholder must not collide.
-- 6.4 is reserved exclusively for Unknown Entrance Level and is not a measured level.

UPDATE levels
SET numeric_value = 6.4
WHERE level_name = 'Unknown Entrance Level';
