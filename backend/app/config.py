import os
from typing import List
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "seat_user"
    DB_PASSWORD: str = "seat_password"
    DB_NAME: str = "seat_booking"

    # Event specifications
    TOTAL_ROWS: int = 10
    SEATS_PER_ROW: int = 12
    TOTAL_SEATS: int = 120
    HOLD_DURATION_SECONDS: int = 300  # 5 minutes
    MAX_HOLD_SEATS: int = 4

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
