"""Montaje genérico. Subtítulos y sticker se dibujan en HTML porque el ffmpeg
objetivo carece de libass, freetype y fontconfig; así ffmpeg solo concatena,
mezcla audio y codifica, sin ASS/drawtext ni filtros geq/overlay.
"""
import base64
from dataclasses import dataclass, replace
from functools import lru_cache
from html import escape
import json
import math
from pathlib import Path
import subprocess
import tempfile

from . import motor
from .config import RenderConfig
from .escenas import Escena, renderizar_cuerpo
from .shorts import chunks, ts


@dataclass(frozen=True)
class Segmento:
    texto: str
    ruta_audio: Path
    escena: Escena
    impacto: bool = False


@dataclass(frozen=True)
class PlanVideo:
    formato: str
    segmentos: list[Segmento]
    ruta_musica: Path
    ruta_whoosh: Path
    ruta_boom: Path
    ruta_sticker: Path
    titulo_interno: str

    def __post_init__(self):
        if self.formato not in ("short", "largo"):
            raise ValueError("formato debe ser short o largo")


@dataclass(frozen=True)
class Toma:
    segmento: Segmento
    duracion: float
    seed: int
    camara: str

    @property
    def escena(self):
        return replace(self.segmento.escena, duracion=self.duracion, seed=self.seed)


def _run(executor, args, **kwargs):
    return (executor or subprocess).run(args, **kwargs)


def _duracion(path, cfg, ejecutor):
    raw = (ejecutor or cfg.executor or subprocess).check_output([
        cfg.ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ])
    return float(raw.decode() if isinstance(raw, bytes) else raw)


def repartir_en_tomas(segmentos, max_toma=7.0, min_toma=3.0, *, cfg=None, ejecutor=None):
    """Divide audios largos en tomas de duración exacta con cámara/seed variados."""
    if max_toma <= 0 or min_toma <= 0 or min_toma > max_toma:
        raise ValueError("límites de toma inválidos")
    cfg = cfg or RenderConfig()
    tomas = []
    for idx, seg in enumerate(segmentos):
        dur = _duracion(seg.ruta_audio, cfg, ejecutor)
        if dur <= max_toma:
            ds = [dur]
        else:
            count = max(2, math.ceil(dur / max_toma))
            # Rebalancea para evitar un último fragmento menor que el mínimo.
            while count > 1 and dur / count < min_toma:
                count -= 1
            ds = [dur / count] * count
        offset = 0.0
        for j, d in enumerate(ds):
            seed = seg.escena.seed + idx * 1009 + j * 37
            tomas.append(Toma(seg, d, seed, ("push", "pull", "push")[j % 3]))
            offset += d
    return tomas


@lru_cache(maxsize=32)
def _sticker_data(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _eventos_subtitulos(plan, tomas, duraciones):
    """Genera eventos HTML por toma. Un chunk que cruza un corte queda en la toma donde empieza."""
    starts = []
    cursor = 0.0
    for d in duraciones:
        starts.append(cursor); cursor += d
    events = [[] for _ in tomas]
    segment_start = 0.0
    for seg in plan.segmentos:
        duration = sum(d for t, d in zip(tomas, duraciones) if t.segmento is seg)
        pieces = chunks(seg.texto, maxc=16) if plan.formato == "short" else [seg.texto]
        weight = max(1, sum(len(p) for p in pieces))
        at = segment_start
        for piece in pieces:
            span = duration * len(piece) / weight
            idx = next((i for i,(st,d) in enumerate(zip(starts,duraciones)) if st <= at < st+d), len(tomas)-1)
            events[idx].append((piece, at-starts[idx], min(span, starts[idx]+duraciones[idx]-at)))
            at += span
        segment_start += duration
    return events


def _capa_subtitulos(eventos, formato):
    if not eventos: return ""
    short = formato == "short"
    # Coordenadas en píxeles del lienzo, independientes de contenedores flex.
    top, height, font = (1191, 229, "900 96px") if short else (864, 129, "600 56px")
    style = (f"position:absolute;left:5%;right:5%;top:{top}px;height:{height}px;"
             f"font:{font} 'Inter',sans-serif;")
    css = "color:white;text-align:center;line-height:1.05;text-shadow:-3px -3px 0 #000,3px -3px 0 #000,-3px 3px 0 #000,3px 3px 0 #000,0 5px 8px #000;"
    spans = []
    for text, delay, duration in eventos:
        text = text.upper() if short else text
        spans.append(f'<div style="position:absolute;left:0;right:0;top:0;animation:subpop {max(.01,duration):.3f}s {delay:.3f}s both">{escape(text)}</div>')
    return "<style>@keyframes subpop{0%{opacity:0;transform:scale(.82)}4%{opacity:1;transform:scale(1.06)}10%,99%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(1)}}</style>" + f'<div data-layer="subtitulos" style="{style}{css}">' + "".join(spans) + "</div>"


def _capa_sticker(plan, sticker):
    short = plan.formato == "short"
    size = 150 if short else 230
    pos = "top:70px;left:50%;transform:translateX(-50%)" if short else "top:30px;right:34px"
    return f'<img data-layer="sticker" src="{sticker}" style="position:absolute;{pos};width:{size}px;height:{size}px;border:5px solid #ffb547;border-radius:50%;object-fit:cover;box-shadow:0 4px 18px #0008;z-index:10">'


def montar(plan: PlanVideo, cfg: RenderConfig, salida: Path, *, renderizador=motor.render_shots, ejecutor=None) -> Path:
    """Renderiza tomas, concatena, mezcla pistas, sticker y subtítulos.

    Subtítulos y sticker se renderizan como capas HTML separadas del contenido
    de escena animado; ffmpeg concatena tomas, mezcla y normaliza el audio.
    """
    executor = ejecutor or cfg.executor
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    work = salida.parent
    tomas = repartir_en_tomas(plan.segmentos, cfg=cfg, ejecutor=executor)
    w, h = ((1080, 1920) if plan.formato == "short" else (1920, 1080))
    durations = [t.duracion for t in tomas]
    sticker = _sticker_data(str(plan.ruta_sticker))
    events = _eventos_subtitulos(plan, tomas, durations)
    shots = [(renderizar_cuerpo(replace(t.escena, formato=plan.formato)) +
              '<div data-layer="overlays" style="position:absolute;inset:0;pointer-events:none">' +
              _capa_subtitulos(events[i], plan.formato) + _capa_sticker(plan, sticker) + '</div>', t.duracion)
             for i, t in enumerate(tomas)]
    prefijo = str(work / (salida.stem + "_toma"))
    clips = renderizador(shots, w, h, prefijo, cfg)
    concat = work / (salida.stem + "_concat.txt")
    concat.write_text("\n".join("file '" + str(Path(c).resolve()).replace("'", "'\\''") + "'" for c in clips), encoding="utf-8")
    video = work / (salida.stem + "_video.mp4")
    _run(executor, [cfg.ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(video)], check=True)
    total = sum(durations)
    inputs = ["-i", str(video)]
    for s in plan.segmentos: inputs += ["-i", str(s.ruta_audio)]
    music_idx = 1 + len(plan.segmentos); inputs += ["-stream_loop", "-1", "-i", str(plan.ruta_musica)]
    whoosh_idx = music_idx + 1; inputs += ["-i", str(plan.ruta_whoosh)]
    impacts = [i for i, s in enumerate(plan.segmentos) if s.impacto]
    boom_indices = []
    for _ in impacts:
        boom_indices.append(whoosh_idx + 1 + len(boom_indices)); inputs += ["-i", str(plan.ruta_boom)]
    filters = []
    narration_labels = []
    cursor = 0.0
    for i, (seg, dur) in enumerate(zip(plan.segmentos, [_duracion(s.ruta_audio, cfg, executor) for s in plan.segmentos])):
        label = f"n{i}"; narration_labels.append(f"[{label}]")
        delay = int(cursor * 1000)
        filters.append(f"[{1+i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}|{delay},apad=pad_dur={max(0,total-cursor-dur):.3f}[{label}]")
        cursor += dur
    filters.append("".join(narration_labels) + f"amix=inputs={len(narration_labels)}:normalize=0:duration=longest,asplit=2[narr_sc][narr_mix]")
    filters.append(f"[{music_idx}:a]volume=0.12,atrim=duration={total:.3f}[mus]")
    fx_labels = []
    cut_time = 0.0
    # whoosh per cut, including boundaries between split shots of the same sentence.
    for i, d in enumerate(durations[:-1]):
        cut_time += d
        label = f"w{i}"; fx_labels.append(f"[{label}]")
        delay = max(0, int((cut_time - .15) * 1000))
        filters.append(f"[{whoosh_idx}:a]adelay={delay}|{delay},volume=.55[{label}]")
    seg_starts=[]; at=0.0
    for seg in plan.segmentos: seg_starts.append(at); at += _duracion(seg.ruta_audio, cfg, executor)
    for j, i in enumerate(impacts):
        label=f"b{j}"; fx_labels.append(f"[{label}]"); delay=int(seg_starts[i]*1000)
        filters.append(f"[{boom_indices[j]}:a]adelay={delay}|{delay},volume=.8[{label}]")
    filters.append("[mus][narr_sc]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=250[mduck]")
    labels = "[narr_mix][mduck]" + "".join(fx_labels)
    # loudnorm fija sonoridad integrada y pico verdadero en la mezcla final.
    filters.append(labels + f"amix=inputs={2+len(fx_labels)}:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    outdur = max(total, .1)
    bitrate = max(180, int((9.0 * 8 * 1000) / outdur - 128)) if plan.formato == "short" and outdur <= 60 else 4000
    args = [cfg.ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-b:v", f"{bitrate}k", "-c:a", "aac", "-b:a", "128k"]
    if plan.formato == "short" and outdur <= 60:
        args += ["-maxrate", f"{bitrate}k", "-bufsize", f"{bitrate*2}k"]
    args += ["-t", f"{outdur:.3f}", "-movflags", "+faststart", str(salida)]
    _run(executor, args, check=True)
    return salida
