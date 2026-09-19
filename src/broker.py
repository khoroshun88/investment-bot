import logging
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

        return int(max_position_rub / lot_cost)

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
            return self._live_buy(
                instrument=instrument,
                quantity_lots=quantity_lots,
                price=normalized_price,
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
            return self._live_sell(
                instrument=instrument,
                quantity_lots=quantity_lots,
                price=normalized_price,
            )

        return False, "UNKNOWN_TRADING_MODE", 0

    def _live_buy(
        self,
        instrument,
        quantity_lots: int,
        price: Decimal,
    ) -> tuple[bool, str, int]:
        """Send and verify LIVE BUY order."""

        order_id = str(uuid.uuid4())

        logger.warning(
            "LIVE BUY: ticker=%s uid=%s lots=%d price=%s order_id=%s",
            instrument.ticker,
            instrument.uid,
            quantity_lots,
            price,
            order_id,
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

                if executed_quantity <= 0:
                    return (
                        False,
                        (
                            "LIVE BUY NOT EXECUTED: "
                            f"status={response.execution_report_status} "
                            f"message={response.message}"
                        ),
                        0,
                    )

                return (
                    True,
                    (
                        f"LIVE BUY executed: "
                        f"{executed_quantity} лот(ов), "
                        f"order_id={response.order_id}"
                    ),
                    executed_quantity,
                )

        except Exception as exc:
            logger.exception("LIVE BUY failed")

            return (
                False,
                f"LIVE BUY ERROR: {exc}",
                0,
            )

    def _live_sell(
        self,
        instrument,
        quantity_lots: int,
        price: Decimal,
    ) -> tuple[bool, str, int]:
        """Send and verify LIVE SELL order."""

        order_id = str(uuid.uuid4())

        logger.warning(
            "LIVE SELL: ticker=%s uid=%s lots=%d price=%s order_id=%s",
            instrument.ticker,
            instrument.uid,
            quantity_lots,
            price,
            order_id,
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

                if executed_quantity <= 0:
                    return (
                        False,
                        (
                            "LIVE SELL NOT EXECUTED: "
                            f"status={response.execution_report_status} "
                            f"message={response.message}"
                        ),
                        0,
                    )

                return (
                    True,
                    (
                        f"LIVE SELL executed: "
                        f"{executed_quantity} лот(ов), "
                        f"order_id={response.order_id}"
                    ),
                    executed_quantity,
                )

        except Exception as exc:
            logger.exception("LIVE SELL failed")

            return (
                False,
                f"LIVE SELL ERROR: {exc}",
                0,
            )