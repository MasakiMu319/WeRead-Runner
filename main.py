import asyncio
import logging

from runner import run
from settings import load_settings


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)-8s - %(message)s"
    )


def main() -> None:
    setup_logging()
    settings = load_settings()
    logging.info("ℹ️ PUSH_METHOD=%s", (settings.push_method or "").strip() or "EMPTY")
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
