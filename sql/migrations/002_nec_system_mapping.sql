-- Apply after 001_system_mapping.sql. This records the reviewed NEC policy:
-- PC-88 -> PC-8801, PC-98 -> PC-9801, combined PC-FX/PC-FXGA -> PC-FX.
-- Dedicated PC-FXGA collections retain their own canonical system.
-- Unlike discovery/refresh, this migration intentionally replaces the earlier
-- NEC decisions. Safe to rerun; only changed rows are updated.
BEGIN;

INSERT INTO ref.canonical_system
    (canonical_manufacturer_name, canonical_system_name)
VALUES ('NEC', 'PC-FXGA')
ON CONFLICT (canonical_manufacturer_name, canonical_system_name) DO NOTHING;

INSERT INTO ref.system_mapping AS existing
    (manufacturer, system, canonical_manufacturer_name, canonical_system_name,
     match_method, notes)
VALUES
    ('NEC', 'PC-88 series', 'NEC', 'PC-8801', 'manual',
     'Reviewed policy: map the broad PC-88 collection to PC-8801.'),
    ('NEC', 'PC-98 series', 'NEC', 'PC-9801', 'manual',
     'Reviewed policy: map the broad PC-98 collection to PC-9801.'),
    ('NEC', 'PC-FX & PC-FXGA', 'NEC', 'PC-FX', 'manual',
     'Reviewed policy: map the combined PC-FX and PC-FXGA collection to PC-FX.'),
    ('NEC', 'PC-FXGA', 'NEC', 'PC-FXGA', 'exact', NULL)
ON CONFLICT (manufacturer, system) DO UPDATE
SET canonical_manufacturer_name = EXCLUDED.canonical_manufacturer_name,
    canonical_system_name = EXCLUDED.canonical_system_name,
    match_method = EXCLUDED.match_method,
    notes = EXCLUDED.notes
WHERE (existing.canonical_manufacturer_name, existing.canonical_system_name,
       existing.match_method, existing.notes)
    IS DISTINCT FROM
      (EXCLUDED.canonical_manufacturer_name, EXCLUDED.canonical_system_name,
       EXCLUDED.match_method, EXCLUDED.notes);

COMMIT;
