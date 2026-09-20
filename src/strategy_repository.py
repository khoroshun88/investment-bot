import logging
from datetime import datetime, timezone
from decimal import Decimal

import psycopg

from config import Settings
from strategy import Position


logger = logging.getLogger(__name__)


def save_position(
    settings: Settings,
    instrument_uid: str,
    position: Position,
) -> None:
    """
    Сохраняет текущую виртуальную позицию Strategy
    в PostgreSQL.

    Для каждого instrument_uid существует максимум одна
    открытая позиция.
    """

    logger.info(
        "Saving strategy position: "
        "instrument=%s side=%s quantity=%d "
        "entry=%s SL=%s TP=%s",
        instrument_uid,
        position.side,
        position.quantity,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
    )

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
                INSERT INTO strategy_positions (
                    instrument_uid,
                    side,
                    entry_price,
                    stop_loss,
                    take_profit,
                    quantity,
                    opened_at,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW()
                )
                ON CONFLICT (instrument_uid)
                DO UPDATE SET
                    side = EXCLUDED.side,
                    entry_price = EXCLUDED.entry_price,
                    stop_loss = EXCLUDED.stop_loss,
                    take_profit = EXCLUDED.take_profit,
                    quantity = EXCLUDED.quantity,
                    opened_at = EXCLUDED.opened_at,
                    updated_at = NOW()
                """,
                (
                    instrument_uid,
                    position.side,
                    position.entry_price,
                    position.stop_loss,
                    position.take_profit,
                    position.quantity,
                    position.opened_at,
                ),
            )

    logger.info(
        "Strategy position saved: "
        "instrument=%s side=%s quantity=%d "
        "entry=%s SL=%s TP=%s",
        instrument_uid,
        position.side,
        position.quantity,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
    )


def load_position(
    settings: Settings,
    instrument_uid: str,
) -> Position | None:
    """
    Загружает виртуальную позицию конкретного инструмента.

    Если позиции нет — возвращает None.
    """

    logger.info(
        "Loading strategy position: instrument=%s",
        instrument_uid,
    )

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
                SELECT
                    side,
                    entry_price,
                    stop_loss,
                    take_profit,
                    quantity,
                    opened_at
                FROM strategy_positions
                WHERE instrument_uid = %s
                """,
                (instrument_uid,),
            )

            row = cursor.fetchone()

    if row is None:
        logger.info(
            "No saved strategy position: instrument=%s",
            instrument_uid,
        )
        return None

    (
        side,
        entry_price,
        stop_loss,
        take_profit,
        quantity,
        opened_at,
    ) = row

    position = Position(
        side=side,
        entry_price=Decimal(entry_price),
        stop_loss=Decimal(stop_loss),
        take_profit=Decimal(take_profit),
        opened_at=opened_at,
        quantity=quantity,
    )

    logger.info(
        "Strategy position loaded: "
        "instrument=%s side=%s quantity=%d "
        "entry=%s SL=%s TP=%s",
        instrument_uid,
        position.side,
        position.quantity,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
    )

    return position


def delete_position(
    settings: Settings,
    instrument_uid: str,
) -> None:
    """
    Удаляет виртуальную позицию конкретного инструмента.
    """

    logger.info(
        "Deleting strategy position: instrument=%s",
        instrument_uid,
    )

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
                DELETE FROM strategy_positions
                WHERE instrument_uid = %s
                """,
                (instrument_uid,),
            )

    logger.info(
        "Strategy position deleted: instrument=%s",
        instrument_uid,
    )


def save_trade(
    settings: Settings,
    instrument_uid: str,
    position: Position,
    exit_price: Decimal,
    close_reason: str,
) -> None:
    """
    Сохраняет завершённую виртуальную сделку.
    """

    closed_at = datetime.now(timezone.utc)

    # PnL на одну единицу инструмента.
    # Количество хранится отдельно в quantity.
    pnl_per_unit = exit_price - position.entry_price

    # Общий PnL с учётом количества.
    pnl = pnl_per_unit * Decimal(position.quantity)

    logger.info(
        "Saving strategy trade: "
        "instrument=%s entry=%s exit=%s "
        "quantity=%d reason=%s pnl=%s",
        instrument_uid,
        position.entry_price,
        exit_price,
        position.quantity,
        close_reason,
        pnl,
    )

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
                INSERT INTO strategy_trades (
                    instrument_uid,
                    side,
                    entry_price,
                    exit_price,
                    quantity,
                    stop_loss,
                    take_profit,
                    close_reason,
                    opened_at,
                    closed_at,
                    pnl
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    instrument_uid,
                    position.side,
                    position.entry_price,
                    exit_price,
                    position.quantity,
                    position.stop_loss,
                    position.take_profit,
                    close_reason,
                    position.opened_at,
                    closed_at,
                    pnl,
                ),
            )

    logger.info(
        "Strategy trade saved: instrument=%s pnl=%s",
        instrument_uid,
        pnl,
    )