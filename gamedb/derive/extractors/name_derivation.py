"""Stream stable archive-name identities through the Python interpreter."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

from sqlalchemy import select
from sqlalchemy.engine import Engine

from gamedb.derive.parser.structure import should_ignore_archive_name

from ..schema import archive_name
from ..writer import DerivedBulkWriter, InterpretationSpool
from .archive_name_extract import ArchiveNameExtractor


class NameDerivation:
    """Produce records, tags, assertions, and media in one streaming pass."""

    version = "1"

    def __init__(self):
        self.extractor = ArchiveNameExtractor()
        self.writer = DerivedBulkWriter()

    def execute(self, engine: Engine) -> dict[str, int]:
        started = time.monotonic()
        visited = 0
        with tempfile.TemporaryDirectory(prefix="gamedb-derive-") as directory:
            with InterpretationSpool(Path(directory)) as spool:
                with engine.connect() as reader:
                    rows = reader.execution_options(yield_per=2000).execute(
                        select(
                            archive_name.c.id,
                            archive_name.c.romset,
                            archive_name.c.archive_name,
                        ).where(archive_name.c.romset.not_in(("MAME", "FBNeo"))).order_by(archive_name.c.id)
                    )
                    for row in rows:
                        visited += 1
                        if should_ignore_archive_name(row.romset, row.archive_name):
                            continue
                        spool.write(
                            row.id,
                            self.extractor.extract(row.romset, row.archive_name),
                        )
                        if visited % 25_000 == 0:
                            elapsed = int(time.monotonic() - started)
                            print(
                                f"  interpreted {visited:,} archive names ({elapsed}s)",
                                flush=True,
                            )
            with engine.begin() as connection:
                self.writer.replace(connection, spool)
            return spool.counts.copy()
