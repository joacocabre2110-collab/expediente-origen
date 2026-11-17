"""Herramientas para animación y montaje de vídeo."""
from .config import RenderConfig
from .motor import BASE_CSS, boom, music, page, particles, planet, render_shots, starfield, whoosh
from .shorts import (
    W, H, CX, cam, chunks, build_short, kicker, label, s_big_moon, s_impact,
    s_laser, s_moon, s_number, s_question, s_ring, s_rocks, s_section,
    s_two_planets, ts,
)
from .escenas import Escena, FONDOS, TIPOS, renderizar_cuerpo
from .montaje import Segmento, PlanVideo, Toma, repartir_en_tomas, montar
from .narracion_falsa import narrar_falso
from .calidad import ResultadoQA, verificar_salida

__all__ = [
    "RenderConfig", "BASE_CSS", "boom", "music", "page", "particles", "planet",
    "render_shots", "starfield", "whoosh", "W", "H", "CX", "cam", "chunks",
    "build_short", "kicker", "label", "s_big_moon", "s_impact", "s_laser",
    "s_moon", "s_number", "s_question", "s_ring", "s_rocks", "s_section",
    "s_two_planets", "ts",
    "Escena", "FONDOS", "TIPOS", "renderizar_cuerpo",
    "Segmento", "PlanVideo", "Toma", "repartir_en_tomas", "montar",
    "narrar_falso", "ResultadoQA", "verificar_salida",
]
