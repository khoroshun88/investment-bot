import logging

from config import load_settings
from database import check_connection, init_database, save_instruments
from logging_config import setup_logging
from tinvest_client import (
    get_accounts,
    get_selected_account,
    get_portfolio,
    get_instrument_metadata,
    money_value_to_decimal,
    quotation_to_decimal,
    print_accounts_info,
)
from market_data import monitor_sber

def main() -> None:
    settings = load_settings()

    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)

    logger.info(
        "Starting %s in %s environment",
        settings.app_name,
        settings.app_env,
    )

    check_connection(settings)
    init_database(settings)

    accounts = get_accounts(settings)

    print_accounts_info(settings, accounts)

    account = get_selected_account(settings, accounts)
    portfolio = get_portfolio(settings, account)
    metadata = get_instrument_metadata(settings, portfolio)
    save_instruments(settings, metadata)


    for uid, instrument in metadata.items():
        print("=" * 80)
        print("UID:", uid)
        print(instrument)

    logger.info("Application startup check completed successfully")

    monitor_sber(
        settings,
        candles_count=200,
    )


if __name__ == "__main__":
    main()