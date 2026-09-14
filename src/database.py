import logging

import psycopg

from config import Settings


logger = logging.getLogger(__name__)


def check_connection(settings: Settings) -> None:
    logger.info("Connecting to PostgreSQL at %s:%s", settings.db_host, settings.db_port)

    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    logger.info("PostgreSQL response: %s", result)
    logger.info("Database connection test successful")

