"""Adaptadores reales del montaje y control de calidad del pipeline."""
from __future__ import annotations

from pathlib import Path
import subprocess

from canal.pipeline.etapas import Render, ResultadoQA
from . import montaje, calidad
from .config import RenderConfig
from .escenas import Escena

_ASSETS = Path(__import__("os").environ.get("CANAL_ASSETS_DIR", Path(__file__).resolve().parents[3] / "assets" / "original" / "canal_youtube"))


class RenderizadorReal:
    def __init__(self, planificador, *, narrador=None, config: RenderConfig | None = None,
                 montar_fn=None, ejecutor=None, ruta_musica=None, ruta_whoosh=None,
                 ruta_boom=None, ruta_sticker=None, imagenes=None, cliente_imagenes=None):
        self.planificador = planificador
        self.imagenes = imagenes
        self.cliente_imagenes = cliente_imagenes
        self.narrador = narrador
        self.config = config or RenderConfig()
        self.montar_fn = montar_fn or montaje.montar
        self.ejecutor = ejecutor or self.config.executor or subprocess
        self.ruta_musica = Path(ruta_musica or _ASSETS / "audio" / "musica" / "musica_ambiente_video_largo.mp3")
        efectos = self.config.ruta_efectos
        if efectos == Path("."):
            efectos = _ASSETS / "audio" / "efectos"
        self.ruta_whoosh = Path(ruta_whoosh or efectos / "whoosh.wav")
        self.ruta_boom = Path(ruta_boom or efectos / "boom.wav")
        self.ruta_sticker = Path(ruta_sticker or (_ASSETS / "imagenes" / "sticker.png" if self.config.ruta_sticker == Path("sticker.png") else self.config.ruta_sticker))

    def preparar_imagenes(self, contexto, tema, estado=None):
        """Recupera las imágenes guardadas o realiza una búsqueda tolerante a fallos."""
        from canal.investigacion.imagenes import ImagenLibre
        estado = estado or {}
        if "imagenes_disponibles" in estado:
            self.imagenes = [ImagenLibre(**i) for i in estado["imagenes_disponibles"]]
            return "reutilizadas" if self.imagenes else estado.get("imagenes_estado", "sin_imagenes")
        if self.imagenes is not None:
            return "reutilizadas"
        if not getattr(self, "cliente_imagenes", None):
            return "sin_configurar"
        import re
        titulo = re.sub(r"^Expediente\s+\d+\s*:\s*", "", tema.titulo, flags=re.IGNORECASE).strip()
        destino = Path(contexto.directorio_trabajo) / "imagenes"
        try:
            self.imagenes = self.cliente_imagenes.buscar_para_tema(titulo, tema.alias, destino, caso_id=tema.caso_id)
            return "disponibles" if self.imagenes else "sin_resultados"
        except Exception as exc:
            self.imagenes = []
            return f"error: {type(exc).__name__}: {exc}"

    def renderizar(self, contexto, tema, guion, narracion) -> Render:
        segmentos = (self.planificador.planificar(contexto, tema, guion, imagenes=self.imagenes)
                     if self.imagenes is not None else self.planificador.planificar(contexto, tema, guion))
        asignadas = {str(s.get("escena", {}).get("datos", {}).get("imagen")) for s in segmentos
                     if s.get("escena", {}).get("datos", {}).get("imagen")}
        self.imagenes_usadas = [img for img in (self.imagenes or []) if str(img.url_local) in asignadas]
        textos = [s["texto"] for s in segmentos]
        audios = None
        if self.narrador is not None and hasattr(self.narrador, "narrar_segmentos"):
            try:
                audios = self.narrador.narrar_segmentos(textos, Path(contexto.directorio_trabajo) / "speko_cache")
            except TypeError:
                audios = self.narrador.narrar_segmentos(textos)
        if not audios:
            audios = self._dividir_audio(Path(narracion.ruta_audio), segmentos, Path(contexto.directorio_trabajo))
        if len(audios) != len(segmentos):
            raise ValueError("la cantidad de audios no coincide con los segmentos")
        partes = []
        for i, (seg, audio) in enumerate(zip(segmentos, audios)):
            escena = seg["escena"]
            partes.append(montaje.Segmento(seg["texto"], Path(audio), Escena(
                escena["tipo"], escena["datos"], 1.0, seed=i, formato=contexto.tipo
            ), seg["impacto"]))
        plan = montaje.PlanVideo(contexto.tipo, partes, self.ruta_musica,
                                 self.ruta_whoosh, self.ruta_boom, self.ruta_sticker,
                                 tema.titulo[:120])
        salida = Path(contexto.directorio_trabajo) / f"{contexto.video_key}.mp4"
        ruta = self.montar_fn(plan, self.config, salida, ejecutor=self.ejecutor)
        return Render(Path(ruta), getattr(narracion, "costo_usd", 0.0))

    def _dividir_audio(self, audio: Path, segmentos: list[dict], trabajo: Path) -> list[Path]:
        """Fallback sin TTS segmentado: corta la narración por pesos de texto."""
        trabajo.mkdir(parents=True, exist_ok=True)
        raw = self.ejecutor.check_output([self.config.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)])
        dur = float(raw.decode() if isinstance(raw, bytes) else raw)
        pesos = [max(1, len(s["texto"].strip())) for s in segmentos]
        total = sum(pesos)
        rutas, inicio = [], 0.0
        for i, peso in enumerate(pesos):
            tramo = dur - inicio if i == len(pesos)-1 else dur * peso / total
            ruta = trabajo / f"{audio.stem}_segmento_{i:03d}{audio.suffix or '.mp3'}"
            self.ejecutor.run([self.config.ffmpeg, "-y", "-v", "error", "-ss", f"{inicio:.6f}", "-i", str(audio), "-t", f"{tramo:.6f}", "-c", "copy", str(ruta)], check=True)
            rutas.append(ruta)
            inicio += tramo
        return rutas


class ControlCalidadReal:
    def __init__(self, *, config: RenderConfig | None = None, ejecutor=None, verificar_fn=None):
        self.config = config or RenderConfig()
        self.ejecutor = ejecutor or self.config.executor
        self.verificar_fn = verificar_fn or calidad.verificar_salida

    def controlar(self, contexto, tema, guion, narracion, render) -> ResultadoQA:
        resultado = self.verificar_fn(render.ruta_video, contexto.tipo, ejecutor=self.ejecutor, cfg=self.config)
        # Traducir el QA del módulo render a la interfaz común de pipeline.
        if isinstance(resultado, ResultadoQA):
            return resultado
        return ResultadoQA(bool(resultado.correcto), list(resultado.motivos))
