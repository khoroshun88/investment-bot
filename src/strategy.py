from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class Position:
    side: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    opened_at: datetime
    quantity: int = 0

    def reprice(
        self,
        new_entry_price: Decimal,
        stop_loss_percent: Decimal = Decimal("0.02"),
        take_profit_percent: Decimal = Decimal("0.04"),
    ) -> None:
        """
        Пересчитывает точку входа, SL и TP по фактической
        цене исполнения заявки.

        Используется после успешного LIVE/PAPER исполнения,
        когда реальная цена может отличаться от last price.
        """

        self.entry_price = new_entry_price

        self.stop_loss = new_entry_price * (
            Decimal("1") - stop_loss_percent
        )

        self.take_profit = new_entry_price * (
            Decimal("1") + take_profit_percent
        )


class Strategy:
    """
    Торговая стратегия с управлением LONG-позицией.

    BUY + NONE -> открыть LONG
    BUY + LONG -> ничего не делать

    SELL + LONG -> закрыть LONG
    SELL + NONE -> ничего не делать

    LONG:
        price <= stop_loss   -> закрыть по STOP_LOSS
        price >= take_profit -> закрыть по TAKE_PROFIT

    HOLD -> ничего не делать
    """

    def __init__(
        self,
        stop_loss_percent: Decimal = Decimal("0.02"),
        take_profit_percent: Decimal = Decimal("0.04"),
    ) -> None:
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent

        self.position: Position | None = None
        self.last_closed_position: Position | None = None

    def restore_position(
        self,
        position: Position | None,
    ) -> None:
        """
        Восстанавливает позицию из PostgreSQL.
        """
        self.position = position
        self.last_closed_position = None

    def work(
        self,
        signal: str,
        price: Decimal,
        quantity: int | None = None,
    ) -> tuple[str, str]:
        """
        Обрабатывает торговый сигнал и проверяет SL/TP.

        Возвращает:

            ("OPEN", "RSI BUY")
            ("CLOSE", "RSI SELL")
            ("CLOSE", "STOP_LOSS")
            ("CLOSE", "TAKE_PROFIT")
            ("HOLD", "...")

        quantity:
            Количество лотов/единиц, которое будет записано
            в новую позицию.

            Если quantity не передан, используется 0.
            Фактическое количество может быть установлено
            после выполнения Broker.open_position().
        """

        # После открытия новой позиции старое значение
        # last_closed_position больше не актуально.
        self.last_closed_position = None

        # ---------------------------------------------------------
        # Если позиция уже открыта — сначала проверяем SL/TP.
        # ---------------------------------------------------------

        if self.position is not None:
            if price <= self.position.stop_loss:
                self.last_closed_position = self.position
                self.position = None

                return "CLOSE", "STOP_LOSS"

            if price >= self.position.take_profit:
                self.last_closed_position = self.position
                self.position = None

                return "CLOSE", "TAKE_PROFIT"

        # ---------------------------------------------------------
        # Обработка RSI BUY.
        # ---------------------------------------------------------

        if signal == "BUY":
            if self.position is None:
                stop_loss = price * (
                    Decimal("1") - self.stop_loss_percent
                )

                take_profit = price * (
                    Decimal("1") + self.take_profit_percent
                )

                self.position = Position(
                    side="LONG",
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    opened_at=datetime.now(timezone.utc),
                    quantity=quantity or 0,
                )

                return "OPEN", "RSI BUY"

            return "HOLD", "LONG уже открыта"

        # ---------------------------------------------------------
        # Обработка RSI SELL.
        # ---------------------------------------------------------

        if signal == "SELL":
            if self.position is not None:
                self.last_closed_position = self.position
                self.position = None

                return "CLOSE", "RSI SELL"

            return "HOLD", "LONG-позиция отсутствует"

        # ---------------------------------------------------------
        # HOLD.
        # ---------------------------------------------------------

        return "HOLD", "RSI HOLD"