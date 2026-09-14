import logging

import grpc
from t_tech import invest

from config import Settings
from decimal import Decimal


logger = logging.getLogger(__name__)


ACCOUNT_TYPES = {
    1: "BROKER",
    2: "IIS",
    3: "IIS_A",
    4: "IIS_B",
    5: "INVEST_BOX",
}


ACCOUNT_STATUSES = {
    0: "UNSPECIFIED",
    1: "NEW",
    2: "OPEN",
    3: "CLOSED",
}

def money_value_to_decimal(value) -> Decimal:
    """Convert T-Invest MoneyValue to Decimal."""
    return Decimal(value.units) + (
        Decimal(value.nano) / Decimal("1000000000")
    )


def quotation_to_decimal(value) -> Decimal:
    """Convert T-Invest Quotation to Decimal."""
    return Decimal(value.units) + (
        Decimal(value.nano) / Decimal("1000000000")
    )

def account_type_name(account_type) -> str:
    """Return a human-readable account type."""
    value = getattr(account_type, "value", account_type)

    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(account_type)

    return ACCOUNT_TYPES.get(value, f"UNKNOWN ({value})")


def account_status_name(account_status) -> str:
    """Return a human-readable account status."""
    value = getattr(account_status, "value", account_status)

    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(account_status)

    return ACCOUNT_STATUSES.get(value, f"UNKNOWN ({value})")


def get_accounts(settings: Settings):
    """Get all accounts available for the configured T-Invest token."""
    logger.info("Connecting to T-Invest API")

    try:
        with invest.Client(
            settings.tinvest_token,
            app_name=settings.app_name,
        ) as client:
            response = client.users.get_accounts()

    except grpc.RpcError as error:
        code = error.code()

        if code == grpc.StatusCode.UNAUTHENTICATED:
            logger.error(
                "T-Invest API authentication failed: "
                "invalid, expired, or revoked token"
            )
            raise RuntimeError(
                "Недействительный или просроченный T-Invest токен"
            ) from error

        if code == grpc.StatusCode.PERMISSION_DENIED:
            logger.error(
                "T-Invest API access denied: insufficient token permissions"
            )
            raise RuntimeError(
                "T-Invest API отклонил запрос: недостаточно прав токена"
            ) from error

        if code in (
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
        ):
            logger.error(
                "T-Invest API is unavailable: network or service error "
                "(gRPC status: %s)",
                code.name,
            )
            raise RuntimeError(
                "T-Invest API недоступен: проверьте сетевое соединение "
                "или доступность API"
            ) from error

        logger.error(
            "T-Invest API gRPC error: status=%s, details=%s",
            code.name,
            error.details(),
        )
        raise RuntimeError(
            f"Ошибка T-Invest API (gRPC {code.name})"
        ) from error

    except Exception as error:
        logger.exception("Unexpected T-Invest API error")
        raise RuntimeError(
            "Неожиданная ошибка при обращении к T-Invest API"
        ) from error

    logger.info("T-Invest API connection successful")

    accounts = response.accounts

    if not accounts:
        logger.warning(
            "T-Invest API returned no accounts: "
            "there are no accounts available for this token"
        )
        return []

    logger.info("Accounts found: %d", len(accounts))

    for account in accounts:
        logger.info(
            "Account: id=%s, type=%s, status=%s",
            account.id,
            account_type_name(account.type),
            account_status_name(account.status),
        )

    return accounts


def get_selected_account(settings: Settings, accounts):
    """Find and validate the configured account in the provided account list."""
    logger.info(
        "Looking for configured account: %s",
        settings.tinvest_account_id,
    )

    if not settings.tinvest_account_id:
        raise RuntimeError(
            "TINVEST_ACCOUNT_ID не задан"
        )

    for account in accounts:
        if account.id == settings.tinvest_account_id:
            account_type = account_type_name(account.type)
            account_status = account_status_name(account.status)

            logger.info(
                "Selected account: id=%s, type=%s, status=%s",
                account.id,
                account_type,
                account_status,
            )

            if account_status != "OPEN":
                raise RuntimeError(
                    f"Выбранный счёт {account.id} не открыт: "
                    f"status={account_status}"
                )

            return account

    raise RuntimeError(
        f"Счёт {settings.tinvest_account_id} "
        "не найден среди доступных счетов T-Invest"
    )


def get_portfolio(settings: Settings, account):
    """Get portfolio for the selected account."""
    logger.info(
        "Getting portfolio for account %s",
        account.id,
    )

    try:
        with invest.Client(
            settings.tinvest_token,
            app_name=settings.app_name,
        ) as client:
            response = client.operations.get_portfolio(
                account_id=account.id,
            )

    except grpc.RpcError as error:
        code = error.code()

        if code == grpc.StatusCode.UNAUTHENTICATED:
            raise RuntimeError(
                "Недействительный или просроченный T-Invest токен"
            ) from error

        if code == grpc.StatusCode.PERMISSION_DENIED:
            raise RuntimeError(
                "Нет прав для получения портфеля этого счёта"
            ) from error

        if code in (
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
        ):
            raise RuntimeError(
                "T-Invest API недоступен при получении портфеля"
            ) from error

        logger.error(
            "T-Invest API gRPC error while getting portfolio: "
            "status=%s, details=%s",
            code.name,
            error.details(),
        )
        raise RuntimeError(
            f"Ошибка T-Invest API при получении портфеля "
            f"(gRPC {code.name})"
        ) from error

    logger.info(
        "Portfolio received: positions=%d",
        len(response.positions),
    )
    total = money_value_to_decimal(response.total_amount_portfolio)
    daily_yield = money_value_to_decimal(response.daily_yield)
    daily_yield_relative = quotation_to_decimal(response.daily_yield_relative)

    logger.info(
        "Portfolio received: positions=%d, total=%s %s, daily_yield=%s %s, daily_yield_relative=%s%%",
        len(response.positions),
        total,
        response.total_amount_portfolio.currency,
        daily_yield,
        response.daily_yield.currency,
        daily_yield_relative * Decimal("100"),
)

    return response
