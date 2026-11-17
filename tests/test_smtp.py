from email.message import EmailMessage

import pytest

from canal.alerts.smtp import CanalSMTP


class ServidorFalso:
    def __init__(self, *, falla_login=False):
        self.falla_login = falla_login
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, usuario, clave):
        self.calls.append(("login", usuario, clave))
        if self.falla_login:
            raise RuntimeError(f"credencial inválida: {clave}")

    def send_message(self, mensaje):
        assert isinstance(mensaje, EmailMessage)
        self.calls.append(("send", mensaje["To"], mensaje["Subject"]))


class ArchivoFalso:
    def __init__(self):
        self.messages = []

    def enviar(self, *args):
        self.messages.append(args)


def crear_archivos(tmp_path):
    config = tmp_path / "smtp.ini"
    config.write_text(
        "[smtp]\nhost = mail.example.test\npuerto = 587\n"
        "usuario = bot@example.test\nremitente = Canal <bot@example.test>\n",
        encoding="utf-8",
    )
    password = tmp_path / "smtp_password.txt"
    password.write_text("secreto-de-prueba\n", encoding="utf-8")
    return config, password


def test_envia_con_starttls_y_timeout_desde_config(tmp_path):
    config, password = crear_archivos(tmp_path)
    server = ServidorFalso()
    factory_args = []

    def factory(host, port, *, timeout):
        factory_args.append((host, port, timeout))
        return server

    channel = CanalSMTP(config, password_file=password, smtp_factory=factory, timeout=4)
    channel.enviar("dest@example.test", "Alerta", "Contenido")

    assert factory_args == [("mail.example.test", 587, 4)]
    assert server.calls[:4] == ["ehlo", "starttls", "ehlo", ("login", "bot@example.test", "secreto-de-prueba")]
    assert server.calls[-1] == ("send", "dest@example.test", "Alerta")


def test_reintenta_y_guarda_en_respaldo_si_smtp_falla(tmp_path):
    config, password = crear_archivos(tmp_path)
    fallback = ArchivoFalso()
    attempts = []

    def factory(*args, **kwargs):
        attempts.append(1)
        raise OSError("sin conexión")

    channel = CanalSMTP(config, password_file=password, fallback=fallback, retries=2,
                        retry_delay=0, smtp_factory=factory)
    channel.enviar("dest@example.test", "Alerta", "Contenido")

    assert len(attempts) == 3
    assert fallback.messages == [("dest@example.test", "Alerta", "Contenido")]


def test_error_no_revela_contraseña(tmp_path):
    config, password = crear_archivos(tmp_path)
    fallback = ArchivoFalso()
    server = ServidorFalso(falla_login=True)
    channel = CanalSMTP(config, password_file=password, fallback=fallback, retries=0,
                        retry_delay=0, smtp_factory=lambda *a, **kw: server)
    channel.enviar("dest@example.test", "Alerta", "Contenido")
    # El fallo SMTP queda oculto porque se guardó correctamente el respaldo.
    assert fallback.messages

    class FallaRespaldo:
        def enviar(self, *args):
            raise RuntimeError("disco no disponible")

    channel.fallback = FallaRespaldo()
    with pytest.raises(RuntimeError) as error:
        channel.enviar("dest@example.test", "Alerta", "Contenido")
    assert "secreto-de-prueba" not in str(error.value)
    assert "secreto-de-prueba" not in repr(error.value.__cause__)
