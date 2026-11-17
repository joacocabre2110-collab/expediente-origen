import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from canal.youtube import auth


def test_autorizar_guarda_token_con_permisos_privados(tmp_path, monkeypatch):
    credentials = Mock()
    credentials.to_json.return_value = '{"token":"secret"}'
    flow = Mock()
    flow.run_local_server.return_value = credentials
    from_client = Mock(return_value=flow)
    monkeypatch.setattr(auth.InstalledAppFlow, "from_client_secrets_file", from_client)

    assert auth.autorizar(tmp_path) is credentials
    from_client.assert_called_once_with(str(tmp_path / "client_secret.json"), auth.SCOPES)
    flow.run_local_server.assert_called_once_with(port=0, access_type="offline", prompt="consent")
    token = tmp_path / "token.json"
    assert json.loads(token.read_text()) == {"token": "secret"}
    assert os.stat(token).st_mode & 0o777 == 0o600


def test_cargar_refresca_y_guarda_token(tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    token.write_text("{}")
    credentials = Mock(valid=False, expired=True, refresh_token="refresh")
    credentials.to_json.return_value = '{"token":"renewed"}'
    loader = Mock(return_value=credentials)
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", loader)
    request = Mock()
    monkeypatch.setattr(auth, "Request", Mock(return_value=request))

    assert auth.cargar_credenciales(tmp_path) is credentials
    credentials.refresh.assert_called_once_with(request)
    assert json.loads(token.read_text()) == {"token": "renewed"}
    assert os.stat(token).st_mode & 0o777 == 0o600


def test_cargar_falla_si_falta_token(tmp_path):
    with pytest.raises(RuntimeError, match="No se encontró el token OAuth"):
        auth.cargar_credenciales(tmp_path)
