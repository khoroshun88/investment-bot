from decimal import Decimal

from strategy import Strategy


def test_buy_opens_position():
    strategy = Strategy()

    action, reason = strategy.work(
        signal="BUY",
        price=Decimal("284.35"),
    )

    assert action == "OPEN"
    assert reason == "RSI BUY"

    assert strategy.position is not None
    assert strategy.position.side == "LONG"
    assert strategy.position.entry_price == Decimal("284.35")

    assert strategy.position.stop_loss == Decimal("278.6630")
    assert strategy.position.take_profit == Decimal("295.7240")


def test_sell_closes_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("284.35"),
    )

    action, reason = strategy.work(
        signal="SELL",
        price=Decimal("290.10"),
    )

    assert action == "CLOSE"
    assert reason == "RSI SELL"
    assert strategy.position is None


def test_hold_does_nothing_without_position():
    strategy = Strategy()

    action, reason = strategy.work(
        signal="HOLD",
        price=Decimal("284.35"),
    )

    assert action == "HOLD"
    assert reason == "RSI HOLD"
    assert strategy.position is None


def test_hold_keeps_existing_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("284.35"),
    )

    action, reason = strategy.work(
        signal="HOLD",
        price=Decimal("285.00"),
    )

    assert action == "HOLD"
    assert reason == "RSI HOLD"

    assert strategy.position is not None
    assert strategy.position.entry_price == Decimal("284.35")


def test_buy_does_not_open_second_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("284.35"),
    )

    action, reason = strategy.work(
        signal="BUY",
        price=Decimal("280.00"),
    )

    assert action == "HOLD"
    assert reason == "LONG уже открыта"

    assert strategy.position is not None
    assert strategy.position.entry_price == Decimal("284.35")


def test_sell_without_position_does_nothing():
    strategy = Strategy()

    action, reason = strategy.work(
        signal="SELL",
        price=Decimal("290.10"),
    )

    assert action == "HOLD"
    assert reason == "LONG-позиция отсутствует"
    assert strategy.position is None


def test_stop_loss_closes_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    assert strategy.position is not None
    assert strategy.position.stop_loss == Decimal("98.00")

    action, reason = strategy.work(
        signal="HOLD",
        price=Decimal("98.00"),
    )

    assert action == "CLOSE"
    assert reason == "STOP_LOSS"
    assert strategy.position is None


def test_take_profit_closes_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    assert strategy.position is not None
    assert strategy.position.take_profit == Decimal("104.00")

    action, reason = strategy.work(
        signal="HOLD",
        price=Decimal("104.00"),
    )

    assert action == "CLOSE"
    assert reason == "TAKE_PROFIT"
    assert strategy.position is None


def test_stop_loss_has_priority_over_signal():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    action, reason = strategy.work(
        signal="BUY",
        price=Decimal("98.00"),
    )

    assert action == "CLOSE"
    assert reason == "STOP_LOSS"
    assert strategy.position is None


def test_take_profit_has_priority_over_signal():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    action, reason = strategy.work(
        signal="SELL",
        price=Decimal("104.00"),
    )

    assert action == "CLOSE"
    assert reason == "TAKE_PROFIT"
    assert strategy.position is None

def test_price_above_stop_loss_keeps_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    action, reason = strategy.work(
        signal="HOLD",
        price=Decimal("98.01"),
    )

    assert action == "HOLD"
    assert reason == "RSI HOLD"
    assert strategy.position is not None

def test_price_below_take_profit_keeps_position():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    action, reason = strategy.work(
        signal="HOLD",
        price=Decimal("103.99"),
    )

    assert action == "HOLD"
    assert reason == "RSI HOLD"
    assert strategy.position is not None

def test_stop_loss_is_two_percent():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    assert strategy.position is not None
    assert strategy.position.stop_loss == Decimal("98.00")

def test_take_profit_is_four_percent():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    assert strategy.position is not None
    assert strategy.position.take_profit == Decimal("104.00")


def test_reprice_uses_actual_execution_price():
    strategy = Strategy()

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    assert strategy.position is not None

    strategy.position.quantity = 2
    strategy.position.reprice(
        Decimal("105.00"),
        stop_loss_percent=strategy.stop_loss_percent,
        take_profit_percent=strategy.take_profit_percent,
    )

    assert strategy.position.entry_price == Decimal("105.00")
    assert strategy.position.stop_loss == Decimal("102.9000")
    assert strategy.position.take_profit == Decimal("109.2000")
    assert strategy.position.quantity == 2


def test_reprice_uses_strategy_percentages():
    strategy = Strategy(
        stop_loss_percent=Decimal("0.05"),
        take_profit_percent=Decimal("0.10"),
    )

    strategy.work(
        signal="BUY",
        price=Decimal("100.00"),
    )

    assert strategy.position is not None

    strategy.position.reprice(
        Decimal("200.00"),
        stop_loss_percent=strategy.stop_loss_percent,
        take_profit_percent=strategy.take_profit_percent,
    )

    assert strategy.position.entry_price == Decimal("200.00")
    assert strategy.position.stop_loss == Decimal("190.00")
    assert strategy.position.take_profit == Decimal("220.00")