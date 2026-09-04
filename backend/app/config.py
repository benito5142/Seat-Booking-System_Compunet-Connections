import os
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Settings:
    """Environment-based configuration for the Seat Booking System backend."""

    def __init__(self):
        # Database Settings
        self.DB_HOST: str = os.getenv("DB_HOST", "localhost")
        self.DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
        self.DB_USER: str = os.getenv("DB_USER", "root")
        self.DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
        self.DB_NAME: str = os.getenv("DB_NAME", "seat_booking")

        # Application Settings
        self.APP_ENV: str = os.getenv("APP_ENV", "development")
        self.APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
        self.APP_PORT: int = int(os.getenv("APP_PORT", "8000"))

        # CORS Settings
        self.CORS_ORIGINS: List[str] = [
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        ]

        # Event Fixed Seat Map Specifications (1 single event, 10 rows x 12 seats = 120 seats)
        self.TOTAL_ROWS: int = 10
        self.SEATS_PER_ROW: int = 12
        self.TOTAL_SEATS: int = self.TOTAL_ROWS * self.SEATS_PER_ROW

    @property
    def DATABASE_URL(self) -> str:
        """Constructs the MySQL database connection URL using PyMySQL driver."""
        password_part = f":{self.DB_PASSWORD}" if self.DB_PASSWORD else ""
        return f"mysql+pymysql://{self.DB_USER}{password_part}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
