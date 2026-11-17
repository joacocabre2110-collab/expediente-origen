"""Autenticación OAuth para las operaciones de YouTube."""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _guardar_token(credentials: Credentials, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(credentials.to_json(), encoding="utf-8")
    os.chmod(ruta, 0o600)


def cargar_credenciales(dir_secretos: Path = Path("secrets")) -> Credentials:
    """Carga credenciales existentes y refresca las vencidas."""
    ruta = Path(dir_secretos) / "token.json"
    if not ruta.is_file():
        raise RuntimeError(f"No se encontró el token OAuth: {ruta}")
    try:
        credentials = Credentials.from_authorized_user_file(str(ruta), SCOPES)
        if not credentials.valid:
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                _guardar_token(credentials, ruta)
            else:
                raise RuntimeError("El token OAuth no es válido o no puede refrescarse")
        return credentials
    except RuntimeError:
        raise
    except (OSError, ValueError, GoogleAuthError) as exc:
        raise RuntimeError("No se pudo leer o refrescar el token OAuth") from exc


def autorizar(dir_secretos: Path = Path("secrets")) -> Credentials:
    """Ejecuta el flujo OAuth local y guarda el token con permisos privados."""
    ruta_cliente = Path(dir_secretos) / "client_secret.json"
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(ruta_cliente), SCOPES)
        credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    except Exception as exc:
        # Evita propagar excepciones de proveedores que pudieran incluir datos sensibles.
        raise RuntimeError("No se pudo completar la autorización OAuth de YouTube") from exc
    _guardar_token(credentials, Path(dir_secretos) / "token.json")
    return credentials
