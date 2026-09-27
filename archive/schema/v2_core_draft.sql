-- GameDB v2 core PostgreSQL schema
--
-- Identity chain:
-- system -> release -> package -> artifact
--
-- Definitions:
-- - system: execution/platform context
-- - release: product a customer could buy/acquire for a system
-- - package: one owned/logical grouped unit mapped to a release
-- - artifact: one concrete file within a package

CREATE TABLE systems (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    short_name      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE releases (
    id              BIGSERIAL PRIMARY KEY,
    system_id       BIGINT NOT NULL REFERENCES systems(id) ON DELETE RESTRICT,

    display_name    TEXT NOT NULL,
    sort_name       TEXT,

    region          TEXT,
    publisher       TEXT,
    developer       TEXT,

    release_year    INTEGER,
    release_month   INTEGER,
    release_day     INTEGER,

    serial          TEXT,
    version_label   TEXT,
    revision_label  TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (release_year IS NULL OR release_year >= 1950),
    CHECK (release_month IS NULL OR release_month BETWEEN 1 AND 12),
    CHECK (release_day IS NULL OR release_day BETWEEN 1 AND 31)
);

CREATE INDEX idx_releases_system_id ON releases(system_id);
CREATE INDEX idx_releases_display_name ON releases(display_name);
CREATE INDEX idx_releases_serial ON releases(serial);

CREATE TABLE release_titles (
    id              BIGSERIAL PRIMARY KEY,
    release_id      BIGINT NOT NULL REFERENCES releases(id) ON DELETE CASCADE,

    title           TEXT NOT NULL,
    title_type      TEXT NOT NULL DEFAULT 'official',
    language_code   TEXT,
    region          TEXT,
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_release_titles_release_id ON release_titles(release_id);
CREATE INDEX idx_release_titles_title ON release_titles(title);

CREATE TABLE packages (
    id              BIGSERIAL PRIMARY KEY,
    release_id      BIGINT REFERENCES releases(id) ON DELETE SET NULL,

    label           TEXT,
    package_type    TEXT NOT NULL,
    source          TEXT,
    container_path  TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_packages_release_id ON packages(release_id);
CREATE INDEX idx_packages_source ON packages(source);

CREATE TABLE artifacts (
    id              BIGSERIAL PRIMARY KEY,

    filename        TEXT NOT NULL,
    size_bytes      BIGINT,
    crc32           TEXT,
    md5             TEXT,
    sha1            TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (size_bytes IS NULL OR size_bytes >= 0)
);

CREATE INDEX idx_artifacts_crc32 ON artifacts(crc32);
CREATE INDEX idx_artifacts_md5 ON artifacts(md5);
CREATE INDEX idx_artifacts_sha1 ON artifacts(sha1);

CREATE TABLE package_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    package_id      BIGINT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    artifact_id     BIGINT NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,

    relative_path   TEXT,
    role            TEXT,
    ordinal         INTEGER,

    UNIQUE (package_id, artifact_id, relative_path)
);

CREATE INDEX idx_package_artifacts_package_id ON package_artifacts(package_id);
CREATE INDEX idx_package_artifacts_artifact_id ON package_artifacts(artifact_id);
