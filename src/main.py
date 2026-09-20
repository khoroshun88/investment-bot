import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import yaml

from config import load_settings
from database import (
    check_connection,
    init_database,
    save_instruments,
)
from logging_config import setup_logging
from market_data import monitor_instrument
from tinvest_client import (
    get_accounts,
    get_selected_account,
    get_portfolio,
    get_instrument_metadata,
    print_accounts_info,
)


STOCKS_CONFIG_FILE = "stocks.yaml"


def load_stocks_config(
    filename: str = STOCKS_CONFIG_FILE,
) -> list[dict]:
    """
    Загружает список инструментов и бюджетов из YAML.

    Формат:

        stocks:
          - ticker: SBER
            budget_rub: 500

          - ticker: YDEX
            budget_rub: 300
    """

    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file) or {}

    stocks = config.get("stocks", [])

    if not isinstance(stocks, list):
        raise ValueError(
            "Поле 'stocks' в stocks.yaml должно быть списком"
        )

    if not stocks:
        raise ValueError(
            "В stocks.yaml не настроен ни один инструмент"
        )

    result = []

    for index, stock in enumerate(stocks, start=1):
        if not isinstance(stock, dict):
            raise ValueError(
                f"stocks[{index}] должен быть объектом"
            )

        ticker = stock.get("ticker")
        budget_rub = stock.get("budget_rub")

        if not ticker:
            raise ValueError(
                f"stocks[{index}]: отсутствует ticker"
            )

        if budget_rub is None:
            raise ValueError(
                f"stocks[{index}] {ticker}: "
                f"отсутствует budget_rub"
            )

        try:
            budget_rub = float(budget_rub)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"stocks[{index}] {ticker}: "
                f"budget_rub должен быть числом"
            ) from error

        if budget_rub <= 0:
            raise ValueError(
                f"stocks[{index}] {ticker}: "
                f"budget_rub должен быть > 0"
            )

        result.append(
            {
                "ticker": str(ticker).upper(),
                "budget_rub": budget_rub,
            }
        )

    return result


def monitor_stock(
    settings,
    stock_config: dict,
) -> None:
    """
    Запускает мониторинг одного инструмента.

    Каждый инструмент работает в собственном потоке.
    """

    ticker = stock_config["ticker"]
    budget_rub = stock_config["budget_rub"]

    logger = logging.getLogger(__name__)

    logger.info(
        "Starting stock monitor: ticker=%s budget=%s RUB",
        ticker,
        budget_rub,
    )

    monitor_instrument(
        settings,
        ticker=ticker,
        budget_rub=budget_rub,
        candles_count=200,
    )


def main() -> None:
    settings = load_settings()

    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)

    logger.info(
        "Starting %s in %s environment",
        settings.app_name,
        settings.app_env,
    )

    # -------------------------------------------------------------
    # Загружаем список инструментов.
    # -------------------------------------------------------------

    stocks = load_stocks_config()

    logger.info(
        "Configured instruments: %d",
        len(stocks),
    )

    for stock in stocks:
        logger.info(
            "Configured instrument: ticker=%s budget=%s RUB",
            stock["ticker"],
            stock["budget_rub"],
        )

    # -------------------------------------------------------------
    # Проверяем PostgreSQL.
    # -------------------------------------------------------------

    check_connection(settings)
    init_database(settings)

    # -------------------------------------------------------------
    # Проверяем T-Invest API.
    # -------------------------------------------------------------

    accounts = get_accounts(settings)

    print_accounts_info(
        settings,
        accounts,
    )

    account = get_selected_account(
        settings,
        accounts,
    )

    portfolio = get_portfolio(
        settings,
        account,
    )

    metadata = get_instrument_metadata(
        settings,
        portfolio,
    )

    save_instruments(
        settings,
        metadata,
    )

    for uid, instrument in metadata.items():
        print("=" * 80)
        print("UID:", uid)
        print(instrument)

    logger.info(
        "Application startup check completed successfully"
    )

    # -------------------------------------------------------------
    # Запускаем отдельный монитор для каждого инструмента.
    # -------------------------------------------------------------

    logger.info(
        "Starting %d instrument monitors",
        len(stocks),
    )

    with ThreadPoolExecutor(
        max_workers=len(stocks),
        thread_name_prefix="market",
    ) as executor:

        futures = []

        for stock in stocks:
            future = executor.submit(
                monitor_stock,
                settings,
                stock,
            )

            futures.append(
                (
                    stock["ticker"],
                    future,
                )
            )

        # Мониторы работают бесконечно.
        # Если один из них завершится с исключением,
        # логируем его.
        for ticker, future in futures:
            try:
                future.result()

            except KeyboardInterrupt:
                logger.info(
                    "KeyboardInterrupt received"
                )
                raise

            except Exception:
                logger.exception(
                    "Monitor thread failed: ticker=%s",
                    ticker,
                )


if __name__ == "__main__":
    main()