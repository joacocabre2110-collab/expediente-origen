"""Contratos e implementaciones falsas del pipeline."""

from .etapas import (
    ContextoVideo, GeneradorGuion, GeneradorMetadatos, GeneradorMiniatura,
    GeneradorTema, Guion, Metadatos, Miniatura, Narracion, Narrador,
    Render, Renderizador, ResultadoQA, ResultadoVerificacion, Tema,
    ControlCalidad, Verificador,
)
from .orquestador import Orquestador, ResultadoPaso

__all__ = [
    "ContextoVideo", "Tema", "Guion", "ResultadoVerificacion", "Narracion",
    "Render", "ResultadoQA", "Miniatura", "Metadatos", "GeneradorTema",
    "GeneradorGuion", "Verificador", "Narrador", "Renderizador",
    "ControlCalidad", "GeneradorMiniatura", "GeneradorMetadatos",
    "Orquestador", "ResultadoPaso",
]
