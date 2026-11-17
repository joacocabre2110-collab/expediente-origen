"""Contratos de datos e interfaces para las etapas de producción."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ContextoVideo:
    video_key: str
    tipo: str
    fecha_publicacion: date | datetime | str
    directorio_trabajo: Path | str
    video_origen: str | None = None

    def __post_init__(self) -> None:
        if self.tipo not in ("largo", "short"):
            raise ValueError("tipo debe ser 'largo' o 'short'")


@dataclass(frozen=True)
class Tema:
    titulo: str
    caso_id: str
    pilar: str
    alias: list[str]


@dataclass(frozen=True)
class Guion:
    texto: str
    gancho: str
    intro: str
    estructura: str
    pilar: str
    afirmaciones: list[dict] | None = None


@dataclass(frozen=True)
class ResultadoVerificacion:
    aprobado: bool
    motivos: list[str]


@dataclass(frozen=True)
class Narracion:
    ruta_audio: Path
    costo_usd: float
    duracion: float = 0.0


@dataclass(frozen=True)
class Render:
    ruta_video: Path
    costo_usd: float


@dataclass(frozen=True)
class ResultadoQA:
    aprobado: bool
    motivos: list[str]


@dataclass(frozen=True)
class Miniatura:
    ruta: Path
    costo_usd: float


@dataclass(frozen=True)
class Metadatos:
    titulo: str
    descripcion: str
    etiquetas: list[str]


class GeneradorTema(Protocol):
    def generar(self, contexto: ContextoVideo) -> Tema: ...


class GeneradorGuion(Protocol):
    def generar(self, contexto: ContextoVideo, tema: Tema) -> Guion: ...


class Verificador(Protocol):
    def verificar(self, contexto: ContextoVideo, tema: Tema, guion: Guion) -> ResultadoVerificacion: ...


class Narrador(Protocol):
    def narrar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
               verificacion: ResultadoVerificacion) -> Narracion: ...


class Renderizador(Protocol):
    def renderizar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                   narracion: Narracion) -> Render: ...


class ControlCalidad(Protocol):
    def controlar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                  narracion: Narracion, render: Render) -> ResultadoQA: ...


class GeneradorMiniatura(Protocol):
    def generar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                render: Render, qa: ResultadoQA) -> Miniatura: ...


class GeneradorMetadatos(Protocol):
    def generar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                render: Render, miniatura: Miniatura) -> Metadatos: ...
