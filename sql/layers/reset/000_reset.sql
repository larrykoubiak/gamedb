-- Reset every rebuildable GameDB layer while preserving staging.rv_files and the
-- durable local users/preferences under app.
\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
    IF to_regclass('staging.rv_files') IS NULL THEN
        RAISE EXCEPTION 'staging.rv_files is missing; refusing to reset the database';
    END IF;
END;
$$;

DROP SCHEMA IF EXISTS catalog CASCADE;
DROP SCHEMA IF EXISTS derived CASCADE;
DROP SCHEMA IF EXISTS ref CASCADE;
DROP SCHEMA IF EXISTS etl CASCADE;
DROP TABLE IF EXISTS public.archive CASCADE;
DROP TABLE IF EXISTS public.system CASCADE;

COMMIT;
