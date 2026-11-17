"""Canal SMTP configurable por archivo, con respaldo durable local."""

from __future__ import annotations

import configparser
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from canal.alerts.notifier import CanalArchivo


class CanalSMTP:
    """Envía alertas por STARTTLS y las archiva tras fallos persistentes.

    El INI contiene [smtp] host, puerto, usuario y opcionalmente remitente.
    La clave se lee de ``password_file``; su contenido nunca se incorpora a
    mensajes de error ni se registra.
    """

    def __init__(
        self,
        config_file: str | Path,
        *,
        password_file: str | Path = "secrets/smtp_password.txt",
        fallback: CanalArchivo | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        retry_delay: float = 0.25,
        smtp_factory: Callable[..., object] | None = None,
    ) -> None:
        if timeout <= 0 or retries < 0 or retry_delay < 0:
            raise ValueError("timeout debe ser positivo; reintentos y demora no negativos")
        self.config_file = Path(config_file)
        self.password_file = Path(password_file)
        self.fallback = fallback or CanalArchivo()
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.smtp_factory = smtp_factory or smtplib.SMTP

    def _config(self) -> tuple[str, int, str, str]:
        parser = configparser.ConfigParser()
        if not parser.read(self.config_file, encoding="utf-8"):
            raise ValueError("No se pudo leer la configuración SMTP")
        try:
            section = parser["smtp"]
            host = section["host"].strip()
            port = section.getint("puerto")
            username = section["usuario"].strip()
            sender = section.get("remitente", username).strip()
        except (KeyError, ValueError) as exc:
            raise ValueError("Configuración SMTP incompleta o inválida") from exc
        if not host or not username or not sender or not 1 <= port <= 65535:
            raise ValueError("Configuración SMTP incompleta o inválida")
        return host, port, username, sender

    def enviar(self, destino: str, asunto: str, cuerpo: str) -> None:
        host, port, username, sender = self._config()
        try:
            password = self.password_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("No se pudo leer el archivo de contraseña SMTP") from exc
        if not password:
            raise RuntimeError("El archivo de contraseña SMTP está vacío")

        message = EmailMessage()
        message["From"] = sender
        message["To"] = destino
        message["Subject"] = asunto
        message.set_content(cuerpo)
        for attempt in range(self.retries + 1):
            try:
                with self.smtp_factory(host, port, timeout=self.timeout) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(username, password)
                    server.send_message(message)
                return
            except Exception as exc:
                if attempt < self.retries and self.retry_delay:
                    time.sleep(self.retry_delay)

        # Store locally even if the fallback raises; preserve the original
        # SMTP failure as a sanitized exception with no server-provided text.
        try:
            self.fallback.enviar(destino, asunto, cuerpo)
        except Exception:
            raise RuntimeError("Falló SMTP y también el respaldo local") from None
