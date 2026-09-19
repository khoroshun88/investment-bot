import logging
from decimal import Decimal

import psycopg

from config import Settings
from strategy import Position
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def save_position(
    settings: Settings,
    instrument_uid: str,
    position: Position,
) -> None:
    """
    Сохраняет текущую виртуальную позицию Strategy в PostgreSQL.
    """

    logger.info(
        "Saving strategy position: instrument=%s side=%s "
        "entry=%s SL=%s TP=%s",
        instrument_uid,
        position.side,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
        position.opened_at
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
                    id,
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
                    1,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW()
                )
                ON CONFLICT (id)
                DO UPDATE SET
                    instrument_uid = EXCLUDED.instrument_uid,
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
        "Saving strategy position: instrument=%s side=%s "
        "quantity=%d entry=%s SL=%s TP=%s",
        instrument_uid,
        position.side,
        position.quantity,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
        position.opened_at,
    )


def load_position(
    settings: Settings,
    instrument_uid: str,
) -> Position | None:
    """
    Загружает виртуальную позицию Strategy из PostgreSQL.

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
                WHERE id = 1
                  AND instrument_uid = %s
                """,
                (instrument_uid,),
            )

            row = cursor.fetchone()

    if row is None:
        logger.info("No saved strategy position")
        return None

    side, entry_price, stop_loss, take_profit, quantity, opened_at = row

    position = Position(
        side=side,
        entry_price=Decimal(entry_price),
        stop_loss=Decimal(stop_loss),
        take_profit=Decimal(take_profit),
        opened_at=opened_at,
        quantity=quantity,
    )

    logger.info(
        "Strategy position loaded: side=%s entry=%s SL=%s TP=%s",
        position.side,
        position.quantity,
        position.entry_price,
        position.stop_loss,
        position.take_profit,
    )

    return position


def delete_position(settings: Settings) -> None:
    """
    Удаляет текущую виртуальную позицию.

    Используется после CLOSE.
    """

    logger.info("Deleting strategy position")

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
                WHERE id = 1
                """
            )

    logger.info("Strategy position deleted")

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

    pnl = exit_price - position.entry_price

    logger.info(
        "Saving strategy trade: instrument=%s "
        "entry=%s exit=%s reason=%s pnl=%s",
        instrument_uid,
        position.entry_price,
        exit_price,
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
                    0,
                    position.stop_loss,
                    position.take_profit,
                    close_reason,
                    position.opened_at,
                    closed_at,
                    pnl,
                ),
            )

    logger.info("Strategy trade saved")