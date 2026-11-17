"""Notificaciones de alertas con archivo local por defecto."""

from __future__ import annotations

import os
import re
import smtplib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate
from enum import Enum
from pathlib import Path
from typing import Protocol


class Nivel(Enum):
    CRITICO = "critico"
    DIARIO = "diario"
    SEMANAL = "semanal"


@dataclass(frozen=True)
class Alerta:
    nivel: Nivel
    asunto: str
    cuerpo: str
    video_key: str | None = None
    creado: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Canal(Protocol):
    def enviar(self, destino: str, asunto: str, cuerpo: str) -> None: ...


class CanalArchivo:
    """Guarda cada mensaje como un archivo de correo y una copia de texto."""

    def __init__(self, directorio: str | Path = "alerts") -> None:
        self.directorio = Path(directorio)

    def enviar(self, destino: str, asunto: str, cuerpo: str) -> None:
        self.directorio.mkdir(parents=True, exist_ok=True)
        identificador = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex}"
        mensaje = EmailMessage()
        mensaje["To"] = destino
        mensaje["Subject"] = asunto
        mensaje["Date"] = formatdate(localtime=False)
        mensaje.set_content(cuerpo)
        (self.directorio / f"{identificador}.eml").write_bytes(bytes(mensaje))
        (self.directorio / f"{identificador}.txt").write_text(
            f"Para: {destino}\nAsunto: {asunto}\n\n{cuerpo}", encoding="utf-8"
        )


class CanalSMTP:
    """Canal SMTP opt-in. Los nombres de variables no se consultan hasta enviar."""

    def __init__(
        self,
        host: str,
        puerto: int,
        usuario_env: str,
        clave_env: str,
        *,
        habilitado: bool = False,
        remitente: str | None = None,
        starttls: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.puerto = puerto
        self.usuario_env = usuario_env
        self.clave_env = clave_env
        self.habilitado = habilitado
        self.remitente = remitente
        self.starttls = starttls
        self.timeout = timeout

    def enviar(self, destino: str, asunto: str, cuerpo: str) -> None:
        if not self.habilitado:
            raise RuntimeError("CanalSMTP está deshabilitado; configure habilitado=True explícitamente")
        usuario = os.environ.get(self.usuario_env)
        clave = os.environ.get(self.clave_env)
        if not usuario or not clave:
            raise RuntimeError("Faltan credenciales SMTP en las variables de entorno configuradas")
        mensaje = EmailMessage()
        mensaje["From"] = self.remitente or usuario
        mensaje["To"] = destino
        mensaje["Subject"] = asunto
        mensaje.set_content(cuerpo)
        with smtplib.SMTP(self.host, self.puerto, timeout=self.timeout) as servidor:
            if self.starttls:
                servidor.starttls()
            servidor.login(usuario, clave)
            servidor.send_message(mensaje)


_EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


class Notificador:
    def __init__(
        self,
        canal: Canal | None = None,
        destino: str | None = None,
        *,
        ventana_dedupe: timedelta | float = timedelta(hours=24),
    ) -> None:
        self.canal: Canal = canal if canal is not None else CanalArchivo()
        self.destino = self._validar_destino(destino)
        self.ventana_dedupe = (
            ventana_dedupe if isinstance(ventana_dedupe, timedelta) else timedelta(seconds=ventana_dedupe)
        )
        if self.ventana_dedupe < timedelta(0):
            raise ValueError("ventana_dedupe no puede ser negativa")
        self.bandeja: list[Alerta] = []
        self._pendientes: dict[Nivel, list[Alerta]] = {Nivel.DIARIO: [], Nivel.SEMANAL: []}
        self._vistos: dict[tuple[object, ...], datetime] = {}
        self.advertencias: list[str] = []
        if not self.destino:
            self.advertencias.append("Destino pendiente: las alertas se conservarán en la bandeja local.")

    @staticmethod
    def _clave(alerta: Alerta) -> tuple[object, ...]:
        return (alerta.nivel, alerta.asunto, alerta.cuerpo, alerta.video_key)

    @staticmethod
    def _validar_destino(destino: str | None) -> str | None:
        limpio = destino.strip() if isinstance(destino, str) else None
        if limpio and not _EMAIL_RE.fullmatch(limpio):
            raise ValueError(f"Formato de destino inválido: {limpio!r}")
        return limpio

    def configurar_destino(self, destino: str | None) -> None:
        self.destino = self._validar_destino(destino)
        if self.destino:
            self.advertencias = [a for a in self.advertencias if not a.startswith("Destino pendiente:")]
        elif not any(a.startswith("Destino pendiente:") for a in self.advertencias):
            self.advertencias.append("Destino pendiente: las alertas se conservarán en la bandeja local.")

    def notificar(self, alerta: Alerta) -> bool:
        clave = self._clave(alerta)
        anterior = self._vistos.get(clave)
        if anterior is not None and alerta.creado - anterior <= self.ventana_dedupe:
            return False
        if alerta.nivel is Nivel.CRITICO:
            if not self.destino:
                self.bandeja.append(alerta)
                self._vistos[clave] = alerta.creado
                return True
            try:
                self.canal.enviar(self.destino, alerta.asunto, alerta.cuerpo)
            except Exception:
                self.bandeja.append(alerta)
                raise
            self._vistos[clave] = alerta.creado
            if alerta in self.bandeja:
                self.bandeja.remove(alerta)
            return True
        self._vistos[clave] = alerta.creado
        self._pendientes[alerta.nivel].append(alerta)
        return True

    def reenviar_bandeja(self) -> int:
        if not self.destino:
            return 0
        enviados = 0
        while self.bandeja:
            alerta = self.bandeja[0]
            self.canal.enviar(self.destino, alerta.asunto, alerta.cuerpo)
            del self.bandeja[0]
            self._vistos[self._clave(alerta)] = alerta.creado
            enviados += 1
        return enviados

    def vaciar_resumen(self, nivel: Nivel) -> bool:
        if nivel not in self._pendientes:
            raise ValueError("Solo se pueden vaciar resúmenes DIARIO o SEMANAL")
        alertas = self._pendientes[nivel]
        if not alertas:
            return False
        if not self.destino:
            self.bandeja.extend(alertas)
            alertas.clear()
            return False
        asunto = f"Resumen {nivel.value}: {len(alertas)} alertas"
        cuerpo = "\n\n".join(
            f"[{alerta.creado.isoformat()}] {alerta.asunto}\n{alerta.cuerpo}"
            for alerta in alertas
        )
        self.canal.enviar(self.destino, asunto, cuerpo)
        alertas.clear()
        return True
