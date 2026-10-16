"""Promote reviewed working software corrections into maintained reference."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import tempfile

from sqlalchemy import text
from sqlalchemy.engine import Engine


FIELDNAMES = (
    "manufacturer_name", "system_name", "subject_content_signature",
    "action", "target_content_signature", "note",
)


class SoftwareCorrectionPromoter:
    """Validate, export, materialize, and archive active corrections."""

    def __init__(self, engine: Engine, path: Path):
        self.engine = engine
        self.path = path

    def execute(self) -> int:
        with self.engine.connect() as connection:
            working = [dict(row) for row in connection.execute(text("""
                SELECT id, manufacturer_name, system_name,
                    subject_content_signature, action,
                    target_content_signature, note
                FROM app.software_correction
                WHERE status = 'active'
                ORDER BY manufacturer_name, system_name,
                    subject_content_signature, id
            """)).mappings()]
            self._validate(connection, working)
        if not working:
            return 0

        reviewed = self._read()
        keyed = {
            self._key(row): row for row in reviewed
        }
        for row in working:
            exported = {field: row[field] or "" for field in FIELDNAMES}
            key = self._key(exported)
            existing = keyed.get(key)
            if existing is not None and existing != exported:
                raise ValueError(
                    "promoted correction conflicts with reference subject "
                    + "/".join(key)
                )
            keyed[key] = exported
        rows = sorted(keyed.values(), key=self._key)
        self._write(rows)

        with self.engine.begin() as connection:
            for row in working:
                connection.execute(text("""
                    INSERT INTO ref.software_correction (
                        manufacturer_name, system_name,
                        subject_content_signature, action,
                        target_content_signature, note
                    ) VALUES (
                        :manufacturer_name, :system_name,
                        :subject_content_signature, :action,
                        :target_content_signature, :note
                    )
                    ON CONFLICT DO NOTHING
                """), row)
            for row in working:
                connection.execute(text("""
                    UPDATE app.software_correction
                    SET status = 'promoted', promoted_at = current_timestamp
                    WHERE id = :id AND status = 'active'
                """), {"id": row["id"]})
        return len(working)

    @staticmethod
    def _validate(connection, rows: list[dict]) -> None:
        for row in rows:
            result = connection.execute(text("""
                WITH selected_system AS (
                    SELECT id FROM catalog.system
                    WHERE manufacturer_name = :manufacturer_name
                      AND system_name = :system_name
                ), subject AS (
                    SELECT count(*) AS release_count
                    FROM selected_system system
                    JOIN catalog.title title ON title.system_id = system.id
                    JOIN catalog.release release ON release.title_id = title.id
                    JOIN catalog.release_content_signature signature
                      ON signature.release_id = release.id
                    WHERE signature.sha1_set_digest
                        = :subject_content_signature
                ), target AS (
                    SELECT count(*) AS release_count,
                        count(DISTINCT membership.software_id) AS software_count
                    FROM selected_system system
                    JOIN catalog.title title ON title.system_id = system.id
                    JOIN catalog.release release ON release.title_id = title.id
                    JOIN catalog.release_content_signature signature
                      ON signature.release_id = release.id
                    JOIN catalog.software_release membership
                      ON membership.release_id = release.id
                    WHERE signature.sha1_set_digest
                        = :target_content_signature
                )
                SELECT EXISTS (SELECT 1 FROM selected_system) AS system_exists,
                    subject.release_count AS subject_count,
                    target.release_count AS target_count,
                    target.software_count AS target_software_count
                FROM subject CROSS JOIN target
            """), row).mappings().one()
            if not result["system_exists"] or result["subject_count"] == 0:
                raise ValueError(
                    f"working correction {row['id']} no longer resolves"
                )
            if row["action"] == "assign" and (
                result["target_count"] == 0
                or result["target_software_count"] != 1
            ):
                raise ValueError(
                    f"working correction {row['id']} target is ambiguous"
                )

    def _read(self) -> list[dict[str, str]]:
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != FIELDNAMES:
                raise ValueError("software correction CSV has an invalid header")
            return list(reader)

    def _write(self, rows: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=self.path.name + ".", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _key(row: dict) -> tuple[str, str, str]:
        return (
            row["manufacturer_name"], row["system_name"],
            row["subject_content_signature"],
        )
