"""Opt-in integration check using a disposable database cloned by schema only.

GAMEDB_INTEGRATION=1 plus .env or libpq PG* settings enables this test. The connection
must be able to create databases; the configured source database is read only.
"""

import os
import subprocess
import unittest
import uuid


@unittest.skipUnless(os.environ.get("GAMEDB_INTEGRATION") == "1", "set GAMEDB_INTEGRATION=1 for disposable database checks")
class CoreDatabaseTests(unittest.TestCase):
    def test_identity_lifecycle(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from gamedb.config import load_environment
        from gamedb.romvault.importer import parse_archive_names, sync_sources

        load_environment()
        database = "gamedb_core_test_" + uuid.uuid4().hex[:12]
        schema = subprocess.run(
            ["pg_dump", "--schema-only", "--no-owner", "--no-privileges",
             "--schema=public", "--schema=ref", "--schema=etl", "--schema=staging"],
            check=True, capture_output=True, text=True,
        ).stdout
        # Newer pg_dump clients emit this session setting even for PG16 sources.
        # It does not exist on PG16 and is unrelated to the exported DDL.
        schema = schema.replace("SET transaction_timeout = 0;\n", "")
        with psycopg.connect("", autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
            try:
                restored = subprocess.run(
                    ["psql", "-X", "-v", "ON_ERROR_STOP=1"], input="DROP SCHEMA public;\n" + schema,
                    env={**os.environ, "PGDATABASE": database}, capture_output=True, text=True,
                )
                self.assertEqual(restored.returncode, 0, restored.stderr)
                conninfo = make_conninfo(dbname=database)
                with psycopg.connect(conninfo) as connection:
                    # Core foreign keys must follow the source tables into etl.
                    # Generated objects must not drift back into the ref layer.
                    for name in ("dat", "archive_name", "system_mapping", "v_archive", "v_romset"):
                        self.assertIsNotNone(connection.execute("SELECT to_regclass(%s)", (f"etl.{name}",)).fetchone()[0])
                        self.assertIsNone(connection.execute("SELECT to_regclass(%s)", (f"ref.{name}",)).fetchone()[0])
                    targets = connection.execute("""
                        SELECT target_ns.nspname, target.relname
                        FROM pg_constraint fk
                        JOIN pg_class target ON target.oid = fk.confrelid
                        JOIN pg_namespace target_ns ON target_ns.oid = target.relnamespace
                        WHERE fk.conrelid = 'public.archive'::regclass AND fk.contype = 'f'
                    """).fetchall()
                    self.assertEqual(set(targets), {("etl", "dat"), ("etl", "archive_name"), ("public", "system")})
                    connection.execute("INSERT INTO public.system(manufacturer_name, name) VALUES ('ID Test', 'Alpha'), ('ID Test', 'Beta')")

                    def add_source(system, filenames):
                        for filename in filenames:
                            connection.execute("""
                                INSERT INTO staging.rv_files (
                                    run_id, exported_at, tree_full_name, name,
                                    file_type, is_dir, dat_status, got_status, rep_status,
                                    sha1_verified, md5_verified, crc_verified, size_verified, deep_scanned,
                                    dat_name, dat_root_full_name, game_display_name
                                ) VALUES (%s, now(), %s, %s, 5, false, 0, 0, 0,
                                          false, false, false, false, false, %s, %s, %s)
                            """, (
                                uuid.UUID("57240e56-a470-4d3a-9cdc-2fa7de08ab84"),
                                f"RomVault/No-Intro/{system}/Same Name (World).zip/{filename}", filename,
                                f"ID Test - {system}", f"DatRoot/No-Intro/ID Test - {system}.dat",
                                "Same Name (World).zip",
                            ))

                    add_source("Alpha", ["track01.bin", "track02.bin"])
                    add_source("Beta", ["game.rom"])
                    connection.commit()

                    first = sync_sources(conninfo)
                    self.assertEqual(first["archives_changed"], 2)
                    self.assertEqual(first["names_added"], 1)
                    archives = connection.execute("""
                        SELECT a.id, a.dat_id, a.archive_name_id, a.system_id,
                               a.staged_row_count, d.system
                        FROM public.archive a JOIN etl.dat d ON d.id = a.dat_id ORDER BY d.system
                    """).fetchall()
                    alpha, beta = archives
                    self.assertNotEqual(alpha[0], beta[0])
                    self.assertEqual(alpha[2], beta[2])  # shared spelling, distinct archives/systems
                    self.assertNotEqual(alpha[3], beta[3])
                    self.assertEqual((alpha[4], beta[4]), (2, 1))
                    self.assertEqual(connection.execute("SELECT parse_status FROM etl.archive_name").fetchone()[0], "pending")

                    parsed = parse_archive_names(conninfo=conninfo)
                    self.assertEqual(parsed["changed"], 1)
                    self.assertEqual(connection.execute("SELECT id, title_candidate, tags->0->>'value' FROM etl.archive_name").fetchone(), (alpha[2], "Same Name", "World"))

                    # A canonical rename and a manual per-archive override must
                    # survive source refresh and parser reruns without new IDs.
                    connection.execute("UPDATE public.system SET name = 'Renamed Beta' WHERE id = %s", (beta[3],))
                    connection.execute("UPDATE public.archive SET system_id = %s, system_assignment = 'manual' WHERE id = %s", (beta[3], alpha[0]))
                    connection.commit()
                    unchanged = sync_sources(conninfo)
                    self.assertTrue(all(value == 0 for value in unchanged.values()), unchanged)
                    self.assertEqual(parse_archive_names(reparse=True, conninfo=conninfo)["changed"], 0)
                    self.assertEqual(connection.execute("SELECT id, dat_id, archive_name_id FROM public.archive ORDER BY id").fetchall(), sorted([alpha[:3], beta[:3]]))
                    self.assertEqual(connection.execute("SELECT system_id FROM public.archive WHERE id = %s", (alpha[0],)).fetchone()[0], beta[3])
                    self.assertEqual(connection.execute("SELECT canonical_system_name FROM etl.v_archive WHERE archive_id = %s", (alpha[0],)).fetchone()[0], "Renamed Beta")

                    with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                        with connection.transaction():
                            connection.execute("UPDATE public.archive SET system_id = -1 WHERE id = %s", (alpha[0],))
                    with self.assertRaises(psycopg.errors.UniqueViolation):
                        with connection.transaction():
                            connection.execute("INSERT INTO public.archive(dat_id, archive_name_id, staged_row_count) VALUES (%s, %s, 1)", (alpha[1], alpha[2]))

                    # Disappearing source data retires presence, not identities.
                    connection.execute("DELETE FROM staging.rv_files WHERE dat_name = 'ID Test - Alpha'")
                    connection.commit()
                    self.assertEqual(sync_sources(conninfo)["archives_absent"], 1)
                    self.assertEqual(connection.execute("SELECT is_present FROM public.archive WHERE id = %s", (alpha[0],)).fetchone()[0], False)
                    add_source("Alpha", ["track01.bin", "track02.bin"])
                    connection.commit()
                    sync_sources(conninfo)
                    self.assertEqual(connection.execute("SELECT id, system_id, is_present FROM public.archive WHERE dat_id = %s", (alpha[1],)).fetchone(), (alpha[0], beta[3], True))
            finally:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


if __name__ == "__main__":
    unittest.main()
