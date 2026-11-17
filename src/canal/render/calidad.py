"""Validación de entregables de vídeo con ffprobe y análisis de sonoridad."""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from .config import RenderConfig


@dataclass(frozen=True)
class ResultadoQA:
    correcto: bool
    motivos: tuple[str, ...]
    duracion: float | None = None
    ancho: int | None = None
    alto: int | None = None
    fps: float | None = None
    tamano: int | None = None
    lufs: float | None = None


def _run(ejecutor, args, **kwargs):
    return (ejecutor or subprocess).run(args, **kwargs)


def verificar_salida(ruta, formato, *, ejecutor=None, duracion_minima_larga=60.0,
                     objetivo_lufs=-16.0, tolerancia_lufs=3.0, cfg=None) -> ResultadoQA:
    cfg = cfg or RenderConfig()
    ruta = Path(ruta)
    motivos = []
    try:
        p = _run(ejecutor or cfg.executor, [cfg.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(ruta)], capture_output=True, text=True, check=True)
        raw = p.stdout
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        streams = data.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video")
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        w, h = int(video["width"]), int(video["height"])
        fps_s = video.get("avg_frame_rate", video.get("r_frame_rate", "0/1"))
        a, b = fps_s.split("/"); fps = float(a) / float(b)
        dur = float(data.get("format", {}).get("duration", video.get("duration", 0)))
        size = int(data.get("format", {}).get("size", ruta.stat().st_size if ruta.exists() else 0))
    except Exception as exc:
        return ResultadoQA(False, (f"No se pudo inspeccionar el archivo con ffprobe: {exc}",))
    target = (1080, 1920) if formato == "short" else (1920, 1080)
    if (w, h) != target: motivos.append(f"Resolución incorrecta: {w}x{h}; se esperaba {target[0]}x{target[1]}.")
    if abs(fps - 30) > .5: motivos.append(f"FPS incorrectos: {fps:.2f}; se esperaba aproximadamente 30.")
    if video.get("codec_name") != "h264": motivos.append(f"Códec de vídeo incorrecto: {video.get('codec_name', 'desconocido')}; se esperaba h264.")
    if audio is None: motivos.append("El archivo no contiene audio.")
    if formato == "short":
        if not 15 <= dur <= 60: motivos.append(f"Duración de short fuera de rango: {dur:.2f} s (15–60 s).")
        if size >= 10_000_000: motivos.append(f"El short supera el límite de 10 MB ({size} bytes).")
    elif dur < duracion_minima_larga:
        motivos.append(f"Duración de video largo insuficiente: {dur:.2f} s; mínimo {duracion_minima_larga:.2f} s.")
    lufs = None
    if audio:
        try:
            p = _run(ejecutor or cfg.executor, [cfg.ffmpeg, "-hide_banner", "-i", str(ruta), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=False)
            stderr = getattr(p, "stderr", "") or ""
            if isinstance(stderr, bytes): stderr = stderr.decode(errors="replace")
            start = stderr.rfind("{")
            if start >= 0:
                lufs = float(json.loads(stderr[start:stderr.rfind("}")+1]).get("input_i"))
                if abs(lufs - objetivo_lufs) > tolerancia_lufs:
                    motivos.append(f"Sonoridad fuera de objetivo: {lufs:.1f} LUFS; objetivo {objetivo_lufs:.1f} ±{tolerancia_lufs:.1f}.")
        except Exception:
            motivos.append("No se pudo medir la sonoridad con ffmpeg loudnorm.")
    return ResultadoQA(not motivos, tuple(motivos), dur, w, h, fps, size, lufs)
