from decimal import Decimal

from market_data import calculate_rsi, get_rsi_signal


def test_buy_when_rsi_crosses_30_down():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("30.01"),
        current_rsi=Decimal("29.99"),
    )

    assert signal == "BUY"
    assert "пересёк уровень BUY" in reason


def test_sell_when_rsi_crosses_70_up():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("69.99"),
        current_rsi=Decimal("70.01"),
    )

    assert signal == "SELL"
    assert "пересёк уровень SELL" in reason


def test_hold_when_rsi_stays_in_neutral_zone():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("45.00"),
        current_rsi=Decimal("55.00"),
    )

    assert signal == "HOLD"
    assert "нейтральной зоне" in reason


def test_hold_when_rsi_stays_below_30():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("25.00"),
        current_rsi=Decimal("28.00"),
    )

    assert signal == "HOLD"
    assert "нового пересечения нет" in reason


def test_hold_when_rsi_stays_above_70():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("75.00"),
        current_rsi=Decimal("72.00"),
    )

    assert signal == "HOLD"
    assert "нового пересечения нет" in reason


def test_hold_when_rsi_moves_from_below_30_to_above_30():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("29.00"),
        current_rsi=Decimal("31.00"),
    )

    assert signal == "HOLD"


def test_hold_when_rsi_moves_from_above_70_to_below_70():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("71.00"),
        current_rsi=Decimal("69.00"),
    )

    assert signal == "HOLD"


def test_hold_when_previous_rsi_is_missing():
    signal, reason = get_rsi_signal(
        previous_rsi=None,
        current_rsi=Decimal("25.00"),
    )

    assert signal == "HOLD"
    assert "предыдущее значение отсутствует" in reason


def test_hold_when_current_rsi_is_missing():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("50.00"),
        current_rsi=None,
    )

    assert signal == "HOLD"
    assert "RSI недоступен" in reason


def test_hold_at_buy_level_without_crossing():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("30.00"),
        current_rsi=Decimal("30.00"),
    )

    assert signal == "HOLD"


def test_hold_at_sell_level_without_crossing():
    signal, reason = get_rsi_signal(
        previous_rsi=Decimal("70.00"),
        current_rsi=Decimal("70.00"),
    )

    assert signal == "HOLD"

def test_rsi_returns_none_when_not_enough_data():
    closes = [
        Decimal("100"),
        Decimal("101"),
        Decimal("102"),
        Decimal("101"),
    ]

    result = calculate_rsi(closes, period=14)

    assert result is None


def test_rsi_returns_100_when_price_only_rises():
    closes = [
        Decimal("100"),
        Decimal("101"),
        Decimal("102"),
        Decimal("103"),
        Decimal("104"),
        Decimal("105"),
    ]

    result = calculate_rsi(closes, period=5)

    assert result == Decimal("100")


def test_rsi_returns_0_when_price_only_falls():
    closes = [
        Decimal("105"),
        Decimal("104"),
        Decimal("103"),
        Decimal("102"),
        Decimal("101"),
        Decimal("100"),
    ]

    result = calculate_rsi(closes, period=5)

    assert result == Decimal("0")


def test_rsi_is_50_when_gains_and_losses_are_balanced():
    closes = [
        Decimal("100"),
        Decimal("101"),
        Decimal("100"),
        Decimal("101"),
        Decimal("100"),
        Decimal("101"),
    ]

    result = calculate_rsi(closes, period=5)

    assert result == Decimal("60")


def test_rsi_increases_after_positive_price_move():
    closes = [
        Decimal("100"),
        Decimal("101"),
        Decimal("100"),
        Decimal("101"),
        Decimal("100"),
        Decimal("105"),
        Decimal("106"),
    ]

    result = calculate_rsi(closes, period=5)

    assert result is not None
    assert result > Decimal("50")


def test_rsi_decreases_after_negative_price_move():
    closes = [
        Decimal("100"),
        Decimal("101"),
        Decimal("102"),
        Decimal("101"),
        Decimal("102"),
        Decimal("97"),
        Decimal("96"),
    ]

    result = calculate_rsi(closes, period=5)

    assert result is not None
    assert result < Decimal("50")