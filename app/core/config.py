from functools import cached_property
from decimal import Decimal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    APP_NAME: str = "shopease-order-service"
    APP_ENV: str = "development"
    DEBUG: bool = False

    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "shopease_order_db"

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"

    AUTH_SERVICE_URL: str = ""
    USER_SERVICE_URL: str = ""
    USER_PROFILE_PATH_TEMPLATE: str = "/api/users/{user_id}"
    USER_ADDRESS_PATH_TEMPLATE: str = "/api/users/{user_id}/addresses/{address_id}"
    PRODUCT_SERVICE_URL: str = ""
    PRODUCT_PATH_TEMPLATE: str = "/api/products/{product_id}"
    INVENTORY_RESERVATIONS_PATH: str = "/api/inventory/reservations"
    SERVICE_TIMEOUT_SECONDS: float = 5.0

    TAX_RATE: Decimal = Decimal("0.18")
    SHIPPING_CHARGE: Decimal = Decimal("50.00")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("TAX_RATE")
    @classmethod
    def validate_tax_rate(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("TAX_RATE must be between 0 and 1")
        return value

    @field_validator("SHIPPING_CHARGE")
    @classmethod
    def validate_shipping_charge(cls, value: Decimal) -> Decimal:
        if (
            not value.is_finite()
            or value < 0
            or value > Decimal("9999999999.99")
        ):
            raise ValueError(
                "SHIPPING_CHARGE must be within the supported monetary range"
            )
        return value

    @cached_property
    def database_url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )


settings = Settings()
