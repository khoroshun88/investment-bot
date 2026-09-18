import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    tinvest_token: str
    tinvest_account_id: str
    instrument_ticker: str


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "investment-bot"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        db_host=os.getenv("DB_HOST", "postgres"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.environ["POSTGRES_DB"],
        db_user=os.environ["POSTGRES_USER"],
        db_password=os.environ["POSTGRES_PASSWORD"],
        tinvest_token=os.getenv("TINVEST_TOKEN", ""),
        tinvest_account_id=os.getenv("TINVEST_ACCOUNT_ID", ""),
        instrument_ticker=os.getenv("INSTRUMENT_TICKER", "SBER"),
    )
