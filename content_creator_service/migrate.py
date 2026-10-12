"""Simple migration runner for the content creator service."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure src/ is importable when running as a script
CURRENT_DIR = Path(__file__).parent
sys.path.append(str(CURRENT_DIR))

from src.migrations_runner import apply_all_migrations  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main() -> None:
    load_dotenv(CURRENT_DIR.parent / ".env")
    apply_all_migrations()


if __name__ == "__main__":
    main()
