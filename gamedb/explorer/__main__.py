"""Run Explorer and its maintenance commands."""

import argparse
import json

from gamedb.catalog.retail import RETAIL_PLATFORMS
from gamedb.config import ProjectEnvironment

from .manuals import manual_roots, warm_manual_cache
from .previews import ArtworkPreviewCache
from .server import serve_explorer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb-explorer")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--username", default="default")
    commands = parser.add_subparsers(dest="command")
    warm = commands.add_parser("warm-manual-cache", help="Render indexed manual covers and pages into the Explorer cache")
    warm.add_argument("platform", choices=RETAIL_PLATFORMS)
    warm.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)
    if args.command == "warm-manual-cache":
        ProjectEnvironment().load()
        root = manual_roots()[args.platform]
        if root is None:
            warm.error(f"Set GAMEDB_{args.platform.upper()}_MANUAL_ROOT")
        try:
            report = warm_manual_cache(root, ArtworkPreviewCache.from_environment(), workers=args.workers)
        except (OSError, ValueError) as error:
            warm.error(str(error))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(bool(report["failures"]))
    return serve_explorer(args.host, args.port, args.username)


if __name__ == "__main__":
    raise SystemExit(main())
