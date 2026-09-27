"""Load local connection settings without overriding the process environment."""

from pathlib import Path


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_environment(path: str | Path | None = None) -> None:
    from dotenv import load_dotenv

    # Connection secrets are literal values, including any ${...} in passwords.
    load_dotenv(ENV_FILE if path is None else path, override=False, interpolate=False)
