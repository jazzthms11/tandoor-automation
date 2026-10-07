"""Zugangsdaten für die Tandoor-API und das Modell, das den Wochenplan wählt."""

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Liest `TANDOOR_URL` und `TANDOOR_TOKEN` aus der Umgebung oder aus `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tandoor_url: HttpUrl
    tandoor_token: SecretStr


class GeminiSettings(BaseSettings):
    """Liest `GEMINI_API_KEY` und `GEMINI_MODEL` aus der Umgebung oder aus `.env`.

    Ohne Modell nimmt der Lauf das jeweils neueste Flash-Modell. Wer eine bestimmte Fassung will,
    weil die neueste anders wählt, setzt sie fest, etwa `gemini-3.8-flash`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-flash-latest"
