"""Ensamblado del Orquestador con las implementaciones reales o falsas.

La publicación pública queda SIEMPRE deshabilitada aquí: ClienteSeguro se crea
con publicacion_publica_habilitada=False sin importar lo que diga la config.
Solo se comprueba la EXISTENCIA de los archivos de clave, nunca su contenido.
"""
from __future__ import annotations

import tomllib
import os
import warnings
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from canal.alerts import CanalArchivo, Notificador
from canal.budget import Ledger
from canal.dedupe import Historial, RegistroTemas
from canal.pipeline import Orquestador
from canal.pipeline.etapas import Metadatos
from canal.queue import QueueStore
from canal.youtube import ClienteFalso, ClienteSeguro

AVISO_IA = "Narración con voz generada por IA. Ilustraciones: recreación artística."
_RAIZ = Path(__file__).resolve().parents[3]
_ARCHIVOS_CLAVE = ("gemini_api_key.txt", "speko_api_key.txt", "token.json")


@dataclass
class Ensamblado:
    orquestador: Orquestador
    ledger: Ledger
    cola: QueueStore
    cliente: ClienteSeguro
    advertencias: list[str]


class GeneradorMetadatosConAviso:
    """Envuelve al generador de metadatos y agrega, de forma determinista, el aviso de IA y el ID interno."""

    def __init__(self, base: Any) -> None:
        self.base = base
        self.imagenes: list[Any] = []

    def generar(self, contexto, tema, guion, render, miniatura) -> Metadatos:
        m = self.base.generar(contexto, tema, guion, render, miniatura)
        desc = m.descripcion.strip()
        if AVISO_IA not in desc:
            desc += "\n\n" + AVISO_IA
        linea = f"ID-interno: {contexto.video_key}"
        if linea not in desc:
            desc += "\n" + linea
        if self.imagenes:
            from canal.investigacion.imagenes import creditos
            # Mantener atribuciones completas: se descartan imágenes si no entran.
            elegidas = []
            for imagen in self.imagenes:
                candidato = elegidas + [imagen]
                bloque = creditos(candidato)
                separador = "\n\n"
                if len(desc.rstrip() + separador + bloque) <= 5000:
                    elegidas = candidato
            bloque = creditos(elegidas)
            if bloque:
                desc = desc.rstrip()
                desc = desc[:max(0, 5000 - len("\n\n" + bloque))].rstrip() + "\n\n" + bloque
            elif len(desc) > 5000:
                desc = desc[:5000]
        elif len(desc) > 5000:
            desc = desc[:5000]
        return replace(m, descripcion=desc)


def _config(config_path: Path | str) -> dict:
    ruta = Path(config_path)
    return tomllib.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


def _validar_claves(dir_secretos: Path) -> None:
    faltan = [n for n in _ARCHIVOS_CLAVE if not (dir_secretos / n).is_file()]
    if faltan:
        raise FileNotFoundError("Faltan archivos en secrets/: " + ", ".join(faltan))


def construir_orquestador(config_path: Path | str, directorio_datos: Path | str, modo: str = "real",
                          *, dir_secretos: Path | str | None = None, reloj=date.today) -> Ensamblado:
    if modo not in ("real", "dry-run"):
        raise ValueError("modo debe ser 'real' o 'dry-run'")
    cfg = _config(config_path)
    datos = Path(os.environ.get("CANAL_DATOS_DIR", directorio_datos))
    datos.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CANAL_ASSETS_DIR", str(_RAIZ / "assets" / "original" / "canal_youtube"))
    advertencias: list[str] = []
    if cfg.get("publish_public_enabled"):
        mensaje = "publish_public_enabled=true ignorado: la publicación pública está bloqueada en este modo."
        advertencias.append(mensaje)
        warnings.warn(mensaje, RuntimeWarning, stacklevel=2)

    tope = float(cfg.get("presupuesto_mensual_usd") or 70)
    ledger = Ledger(str(datos / "ledger.sqlite"), tope_mensual_usd=tope)
    cola = QueueStore(str(datos / "queue.sqlite"))
    notificador = Notificador(canal=CanalArchivo(datos / "alerts"), destino=cfg.get("email_alertas") or None)
    historial = Historial(ruta=datos / "historial.json")
    registro = RegistroTemas(ruta=datos / "temas.json")

    if modo == "dry-run":
        from canal.pipeline.falsos import (ControlCalidadFalso, GeneradorGuionFalso, GeneradorMetadatosFalso,
                                           GeneradorMiniaturaFalso, GeneradorTemaFalso, NarradorFalso,
                                           RenderizadorFalso, VerificadorFalso)
        etapas = SimpleNamespace(tema=GeneradorTemaFalso(), guion=GeneradorGuionFalso(), verificacion=VerificadorFalso(),
                                 narracion=NarradorFalso(.2), render=RenderizadorFalso(.3), qa=ControlCalidadFalso(),
                                 miniatura=GeneradorMiniaturaFalso(.1),
                                 generador_metadatos=GeneradorMetadatosConAviso(GeneradorMetadatosFalso()))
        cliente_base: Any = ClienteFalso()
    else:
        secretos = Path(dir_secretos) if dir_secretos else Path(os.environ.get("CANAL_SECRETS_DIR", _RAIZ / "secrets"))
        _validar_claves(secretos)
        from canal.director.planificador import PlanificadorEscenasLLM
        from canal.investigacion import ClienteWikipedia
        from canal.llm.gemini import ClienteGemini
        from canal.llm.generadores import (GeneradorGuionLLM, GeneradorMetadatosLLM, GeneradorTemaLLM, VerificadorLLM)
        from canal.miniatura.html import GeneradorMiniaturaHTML
        from canal.narracion.speko import ClienteSpeko, NarradorSpeko
        from canal.render.config import RenderConfig
        from canal.render.render_real import ControlCalidadReal, RenderizadorReal
        from canal.investigacion.imagenes import ClienteImagenes
        from canal.youtube.client import ClienteYouTubeReal

        llm = {"guion": "gemini-3-flash-preview", "verificacion": "gemini-3.5-flash", "metadatos": "gemini-3.1-flash-lite"}
        llm.update(cfg.get("llm", {}))
        nar = cfg.get("narracion", {})
        gemini = ClienteGemini(secretos / "gemini_api_key.txt", llm,
                              ruta_estado=datos / "gemini_uso.json")
        wiki = ClienteWikipedia()
        speko = ClienteSpeko(secretos / "speko_api_key.txt", voz=nar.get("voz", "HRUUrQrYM9LfgDbWoMXS"),
                             proveedor=nar.get("proveedor", "elevenlabs"),
                             modelo=nar.get("modelo", "eleven_v3_conversational"),
                             registrar_uso=lambda costo, *args: ledger.registrar_gasto("speko", costo))
        narrador = NarradorSpeko(speko, max_caracteres_por_video=nar.get("max_caracteres_largo", 20000))
        rcfg = RenderConfig(dir_trabajo=datos)
        etapas = SimpleNamespace(
            tema=GeneradorTemaLLM(gemini, wiki, registro), guion=GeneradorGuionLLM(gemini, wiki),
            verificacion=VerificadorLLM(gemini, wiki), narracion=narrador,
            render=RenderizadorReal(PlanificadorEscenasLLM(gemini), narrador=narrador, config=rcfg,
                                    cliente_imagenes=ClienteImagenes()),
            qa=ControlCalidadReal(config=rcfg), miniatura=GeneradorMiniaturaHTML(),
            generador_metadatos=GeneradorMetadatosConAviso(GeneradorMetadatosLLM(gemini)))
        cliente_base = ClienteYouTubeReal(dir_secretos=str(secretos))

    cliente = ClienteSeguro(cliente_base, publicacion_publica_habilitada=False)
    orq = Orquestador(cola, ledger, notificador, historial, registro, etapas, datos, cliente, reloj)
    return Ensamblado(orq, ledger, cola, cliente, advertencias)
