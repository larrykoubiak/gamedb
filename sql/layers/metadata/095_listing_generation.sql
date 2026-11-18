-- Publish a cheap revision for the catalog data that can change between
-- scoring and artwork builds. This file also upgrades an existing catalog.
CREATE TABLE IF NOT EXISTS catalog.listing_generation (
    singleton boolean PRIMARY KEY CHECK (singleton),
    revision uuid NOT NULL,
    writer xid8 NOT NULL
);

CREATE OR REPLACE FUNCTION catalog.mark_listings_changed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- A sample refresh can issue many statements in one transaction.
    UPDATE catalog.listing_generation
    SET revision = gen_random_uuid(), writer = pg_current_xact_id()
    WHERE singleton AND writer <> pg_current_xact_id();
    RETURN NULL;
END;
$$;

CREATE OR REPLACE TRIGGER mark_listings_changed
AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON catalog.software_fact
FOR EACH STATEMENT EXECUTE FUNCTION catalog.mark_listings_changed();
CREATE OR REPLACE TRIGGER mark_listings_changed
AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON catalog.software_fact_evidence
FOR EACH STATEMENT EXECUTE FUNCTION catalog.mark_listings_changed();
CREATE OR REPLACE TRIGGER mark_listings_changed
AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON catalog.arcade_release
FOR EACH STATEMENT EXECUTE FUNCTION catalog.mark_listings_changed();
CREATE OR REPLACE TRIGGER mark_listings_changed
AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON catalog.release_fact
FOR EACH STATEMENT EXECUTE FUNCTION catalog.mark_listings_changed();

INSERT INTO catalog.listing_generation (singleton, revision, writer)
VALUES (true, gen_random_uuid(), pg_current_xact_id())
ON CONFLICT (singleton) DO UPDATE
SET revision = excluded.revision, writer = excluded.writer;
