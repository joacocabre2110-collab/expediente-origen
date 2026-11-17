from pathlib import Path

from scripts.auditar_publico import auditar, excluido


def test_auditoria_detecta_credencial_y_omite_archivos_ignorados(tmp_path: Path):
    bearer = "Authorization: " + "Bearer " + ("abcdefghijklm" + "nopqrstuvwxyz0123456789")
    (tmp_path / "visible.txt").write_text(bearer, encoding="utf-8")
    (tmp_path / "config.toml").write_text('email_alertas="persona@example.test"', encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "token.json").write_text("secreto", encoding="utf-8")
    hallazgos = auditar(tmp_path)
    assert hallazgos == [("visible.txt", "posible clave API/token bearer")]


def test_gitignore_publico_incluye_archivos_sensibles():
    assert excluido("secrets/token.json")
    assert excluido("config.toml")
    assert excluido("assets/audio/musica.mp3")
    assert excluido("datos_corrida/real/queue.sqlite")
    assert excluido("docs_externas/referencia.txt")
    assert excluido("token-youtube.json")
    assert excluido("client_secret_oauth.json")
