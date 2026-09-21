"""Zugriff auf die Kassenbons in Lidl Plus.

Die App-API ist klein: ein Token-Tausch gegen `accounts.lidl.com` und zwei Endpunkte für die
Bons. Der Zugang läuft über OAuth mit PKCE, so wie die App selbst ihn führt. Einmalig muss der
Anmeldebildschirm im Browser durchlaufen werden, danach trägt der Refresh-Token allein.

Die API ist nicht dokumentiert, sie stammt aus mitgeschnittenen Anfragen der App und kann sich
jederzeit ändern. Die Kopfzeilen unten geben deshalb die App aus.
"""

import base64
import hashlib
import secrets
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://accounts.lidl.com/connect/authorize"
TOKEN_URL = "https://accounts.lidl.com/connect/token"
LIST_URL = "https://tickets.lidlplus.com/api/v2"
DETAIL_URL = "https://tickets.lidlplus.com/api/v3"
"""Liste und Einzelbon liegen auf verschiedenen Fassungen der API. Die Liste kennt v3 nicht,
der Einzelbon antwortet auf v2 mit 400."""
CLIENT_ID = "LidlPlusNativeClient"
REDIRECT_URI = "com.lidlplus.app://callback"
SCOPE = "openid profile offline_access lpprofile lpapis"
COUNTRY = "DE"
LANGUAGE = "de"
TIMEOUT_SECONDS = 30
EXPIRY_MARGIN = timedelta(minutes=1)
VERIFIER_BYTES = 64

TOKEN_FILE = Path(".lidl-token")
"""Der Refresh-Token, die einzige Stelle, an der er liegt. Lidl gibt bei jedem Erneuern einen
neuen aus und sichert nicht zu, dass der alte gültig bleibt, die Datei wird deshalb bei jedem
Tausch überschrieben."""


class LidlAuthError(Exception):
    """Der Zugang zu Lidl Plus fehlt oder wurde abgewiesen."""


def login_url() -> tuple[str, str]:
    """Baut die Adresse des Anmeldebildschirms.

    Returns:
        Die Adresse und den dazugehörigen `code_verifier`. Beide gehören zusammen: der Verifier
        beweist beim Einlösen, dass der Code aus genau diesem Anlauf stammt.
    """
    verifier = secrets.token_urlsafe(VERIFIER_BYTES)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    query = urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "scope": SCOPE,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "Country": COUNTRY,
            "language": f"{LANGUAGE}-{COUNTRY}",
        }
    )
    return f"{AUTHORIZE_URL}?{query}", verifier


def redeem(code: str, verifier: str) -> None:
    """Tauscht den Anmeldecode gegen einen Refresh-Token und legt ihn ab.

    Args:
        code: Der Wert des Parameters `code` aus der Adresse, auf die Lidl weiterleitet.
        verifier: Der `code_verifier` aus demselben Anlauf.
    """
    answer = _request_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    )
    _store(answer["refresh_token"])


def _request_token(payload: dict[str, str]) -> dict[str, Any]:
    """Ruft den Token-Endpunkt auf und gibt die Antwort zurück.

    Raises:
        LidlAuthError: Wenn Lidl den Tausch abweist.
    """
    secret = base64.b64encode(f"{CLIENT_ID}:secret".encode()).decode()
    response = httpx.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {secret}"},
        data=payload,
        timeout=TIMEOUT_SECONDS,
    )
    answer: dict[str, Any] = response.json()
    if "access_token" not in answer:
        raise LidlAuthError(answer.get("error_description") or answer.get("error") or answer)
    return answer


def _store(token: str) -> None:
    """Hält den Refresh-Token fest."""
    TOKEN_FILE.write_text(f"{token}\n", encoding="utf-8")


class LidlClient:
    """Holt die Liste der Kassenbons und einzelne Bons, beide im Rohformat der API.

    Als Kontextmanager benutzen, damit die HTTP-Verbindung wieder geschlossen wird:

    ```python
    with LidlClient() as lidl:
        for summary in lidl.tickets():
            print(summary["id"])
    ```
    """

    def __init__(self) -> None:
        """Nimmt den abgelegten Refresh-Token auf und baut den HTTP-Client.

        Raises:
            LidlAuthError: Wenn noch kein Zugang besteht.
        """
        if not TOKEN_FILE.exists():
            raise LidlAuthError(f"Kein Zugang zu Lidl Plus, {TOKEN_FILE} fehlt")
        self._refresh_token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        self._access_token = ""
        self._expires_at = datetime.min
        self._client = httpx.Client(timeout=TIMEOUT_SECONDS)

    def __enter__(self) -> "LidlClient":
        """Gibt den Client selbst zurück."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Schließt die HTTP-Verbindung."""
        self._client.close()

    def tickets(self) -> Iterator[dict[str, Any]]:
        """Geht die Bonliste Seite für Seite durch, neueste zuerst.

        Yields:
            Je eine Zusammenfassung mit `id`, `date` und Summe, ohne die einzelnen Positionen.
        """
        page = 1
        seen = 0
        while True:
            answer = self._get(f"{LIST_URL}/{COUNTRY}/tickets", {"pageNumber": page})
            tickets = answer.get("tickets") or []
            if not tickets:
                return
            yield from tickets
            seen += len(tickets)
            if seen >= int(answer.get("totalCount", seen)):
                return
            page += 1

    def ticket(self, ticket_id: str) -> dict[str, Any]:
        """Holt einen einzelnen Bon mit allen Positionen.

        Args:
            ticket_id: Die ID aus der Bonliste.

        Returns:
            Die Antwort der API, unverändert. Die einzelnen Positionen stehen nicht als Felder
            darin, sondern als Beleg in HTML unter `htmlPrintedReceipt`.
        """
        return self._get(f"{DETAIL_URL}/{COUNTRY}/tickets/{ticket_id}", None)

    def _get(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Ruft die API auf und gibt die Antwort als Objekt zurück."""
        response = self._client.get(url, params=params, headers=self._headers())
        response.raise_for_status()
        answer: dict[str, Any] = response.json()
        return answer

    def _headers(self) -> dict[str, str]:
        """Gibt die Kopfzeilen der App aus und erneuert vorher den Zugang, falls nötig.

        Ein `App-Version`-Kopf fehlt mit Absicht: die Liste bleibt mit ihm ohne Antwort stehen,
        bis die Verbindung abläuft, und ohne ihn antworten beide Endpunkte.
        """
        if datetime.now() >= self._expires_at:
            self._renew()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "App": "com.lidl.eci.lidlplus",
            "Country": COUNTRY,
            "Accept-Language": COUNTRY,
        }

    def _renew(self) -> None:
        """Tauscht den Refresh-Token gegen einen frischen Zugang und hält den neuen fest."""
        answer = _request_token(
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        )
        self._access_token = answer["access_token"]
        self._expires_at = datetime.now() + timedelta(seconds=answer["expires_in"]) - EXPIRY_MARGIN
        renewed = answer.get("refresh_token")
        if renewed and renewed != self._refresh_token:
            _store(renewed)
            self._refresh_token = renewed
