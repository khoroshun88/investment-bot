import logging

import psycopg

from config import Settings


logger = logging.getLogger(__name__)


def get_connection(settings: Settings):
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


def check_connection(settings: Settings) -> None:
    logger.info(
        "Connecting to PostgreSQL at %s:%s",
        settings.db_host,
        settings.db_port,
    )

    with get_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    logger.info("PostgreSQL response: %s", result)
    logger.info("Database connection test successful")


def init_database(settings: Settings) -> None:
    logger.info("Initializing database")

    with get_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_uid TEXT PRIMARY KEY,

                    figi TEXT,
                    ticker TEXT,
                    class_code TEXT,
                    isin TEXT,
                    name TEXT,

                    instrument_type TEXT,
                    currency TEXT,
                    lot INTEGER,
                    exchange TEXT,

                    country_of_risk TEXT,
                    country_of_risk_name TEXT,

                    for_iis_flag BOOLEAN,
                    for_qual_investor_flag BOOLEAN,
                    buy_available_flag BOOLEAN,
                    sell_available_flag BOOLEAN,

                    min_price_increment NUMERIC,

                    position_uid TEXT,
                    asset_uid TEXT,

                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    logger.info("Database initialization completed")
    init_strategy_positions_table(settings)


def save_instruments(settings: Settings, instruments: dict) -> None:
    if not instruments:
        logger.warning("No instrument metadata to save")
        return

    logger.info(
        "Saving instrument metadata: instruments=%d",
        len(instruments),
    )

    with get_connection(settings) as connection:
        with connection.cursor() as cursor:
            for instrument_uid, instrument in instruments.items():
                cursor.execute(
                    """
                    INSERT INTO instruments (
                        instrument_uid,
                        figi,
                        ticker,
                        class_code,
                        isin,
                        name,
                        instrument_type,
                        currency,
                        lot,
                        exchange,
                        country_of_risk,
                        country_of_risk_name,
                        for_iis_flag,
                        for_qual_investor_flag,
                        buy_available_flag,
                        sell_available_flag,
                        min_price_increment,
                        position_uid,
                        asset_uid,
                        updated_at
                    )
                    VALUES (
                        %(instrument_uid)s,
                        %(figi)s,
                        %(ticker)s,
                        %(class_code)s,
                        %(isin)s,
                        %(name)s,
                        %(instrument_type)s,
                        %(currency)s,
                        %(lot)s,
                        %(exchange)s,
                        %(country_of_risk)s,
                        %(country_of_risk_name)s,
                        %(for_iis_flag)s,
                        %(for_qual_investor_flag)s,
                        %(buy_available_flag)s,
                        %(sell_available_flag)s,
                        %(min_price_increment)s,
                        %(position_uid)s,
                        %(asset_uid)s,
                        NOW()
                    )
                    ON CONFLICT (instrument_uid)
                    DO UPDATE SET
                        figi = EXCLUDED.figi,
                        ticker = EXCLUDED.ticker,
                        class_code = EXCLUDED.class_code,
                        isin = EXCLUDED.isin,
                        name = EXCLUDED.name,
                        instrument_type = EXCLUDED.instrument_type,
                        currency = EXCLUDED.currency,
                        lot = EXCLUDED.lot,
                        exchange = EXCLUDED.exchange,
                        country_of_risk = EXCLUDED.country_of_risk,
                        country_of_risk_name = EXCLUDED.country_of_risk_name,
                        for_iis_flag = EXCLUDED.for_iis_flag,
                        for_qual_investor_flag = EXCLUDED.for_qual_investor_flag,
                        buy_available_flag = EXCLUDED.buy_available_flag,
                        sell_available_flag = EXCLUDED.sell_available_flag,
                        min_price_increment = EXCLUDED.min_price_increment,
                        position_uid = EXCLUDED.position_uid,
                        asset_uid = EXCLUDED.asset_uid,
                        updated_at = NOW()
                    """,
                    instrument,
                )

    logger.info(
        "Instrument metadata saved successfully: instruments=%d",
        len(instruments),
    )

def init_strategy_positions_table(settings: Settings) -> None:
    logger.info("Initializing strategy_positions table")

    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_positions (
                    instrument_uid TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_price NUMERIC(20, 9) NOT NULL,
                    stop_loss NUMERIC(20, 9) NOT NULL,
                    take_profit NUMERIC(20, 9) NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    opened_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    CONSTRAINT strategy_positions_side
                        CHECK (side IN ('LONG')),

                    CONSTRAINT strategy_positions_quantity
                        CHECK (quantity >= 0)
                )
                """
            )

    logger.info("strategy_positions table initialized")

def init_strategy_trades_table(settings: Settings) -> None:
    logger.info("Initializing strategy_trades table")

    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_trades (
                    id BIGSERIAL PRIMARY KEY,

                    instrument_uid TEXT NOT NULL,
                    side TEXT NOT NULL,

                    entry_price NUMERIC(20, 9) NOT NULL,
                    exit_price NUMERIC(20, 9) NOT NULL,

                    quantity INTEGER NOT NULL DEFAULT 0,

                    stop_loss NUMERIC(20, 9) NOT NULL,
                    take_profit NUMERIC(20, 9) NOT NULL,

                    close_reason TEXT NOT NULL,

                    opened_at TIMESTAMPTZ NOT NULL,
                    closed_at TIMESTAMPTZ NOT NULL,

                    pnl NUMERIC(20, 9) NOT NULL,

                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    CONSTRAINT strategy_trades_side
                        CHECK (side IN ('LONG')),

                    CONSTRAINT strategy_trades_quantity
                        CHECK (quantity >= 0)
                )
                """
            )

    logger.info("strategy_trades table initialized")