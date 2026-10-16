"""Start the standalone explorer process."""

import argparse

from .server import serve_explorer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb-explorer")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int)
    parser.add_argument("--username", default="default")
    args = parser.parse_args(argv)
    return serve_explorer(args.host, args.port, args.username)


if __name__ == "__main__":
    raise SystemExit(main())
