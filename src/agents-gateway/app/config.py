from __future__ import annotations

import functools
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Vertex / Project
    PROJECT_ID: str = Field(..., description="GCP project id")
    REGION: str = Field("europe-west1", description="Vertex/AlloyDB region")

    # Database (read-only)
    DB_HOST: str = Field(...)
    DB_PORT: int = Field(5432)
    DB_NAME: str = Field("products")
    DB_USER: str = Field("postgres")
    DB_PASSWORD: str = Field(...)

    # Limits
    API_TOP_K_MAX: int = Field(50)
    MAX_UPLOAD_MB: int = Field(10)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore")


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]


class HealthSnapshot(BaseModel):
    project: str
    region: str
    top_k_max: int
    upload_mb_max: int
