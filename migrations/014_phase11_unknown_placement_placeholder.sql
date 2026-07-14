-- Owner-approved controlled placeholder for legacy learners without a business placement.
-- It represents unavailable source data, not a measured proficiency level.
-- Forward verification: reference exists and the remediation command is audited.
-- Rollback: restore the pre-remediation backup; do not delete placement history selectively.

INSERT INTO levels(level_name, numeric_value, sequence_order)
VALUES ('Unknown Entrance Level', 0.0, 32767)
ON CONFLICT (level_name) DO NOTHING;

COMMENT ON TABLE placements IS
    'Business placement is an observed entrance-level record; legacy Unknown Entrance Level is an explicit unavailable-source placeholder.';
