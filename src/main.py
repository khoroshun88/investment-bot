import logging

from config import load_settings
from database import check_connection
from logging_config import setup_logging


def main() -> None:
    settings = load_settings()

    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)

    logger.info(
        "Starting %s in %s environment",
        settings.app_name,
        settings.app_env,
    )

    check_connection(settings)

    logger.info("Application startup check completed successfully")


if __name__ == "__main__":
    main()