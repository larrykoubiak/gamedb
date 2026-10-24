"""Explicit import of a version-matched MAME metadata pair."""

import argparse
import json
from pathlib import Path

from gamedb.database import create_database_engine

from .importer import import_fbneo, import_mame
from .samples import import_samples, refresh_sample_plans


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gamedb import-arcade")
    parser.add_argument("xml", type=Path)
    parser.add_argument("--emulator", choices=("MAME", "FBNeo"), default="MAME")
    parser.add_argument("--arcade-dat", type=Path)
    parser.add_argument("--rom-dat-path", required=True)
    parser.add_argument("--chd-dat-path")
    parser.add_argument("--samples-dat", type=Path)
    parser.add_argument("--samples-dat-path")
    parser.add_argument(
        "--refresh-samples",
        action="store_true",
        help="Refresh existing sample plans without rebuilding identities; rerun catalog scoring afterward",
    )
    args = parser.parse_args(argv)
    if bool(args.samples_dat) != bool(args.samples_dat_path):
        parser.error("--samples-dat and --samples-dat-path must be supplied together")
    if args.refresh_samples and not args.samples_dat:
        parser.error("--refresh-samples requires the samples DAT")
    if args.samples_dat and args.emulator != "FBNeo":
        parser.error("Sample imports currently support FBNeo only")
    if args.emulator == "FBNeo":
        engine = create_database_engine()
        result = import_fbneo(engine, args.xml, args.rom_dat_path)
        if args.samples_dat:
            result["sampleSets"] = import_samples(
                engine, result["source"], args.samples_dat, args.samples_dat_path
            )
        if args.refresh_samples:
            result["samplePlansRefreshed"] = refresh_sample_plans(
                engine, result["source"]
            )
        print(json.dumps(result, indent=2))
        return 0
    if not args.arcade_dat or not args.chd_dat_path:
        parser.error("MAME requires --arcade-dat and --chd-dat-path")
    print(
        json.dumps(
            import_mame(
                create_database_engine(),
                args.xml,
                args.arcade_dat,
                args.rom_dat_path,
                args.chd_dat_path,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
