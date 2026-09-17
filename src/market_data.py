import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import grpc
from t_tech import invest

from config import Settings
from tinvest_client import money_value_to_decimal
import time
from strategy import Strategy
from strategy_repository import (
    delete_position,
    load_position,
    save_position,
    save_trade,
)

logger = logging.getLogger(__name__)


SBER_UID = "e6123145-9665-43e0-8413-cd61b8aa9b13"

def calculate_rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    """Calculate RSI using Wilder's smoothing method."""

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

    average_gain = sum(gains[:period]) / Decimal(period)
    average_loss = sum(losses[:period]) / Decimal(period)

    for i in range(period, len(gains)):
        average_gain = (
            (average_gain * Decimal(period - 1)) + gains[i]
        ) / Decimal(period)

        average_loss = (
            (average_loss * Decimal(period - 1)) + losses[i]
        ) / Decimal(period)

    if average_loss == 0:
        return Decimal("100")

    if average_gain == 0:
        return Decimal("0")

    rs = average_gain / average_loss

    return Decimal("100") - (
        Decimal("100") / (Decimal("1") + rs)
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
            "Первый расчёт RSI, предыдущее значение отсутствует",
        )

    # Пересечение BUY уровня сверху вниз.
    if previous_rsi >= buy_level and current_rsi < buy_level:
        return (
            "BUY",
            f"RSI пересёк уровень BUY {buy_level} "
            f"сверху вниз: {previous_rsi:.2f} -> {current_rsi:.2f}",
        )

    # Пересечение SELL уровня снизу вверх.
    if previous_rsi <= sell_level and current_rsi > sell_level:
        return (
            "SELL",
            f"RSI пересёк уровень SELL {sell_level} "
            f"снизу вверх: {previous_rsi:.2f} -> {current_rsi:.2f}",
        )

    # RSI ниже BUY уровня, но пересечения сейчас нет.
    if current_rsi < buy_level:
        return (
            "HOLD",
            f"RSI ниже BUY уровня {buy_level}, "
            f"но нового пересечения нет",
        )

    # RSI выше SELL уровня, но пересечения сейчас нет.
    if current_rsi > sell_level:
        return (
            "HOLD",
            f"RSI выше SELL уровня {sell_level}, "
            f"но нового пересечения нет",
        )

    # RSI находится между уровнями.
    return (
        "HOLD",
        f"RSI находится в нейтральной зоне "
        f"{buy_level}..{sell_level}",
    )

def get_sber_market_data(
    settings: Settings,
    candles_count: int = 30,
):
    """
    Получает последние минутные свечи SBER
    и текущую цену.

    Никаких торговых заявок не отправляет.
    """

    now = datetime.now(timezone.utc)

    # Для получения N минутных свечей запрашиваем
    # немного больший интервал времени.
    from_time = now - timedelta(
        minutes=candles_count + 10
    )

    try:
        with invest.Client(
            settings.tinvest_token,
            app_name=settings.app_name,
        ) as client:

            response = client.market_data.get_candles(
                instrument_id=SBER_UID,
                from_=from_time,
                to=now,
                interval=invest.CandleInterval.CANDLE_INTERVAL_1_MIN,
                limit=candles_count,
            )

            last_prices = client.market_data.get_last_prices(
                instrument_id=[SBER_UID],
            )

    except grpc.RpcError as error:
        logger.error(
            "T-Invest market data error: status=%s, details=%s",
            error.code().name,
            error.details(),
        )
        raise RuntimeError(
            f"Ошибка T-Invest API при получении рыночных данных: "
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
                "open": money_value_to_decimal(candle.open),
                "high": money_value_to_decimal(candle.high),
                "low": money_value_to_decimal(candle.low),
                "close": money_value_to_decimal(candle.close),
                "volume": candle.volume,
                "is_complete": candle.is_complete,
            }
        )

    return current_price, result


def print_sber_market_data(
    settings: Settings,
    candles_count: int = 30,
):
    """Получить и вывести рыночные данные SBER."""

    current_price, candles = get_sber_market_data(
        settings,
        candles_count=candles_count,
    )

    print()
    print("=" * 100)
    print("SBER MARKET DATA")
    print("=" * 100)

    if current_price is not None:
        print(f"Current price: {current_price} RUB")
    else:
        print("Current price: unavailable")

    print(f"Candles received: {len(candles)}")
    print()

    print(
        f"{'TIME':<25}"
        f"{'OPEN':>12}"
        f"{'HIGH':>12}"
        f"{'LOW':>12}"
        f"{'CLOSE':>12}"
        f"{'VOLUME':>12}"
        f"{'COMPLETE':>10}"
    )

    print("-" * 100)

    for candle in candles:
        print(
            f"{str(candle['time']):<25}"
            f"{candle['open']:>12.2f}"
            f"{candle['high']:>12.2f}"
            f"{candle['low']:>12.2f}"
            f"{candle['close']:>12.2f}"
            f"{candle['volume']:>12}"
            f"{str(candle['is_complete']):>10}"
        )

    print("=" * 100)
    print()

def monitor_sber(settings: Settings, candles_count: int = 200):
    """
    Постоянный мониторинг SBER.
    Каждую минуту:
    - получает последние минутные свечи;
    - получает текущую цену;
    - рассчитывает RSI(14);
    - определяет сигнал только при пересечении уровней RSI.

    Торговые заявки НЕ отправляются.
    """
    logger.info(
        "Starting SBER market monitoring: candles=%d",
        candles_count,
    )

    print()
    print("=" * 100)
    print("SBER MONITORING STARTED")
    print("Trading is DISABLED")
    print("=" * 100)

    rsi_period = 14
    rsi_buy_level = Decimal("30")
    rsi_sell_level = Decimal("70")

    previous_rsi = None
    strategy = Strategy()
    
    saved_position = load_position(
        settings,
        SBER_UID,
    )
    
    strategy.restore_position(saved_position)
    try:
        while True:
            #started_at = time.monotonic()

            try:
                current_price, candles = get_sber_market_data(
                    settings,
                    candles_count=candles_count,
                )
                closes = [candle["close"] for candle in candles]

                rsi = calculate_rsi(
                    closes,
                    period=rsi_period,
                )

                rsi_before_update = previous_rsi

                signal, signal_reason = get_rsi_signal(
                    previous_rsi,
                    rsi,
                    buy_level=rsi_buy_level,
                    sell_level=rsi_sell_level,
                )

                action, action_reason = strategy.work(
                    signal=signal,
                    price=current_price,
                )

                if action == "OPEN" and strategy.position is not None:
                    save_position(
                        settings,
                        SBER_UID,
                        strategy.position,
                    )
                
                if action == "CLOSE":
                    if strategy.last_closed_position is not None:
                        save_trade(
                            settings,
                            SBER_UID,
                            strategy.last_closed_position,
                            current_price,
                            action_reason,
                        )
                
                    delete_position(settings)

                previous_rsi = rsi

                print()
                print(
                    f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}] "
                    f"SBER"
                )

                if current_price is not None:
                    print(f"Current price: {current_price:.2f} RUB")
                else:
                    print("Current price: unavailable")

                print(f"Candles: {len(candles)}")

                if rsi is not None:
                    if previous_rsi is not None:
                        print(
                            f"RSI(14): {previous_rsi:.2f} -> {rsi:.2f}"
                        )
                    else:
                        print(f"RSI(14): {rsi:.2f}")
                else:
                    print("RSI(14): unavailable")
                
                print(f"Signal: {signal}")
                print(f"Reason: {signal_reason}")

                position = strategy.position

                if position is None:
                    position_text = "NONE"
                else:
                    position_text = (
                        f"{position.side} "
                        f"entry={position.entry_price} "
                        f"SL={position.stop_loss} "
                        f"TP={position.take_profit}"
                    )

                print(f"Strategy action: {action}")
                print(f"Action reason: {action_reason}")
                print(f"Position: {position_text}")

                if action in ("OPEN", "CLOSE"):
                    print(
                        "Trading is DISABLED — "
                        "order was not sent"
                    )

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
                        f"complete={last_candle['is_complete']}"
                    )

            except Exception:
                logger.exception(
                    "Error while getting SBER market data"
                )

            # Ждём следующую минуту.
            # Учитываем время, которое занял API-запрос.
            now = datetime.now(timezone.utc)

            next_minute = (
                now.replace(second=0, microsecond=0)
                + timedelta(minutes=1)
            )

            sleep_time = (
                next_minute - now
            ).total_seconds() + 2

            logger.info(
                "Next SBER market data request in %.1f seconds "
                "(next minute + 2 sec)",
                sleep_time,
            )

            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("SBER market monitoring stopped")

        print()
        print("=" * 100)
        print("SBER MONITORING STOPPED")
        print("=" * 100)
