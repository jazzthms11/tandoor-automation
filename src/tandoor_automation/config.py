"""Zugangsdaten für die Tandoor-API."""

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Liest `TANDOOR_URL` und `TANDOOR_TOKEN` aus der Umgebung oder aus `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tandoor_url: HttpUrl
    tandoor_token: SecretStr
