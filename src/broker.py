import logging
import time
import uuid
from decimal import Decimal, ROUND_DOWN

from config import Settings
from t_tech import invest
from t_tech.invest.schemas import (
    OrderDirection,
    OrderType,
    PriceType,
    TimeInForceType,
    Quotation,
)

logger = logging.getLogger(__name__)


LIVE_ORDER_MAX_ATTEMPTS = 3
LIVE_ORDER_RETRY_DELAY_SECONDS = 1.0
ORDER_BOOK_DEPTH = 5


class Broker:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_live(self) -> bool:
        return self.settings.trading_mode == "LIVE"

    @staticmethod
    def calculate_lots(
        price: Decimal,
        lot: int,
        max_position_rub: Decimal,
    ) -> int:
        """Calculate maximum number of lots within position limit."""

        if price <= 0:
            return 0

        if lot <= 0:
            return 0

        lot_cost = price * Decimal(lot)

        #return int(max_position_rub / lot_cost)
        return int(Decimal(str(max_position_rub)) / lot_cost)

    @staticmethod
    def normalize_price(
        price: Decimal,
        min_price_increment: Decimal,
    ) -> Decimal:
        """Normalize price to instrument price increment."""

        if min_price_increment <= 0:
            return price

        steps = (price / min_price_increment).quantize(
            Decimal("1"),
            rounding=ROUND_DOWN,
        )

        return steps * min_price_increment

    @staticmethod
    def decimal_to_quotation(value: Decimal) -> Quotation:
        """Convert Decimal price to T-Invest Quotation."""

        units = int(value)
        nano = int(
            (value - Decimal(units)) * Decimal("1000000000")
        )

        return Quotation(
            units=units,
            nano=nano,
        )

    @staticmethod
    def quotation_to_decimal(value) -> Decimal:
        """Convert T-Invest quotation/money value to Decimal."""

        return (
            Decimal(value.units)
            + Decimal(value.nano) / Decimal("1000000000")
        )

    def get_best_price(
        self,
        client,
        instrument_uid: str,
        direction: str,
    ) -> Decimal | None:
        """
        Возвращает лучшую цену из стакана для сделки.

        BUY  -> лучший ask (цена продавца).
        SELL -> лучший bid (цена покупателя).

        Возвращает None, если нужная сторона стакана пуста.
        """

        order_book = client.market_data.get_order_book(
            instrument_id=instrument_uid,
            depth=ORDER_BOOK_DEPTH,
        )

        if direction == "BUY":
            levels = order_book.asks

        elif direction == "SELL":
            levels = order_book.bids

        else:
            raise ValueError(
                f"Неизвестное направление: {direction}"
            )

        if not levels:
            return None

        return self.quotation_to_decimal(
            levels[0].price
        )

    def resolve_order_price(
        self,
        instrument_uid: str,
        fallback_price: Decimal,
        direction: str,
        min_price_increment: Decimal,
    ) -> Decimal:
        """
        Определяет цену заявки по стакану.

        Для BUY берётся лучший ask, для SELL — лучший bid.
        Если стакан пуст — используется fallback_price
        (цена последней сделки), нормализованная по шагу.

        Для BUY дополнительно добавляется один шаг цены,
        чтобы заявка перекрывала спред и не «зависала»
        в пустом стакане низколиквидных бумаг.
        """

        ask_or_bid = None

        try:
            with invest.Client(
                self.settings.tinvest_token,
                app_name=self.settings.app_name,
            ) as client:
                ask_or_bid = self.get_best_price(
                    client,
                    instrument_uid,
                    direction,
                )

        except Exception:
            logger.exception(
                "Failed to get order book: uid=%s direction=%s",
                instrument_uid,
                direction,
            )

        if ask_or_bid is not None and ask_or_bid > 0:
            price = ask_or_bid
        else:
            logger.warning(
                "Order book is empty: uid=%s direction=%s, "
                "falling back to last price %s",
                instrument_uid,
                direction,
                fallback_price,
            )
            price = fallback_price

        price = self.normalize_price(
            price,
            min_price_increment,
        )

        if direction == "BUY" and min_price_increment > 0:
            price = price + min_price_increment

        return price

    def open_position(
        self,
        instrument,
        price: Decimal,
    ) -> tuple[bool, str, int]:
        """
        Open a long position.

        Returns:
            (executed, reason, quantity_lots)
        """

        if self.settings.trading_mode == "DISABLED":
            return False, "TRADING_DISABLED", 0

        if not instrument.api_trade_available_flag:
            return False, "API_TRADE_NOT_AVAILABLE", 0

        if not instrument.buy_available_flag:
            return False, "BUY_NOT_AVAILABLE", 0

        lot = int(instrument.lot)

        min_price_increment = self.quotation_to_decimal(
            instrument.min_price_increment
        )

        quantity_lots = self.calculate_lots(
            price=price,
            lot=lot,
            max_position_rub=self.settings.max_position_rub,
        )

        if quantity_lots <= 0:
            return False, "MAX_POSITION_TOO_SMALL", 0

        normalized_price = self.normalize_price(
            price,
            min_price_increment,
        )

        logger.info(
            "Open position: ticker=%s uid=%s price=%s "
            "normalized_price=%s lot=%d quantity_lots=%d",
            instrument.ticker,
            instrument.uid,
            price,
            normalized_price,
            lot,
            quantity_lots,
        )

        if self.settings.trading_mode == "PAPER":
            logger.info(
                "PAPER BUY: ticker=%s uid=%s lots=%d price=%s",
                instrument.ticker,
                instrument.uid,
                quantity_lots,
                normalized_price,
            )

            return (
                True,
                f"PAPER BUY {quantity_lots} лот(ов) по цене {normalized_price}",
                quantity_lots,
            )

        if self.settings.trading_mode == "LIVE":
            live_price = self.resolve_order_price(
                instrument_uid=instrument.uid,
                fallback_price=normalized_price,
                direction="BUY",
                min_price_increment=min_price_increment,
            )

            return self._live_buy(
                instrument=instrument,
                quantity_lots=quantity_lots,
                price=live_price,
            )

        return False, "UNKNOWN_TRADING_MODE", 0

    def close_position(
        self,
        instrument,
        quantity_lots: int,
        price: Decimal,
    ) -> tuple[bool, str, int]:
        """
        Close a long position.

        quantity_lots is the actual broker position size in lots.

        Returns:
            (executed, reason, quantity_lots)
        """

        if self.settings.trading_mode == "DISABLED":
            return False, "TRADING_DISABLED", 0

        if not instrument.api_trade_available_flag:
            return False, "API_TRADE_NOT_AVAILABLE", 0

        if not instrument.sell_available_flag:
            return False, "SELL_NOT_AVAILABLE", 0

        if quantity_lots <= 0:
            return False, "INVALID_QUANTITY", 0

        min_price_increment = self.quotation_to_decimal(
            instrument.min_price_increment
        )

        normalized_price = self.normalize_price(
            price,
            min_price_increment,
        )

        logger.info(
            "Close position: ticker=%s uid=%s lots=%d "
            "price=%s normalized_price=%s",
            instrument.ticker,
            instrument.uid,
            quantity_lots,
            price,
            normalized_price,
        )

        if self.settings.trading_mode == "PAPER":
            logger.info(
                "PAPER SELL: ticker=%s uid=%s lots=%d price=%s",
                instrument.ticker,
                instrument.uid,
                quantity_lots,
                normalized_price,
            )

            return (
                True,
                f"PAPER SELL {quantity_lots} лот(ов) по цене {normalized_price}",
                quantity_lots,
            )

        if self.settings.trading_mode == "LIVE":
            live_price = self.resolve_order_price(
                instrument_uid=instrument.uid,
                fallback_price=normalized_price,
                direction="SELL",
                min_price_increment=min_price_increment,
            )

            return self._live_sell(
                instrument=instrument,
                quantity_lots=quantity_lots,
                price=live_price,
            )

        return False, "UNKNOWN_TRADING_MODE", 0

    def _live_buy(
        self,
        instrument,
        quantity_lots: int,
        price: Decimal,
    ) -> tuple[bool, str, int]:
        """Send and verify LIVE BUY order with retries."""

        last_reason = "LIVE BUY NOT EXECUTED"

        for attempt in range(1, LIVE_ORDER_MAX_ATTEMPTS + 1):
            order_id = str(uuid.uuid4())

            logger.warning(
                "LIVE BUY: ticker=%s uid=%s lots=%d price=%s "
                "order_id=%s attempt=%d/%d",
                instrument.ticker,
                instrument.uid,
                quantity_lots,
                price,
                order_id,
                attempt,
                LIVE_ORDER_MAX_ATTEMPTS,
            )

            try:
                with invest.Client(
                    self.settings.tinvest_token,
                    app_name=self.settings.app_name,
                ) as client:

                    response = client.orders.post_order(
                        quantity=quantity_lots,
                        price=self.decimal_to_quotation(price),
                        direction=OrderDirection.ORDER_DIRECTION_BUY,
                        account_id=self.settings.tinvest_account_id,
                        order_type=OrderType.ORDER_TYPE_LIMIT,
                        order_id=order_id,
                        instrument_id=instrument.uid,
                        time_in_force=TimeInForceType.TIME_IN_FORCE_FILL_AND_KILL,
                        price_type=PriceType.PRICE_TYPE_CURRENCY,
                    )

                    logger.info(
                        "LIVE BUY response: order_id=%s "
                        "status=%s requested=%d executed=%d",
                        response.order_id,
                        response.execution_report_status,
                        response.lots_requested,
                        response.lots_executed,
                    )

                    executed_quantity = int(response.lots_executed)

                    if executed_quantity > 0:
                        return (
                            True,
                            (
                                f"LIVE BUY executed: "
                                f"{executed_quantity} лот(ов), "
                                f"order_id={response.order_id}"
                            ),
                            executed_quantity,
                        )

                    last_reason = (
                        "LIVE BUY NOT EXECUTED: "
                        f"status={response.execution_report_status} "
                        f"message={response.message}"
                    )

            except Exception as exc:
                logger.exception(
                    "LIVE BUY failed: attempt=%d/%d",
                    attempt,
                    LIVE_ORDER_MAX_ATTEMPTS,
                )

                last_reason = f"LIVE BUY ERROR: {exc}"

            # Перед следующей попыткой обновляем цену по стакану.
            if attempt < LIVE_ORDER_MAX_ATTEMPTS:
                min_price_increment = self.quotation_to_decimal(
                    instrument.min_price_increment
                )

                price = self.resolve_order_price(
                    instrument_uid=instrument.uid,
                    fallback_price=price,
                    direction="BUY",
                    min_price_increment=min_price_increment,
                )

                time.sleep(LIVE_ORDER_RETRY_DELAY_SECONDS)

        return False, last_reason, 0

    def _live_sell(
        self,
        instrument,
        quantity_lots: int,
        price: Decimal,
    ) -> tuple[bool, str, int]:
        """Send and verify LIVE SELL order with retries."""

        last_reason = "LIVE SELL NOT EXECUTED"

        for attempt in range(1, LIVE_ORDER_MAX_ATTEMPTS + 1):
            order_id = str(uuid.uuid4())

            logger.warning(
                "LIVE SELL: ticker=%s uid=%s lots=%d price=%s "
                "order_id=%s attempt=%d/%d",
                instrument.ticker,
                instrument.uid,
                quantity_lots,
                price,
                order_id,
                attempt,
                LIVE_ORDER_MAX_ATTEMPTS,
            )

            try:
                with invest.Client(
                    self.settings.tinvest_token,
                    app_name=self.settings.app_name,
                ) as client:

                    response = client.orders.post_order(
                        quantity=quantity_lots,
                        price=self.decimal_to_quotation(price),
                        direction=OrderDirection.ORDER_DIRECTION_SELL,
                        account_id=self.settings.tinvest_account_id,
                        order_type=OrderType.ORDER_TYPE_LIMIT,
                        order_id=order_id,
                        instrument_id=instrument.uid,
                        time_in_force=TimeInForceType.TIME_IN_FORCE_FILL_AND_KILL,
                        price_type=PriceType.PRICE_TYPE_CURRENCY,
                    )

                    logger.info(
                        "LIVE SELL response: order_id=%s "
                        "status=%s requested=%d executed=%d",
                        response.order_id,
                        response.execution_report_status,
                        response.lots_requested,
                        response.lots_executed,
                    )

                    executed_quantity = int(response.lots_executed)

                    if executed_quantity > 0:
                        return (
                            True,
                            (
                                f"LIVE SELL executed: "
                                f"{executed_quantity} лот(ов), "
                                f"order_id={response.order_id}"
                            ),
                            executed_quantity,
                        )

                    last_reason = (
                        "LIVE SELL NOT EXECUTED: "
                        f"status={response.execution_report_status} "
                        f"message={response.message}"
                    )

            except Exception as exc:
                logger.exception(
                    "LIVE SELL failed: attempt=%d/%d",
                    attempt,
                    LIVE_ORDER_MAX_ATTEMPTS,
                )

                last_reason = f"LIVE SELL ERROR: {exc}"

            if attempt < LIVE_ORDER_MAX_ATTEMPTS:
                min_price_increment = self.quotation_to_decimal(
                    instrument.min_price_increment
                )

                price = self.resolve_order_price(
                    instrument_uid=instrument.uid,
                    fallback_price=price,
                    direction="SELL",
                    min_price_increment=min_price_increment,
                )

                time.sleep(LIVE_ORDER_RETRY_DELAY_SECONDS)

        return False, last_reason, 0