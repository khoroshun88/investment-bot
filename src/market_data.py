import copy
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import grpc
from t_tech import invest

from broker import Broker
from config import Settings
from strategy import Strategy
from strategy_repository import (
    delete_position,
    load_position,
    save_position,
    save_trade,
)
from tinvest_client import (
    get_instrument_by_ticker,
    money_value_to_decimal,
)


logger = logging.getLogger(__name__)


def calculate_rsi(
    closes: list[Decimal],
    period: int = 14,
) -> Decimal | None:
    """
    Calculate RSI using Wilder's smoothing method.
    """

    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))

    average_gain = (
        sum(gains[:period]) / Decimal(period)
    )

    average_loss = (
        sum(losses[:period]) / Decimal(period)
    )

    for i in range(period, len(gains)):
        average_gain = (
            (
                average_gain * Decimal(period - 1)
            )
            + gains[i]
        ) / Decimal(period)

        average_loss = (
            (
                average_loss * Decimal(period - 1)
            )
            + losses[i]
        ) / Decimal(period)

    if average_loss == 0:
        return Decimal("100")

    if average_gain == 0:
        return Decimal("0")

    rs = average_gain / average_loss

    return Decimal("100") - (
        Decimal("100")
        / (Decimal("1") + rs)
    )


def get_rsi_signal(
    previous_rsi: Decimal | None,
    current_rsi: Decimal | None,
    buy_level: Decimal = Decimal("30"),
    sell_level: Decimal = Decimal("70"),
) -> tuple[str, str]:
    """
    Определяет сигнал только при пересечении уровней RSI.

    BUY:
        RSI был >= 30 и стал < 30.

    SELL:
        RSI был <= 70 и стал > 70.

    HOLD:
        Во всех остальных случаях.

    Возвращает:
        (signal, reason)
    """

    if current_rsi is None:
        return "HOLD", "RSI недоступен"

    if previous_rsi is None:
        return (
            "HOLD",
            "Первый расчёт RSI, "
            "предыдущее значение отсутствует",
        )

    # BUY: пересечение уровня сверху вниз.
    if (
        previous_rsi >= buy_level
        and current_rsi < buy_level
    ):
        return (
            "BUY",
            f"RSI пересёк уровень BUY {buy_level} "
            f"сверху вниз: "
            f"{previous_rsi:.2f} -> "
            f"{current_rsi:.2f}",
        )

    # SELL: пересечение уровня снизу вверх.
    if (
        previous_rsi <= sell_level
        and current_rsi > sell_level
    ):
        return (
            "SELL",
            f"RSI пересёк уровень SELL {sell_level} "
            f"снизу вверх: "
            f"{previous_rsi:.2f} -> "
            f"{current_rsi:.2f}",
        )

    if current_rsi < buy_level:
        return (
            "HOLD",
            f"RSI ниже BUY уровня {buy_level}, "
            f"но нового пересечения нет",
        )

    if current_rsi > sell_level:
        return (
            "HOLD",
            f"RSI выше SELL уровня {sell_level}, "
            f"но нового пересечения нет",
        )

    return (
        "HOLD",
        f"RSI находится в нейтральной зоне "
        f"{buy_level}..{sell_level}",
    )


def get_market_data(
    settings,
    instrument_uid: str,
    candles_count: int = 200,
):
    """
    Получает последние минутные свечи конкретного инструмента
    и текущую цену.

    Никаких торговых заявок здесь не отправляется.
    """

    now = datetime.now(timezone.utc)

    from_time = now - timedelta(
        minutes=candles_count + 10
    )

    try:
        with invest.Client(
            settings.tinvest_token,
            app_name=settings.app_name,
        ) as client:

            response = client.market_data.get_candles(
                instrument_id=instrument_uid,
                from_=from_time,
                to=now,
                interval=(
                    invest.CandleInterval
                    .CANDLE_INTERVAL_1_MIN
                ),
                limit=candles_count,
            )

            last_prices = (
                client.market_data.get_last_prices(
                    instrument_id=[instrument_uid],
                )
            )

    except grpc.RpcError as error:
        logger.error(
            "T-Invest market data error: "
            "status=%s, details=%s",
            error.code().name,
            error.details(),
        )

        raise RuntimeError(
            "Ошибка T-Invest API при получении "
            "рыночных данных: "
            f"{error.code().name}"
        ) from error

    candles = response.candles

    current_price = None

    if last_prices.last_prices:
        current_price = money_value_to_decimal(
            last_prices.last_prices[0].price
        )

    result = []

    for candle in candles:
        result.append(
            {
                "time": candle.time,
                "open": money_value_to_decimal(
                    candle.open
                ),
                "high": money_value_to_decimal(
                    candle.high
                ),
                "low": money_value_to_decimal(
                    candle.low
                ),
                "close": money_value_to_decimal(
                    candle.close
                ),
                "volume": candle.volume,
                "is_complete": candle.is_complete,
            }
        )

    return current_price, result


def monitor_instrument(
    settings: Settings,
    ticker: str,
    budget_rub: float,
    candles_count: int = 200,
):
    """
    Постоянный мониторинг одного инструмента.

    Каждый инструмент имеет:
        - собственный Strategy;
        - собственную PostgreSQL position;
        - собственный бюджет;
        - собственный RSI state.

    Бюджет инструмента передаётся в Broker через отдельную
    копию Settings, чтобы разные потоки не изменяли общий
    settings.max_position_rub.
    """

    # -------------------------------------------------------------
    # Получаем инструмент.
    # -------------------------------------------------------------

    instrument = get_instrument_by_ticker(
        settings,
        ticker,
    )

    instrument_uid = instrument.uid

    ticker = instrument.ticker

    # -------------------------------------------------------------
    # Каждый инструмент получает собственный экземпляр settings
    # для Broker.
    #
    # Это важно: несколько потоков не должны одновременно менять
    # общий settings.max_position_rub.
    # -------------------------------------------------------------

    broker_settings = copy.copy(settings)

    broker_settings.max_position_rub = budget_rub

    broker = Broker(broker_settings)

    # -------------------------------------------------------------
    # Логирование.
    # -------------------------------------------------------------

    logger.info(
        "Monitoring instrument: %s (%s), uid=%s, "
        "budget=%s RUB",
        ticker,
        instrument.class_code,
        instrument_uid,
        budget_rub,
    )

    logger.info(
        "Starting %s market monitoring: candles=%d",
        ticker,
        candles_count,
    )

    print()
    print("=" * 100)
    print(f"{ticker} MONITORING STARTED")
    print(f"Instrument UID: {instrument_uid}")
    print(f"Trading mode: {settings.trading_mode}")
    print(f"Position budget: {budget_rub} RUB")
    print("=" * 100)

    # -------------------------------------------------------------
    # RSI settings.
    # -------------------------------------------------------------

    rsi_period = 14
    rsi_buy_level = Decimal("30")
    rsi_sell_level = Decimal("70")

    previous_rsi = None
    last_processed_candle_time = None

    # -------------------------------------------------------------
    # У каждого инструмента собственная Strategy.
    # -------------------------------------------------------------

    strategy = Strategy()

    # -------------------------------------------------------------
    # Восстанавливаем позицию именно этого инструмента.
    # -------------------------------------------------------------

    saved_position = load_position(
        settings,
        instrument_uid,
    )

    strategy.restore_position(
        saved_position
    )

    if saved_position is not None:
        logger.info(
            "Restored strategy position: "
            "instrument=%s side=%s entry=%s "
            "quantity=%d SL=%s TP=%s",
            instrument_uid,
            saved_position.side,
            saved_position.entry_price,
            saved_position.quantity,
            saved_position.stop_loss,
            saved_position.take_profit,
        )

    try:
        while True:
            try:
                current_price, candles = get_market_data(
                    settings,
                    instrument_uid,
                    candles_count,
                )

                # -------------------------------------------------
                # Только завершённые свечи.
                # -------------------------------------------------

                completed_candles = [
                    candle
                    for candle in candles
                    if candle["is_complete"]
                ]

                new_candle = False
                latest_completed_candle = None
                latest_candle_time = None

                if completed_candles:
                    latest_completed_candle = (
                        completed_candles[-1]
                    )

                    latest_candle_time = (
                        latest_completed_candle["time"]
                    )

                    new_candle = (
                        latest_candle_time
                        != last_processed_candle_time
                    )

                # -------------------------------------------------
                # Значения текущего цикла.
                # -------------------------------------------------

                rsi = None

                rsi_before_update = previous_rsi

                signal = "HOLD"

                signal_reason = (
                    "Waiting for new completed candle"
                )

                action = "HOLD"

                action_reason = (
                    "No new RSI signal"
                )

                execution_reason = None
                executed = False
                executed_quantity = 0

                # -------------------------------------------------
                # RSI обрабатывается только на новой завершённой
                # минутной свече.
                # -------------------------------------------------

                if new_candle:
                    closes = [
                        candle["close"]
                        for candle in completed_candles
                    ]

                    rsi = calculate_rsi(
                        closes,
                        period=rsi_period,
                    )

                    rsi_before_update = previous_rsi

                    signal, signal_reason = (
                        get_rsi_signal(
                            previous_rsi,
                            rsi,
                            buy_level=rsi_buy_level,
                            sell_level=rsi_sell_level,
                        )
                    )

                    action, action_reason = (
                        strategy.work(
                            signal=signal,
                            price=current_price,
                        )
                    )

                    previous_rsi = rsi

                    last_processed_candle_time = (
                        latest_candle_time
                    )

                    logger.info(
                        "[%s] New completed candle: "
                        "time=%s RSI=%s signal=%s "
                        "reason=%s",
                        ticker,
                        latest_candle_time,
                        (
                            f"{rsi:.2f}"
                            if rsi is not None
                            else "None"
                        ),
                        signal,
                        signal_reason,
                    )

                # -------------------------------------------------
                # SL/TP проверяем каждые 10 секунд.
                # -------------------------------------------------

                elif (
                    strategy.position is not None
                    and current_price is not None
                ):
                    action, action_reason = (
                        strategy.work(
                            signal="HOLD",
                            price=current_price,
                        )
                    )

                # -------------------------------------------------
                # OPEN.
                # -------------------------------------------------

                if (
                    action == "OPEN"
                    and current_price is not None
                ):
                    logger.info(
                        "[%s] OPEN requested: "
                        "price=%s budget=%s RUB",
                        ticker,
                        current_price,
                        budget_rub,
                    )

                    (
                        executed,
                        execution_reason,
                        executed_quantity,
                    ) = broker.open_position(
                        instrument=instrument,
                        price=current_price,
                    )

                    logger.info(
                        "[%s] Execution OPEN: "
                        "executed=%s quantity_lots=%d "
                        "reason=%s",
                        ticker,
                        executed,
                        executed_quantity,
                        execution_reason,
                    )

                    if (
                        executed
                        and strategy.position is not None
                    ):
                        strategy.position.quantity = (
                            executed_quantity
                        )

                        save_position(
                            settings,
                            instrument_uid,
                            strategy.position,
                        )

                # -------------------------------------------------
                # CLOSE.
                # -------------------------------------------------

                elif (
                    action == "CLOSE"
                    and current_price is not None
                ):
                    if (
                        strategy.last_closed_position
                        is None
                    ):
                        logger.error(
                            "[%s] CLOSE action without "
                            "last_closed_position",
                            ticker,
                        )

                    else:
                        quantity_lots = (
                            strategy.last_closed_position.quantity
                        )

                        # Защита от некорректной виртуальной
                        # позиции.
                        if quantity_lots <= 0:
                            logger.error(
                                "[%s] Cannot close position: "
                                "quantity=%d",
                                ticker,
                                quantity_lots,
                            )

                            executed = False

                            execution_reason = (
                                "Некорректное количество "
                                "позиции"
                            )

                        else:
                            (
                                executed,
                                execution_reason,
                                executed_quantity,
                            ) = broker.close_position(
                                instrument=instrument,
                                quantity_lots=quantity_lots,
                                price=current_price,
                            )

                        logger.info(
                            "[%s] Execution CLOSE: "
                            "executed=%s quantity_lots=%d "
                            "reason=%s",
                            ticker,
                            executed,
                            executed_quantity,
                            execution_reason,
                        )

                        if executed:
                            save_trade(
                                settings,
                                instrument_uid,
                                strategy.last_closed_position,
                                current_price,
                                action_reason,
                                lot=int(instrument.lot),
                            )

                            delete_position(
                                settings,
                                instrument_uid,
                            )

                            strategy.last_closed_position = (
                                None
                            )

                # -------------------------------------------------
                # Вывод текущего состояния.
                # -------------------------------------------------

                print()

                print(
                    f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}] "
                    f"{ticker}"
                )

                print(
                    f"Budget: {budget_rub:.2f} RUB"
                )

                if current_price is not None:
                    print(
                        f"Current price: "
                        f"{current_price:.2f} RUB"
                    )
                else:
                    print(
                        "Current price: unavailable"
                    )

                print(
                    f"Candles: {len(candles)}"
                )

                # -------------------------------------------------
                # RSI.
                # -------------------------------------------------

                if new_candle:
                    print(
                        "New completed candle: "
                        f"{latest_candle_time}"
                    )

                    if rsi is not None:
                        if (
                            rsi_before_update
                            is not None
                        ):
                            rsi_delta = (
                                rsi
                                - rsi_before_update
                            )

                            print(
                                f"RSI(14): "
                                f"{rsi_before_update:.2f} -> "
                                f"{rsi:.2f} "
                                f"(Δ {rsi_delta:+.2f})"
                            )

                        else:
                            print(
                                f"RSI(14): "
                                f"previous=None -> "
                                f"current={rsi:.2f}"
                            )

                    else:
                        print(
                            "RSI(14): unavailable"
                        )

                    print(
                        f"Signal: {signal}"
                    )

                    print(
                        f"Reason: {signal_reason}"
                    )

                else:
                    print(
                        "RSI: waiting for new "
                        "completed candle"
                    )

                    if previous_rsi is not None:
                        print(
                            f"RSI(14): "
                            f"{previous_rsi:.2f} "
                            f"(unchanged)"
                        )

                    print(
                        "Signal: HOLD "
                        "(RSI signal not processed)"
                    )

                # -------------------------------------------------
                # Position.
                # -------------------------------------------------

                position = strategy.position

                if position is None:
                    position_text = "NONE"

                else:
                    position_text = (
                        f"{position.side} "
                        f"entry={position.entry_price} "
                        f"quantity={position.quantity} "
                        f"SL={position.stop_loss} "
                        f"TP={position.take_profit}"
                    )

                print(
                    f"Strategy position: "
                    f"{position_text}"
                )

                print(
                    f"Strategy action: "
                    f"{action}"
                )

                print(
                    f"Action reason: "
                    f"{action_reason}"
                )

                if execution_reason is not None:
                    print(
                        f"Execution: "
                        f"{execution_reason}"
                    )

                # -------------------------------------------------
                # Последняя свеча.
                # -------------------------------------------------

                if candles:
                    last_candle = candles[-1]

                    print(
                        f"Last candle: "
                        f"{last_candle['time']} | "
                        f"O={last_candle['open']:.2f} "
                        f"H={last_candle['high']:.2f} "
                        f"L={last_candle['low']:.2f} "
                        f"C={last_candle['close']:.2f} "
                        f"V={last_candle['volume']} "
                        f"complete="
                        f"{last_candle['is_complete']}"
                    )

                logger.info(
                    "[%s] Next market data request "
                    "in 10 seconds",
                    ticker,
                )

            except Exception:
                logger.exception(
                    "Error while getting %s market data",
                    ticker,
                )

            time.sleep(10)

    except KeyboardInterrupt:
        logger.info(
            "%s market monitoring stopped",
            ticker,
        )

        print()
        print("=" * 100)
        print(f"{ticker} MONITORING STOPPED")
        print("=" * 100)