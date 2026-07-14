-- Owner-approved controlled placeholders for legacy employees with no BU/role.
-- Grain: these are reference values, never inferred employee facts.
-- Forward verification: the two references exist and the remediation command is audited.
-- Rollback: restore the pre-remediation backup; do not delete audited history selectively.

INSERT INTO business_units(business_unit_name, is_active) VALUES ('Unknown BU', TRUE)
ON CONFLICT (business_unit_name) DO NOTHING;
INSERT INTO job_roles(job_role_name, is_active) VALUES ('Unknown Role', TRUE)
ON CONFLICT (job_role_name) DO NOTHING;
