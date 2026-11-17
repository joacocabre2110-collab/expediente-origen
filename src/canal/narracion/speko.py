"""Narración por Speko Router: POST https://router.speko.dev/v1/tts/speech.

Campos documentados en ``docs_externas/speko_llms_full.txt``, sección
``# Synthesize speech (/relay/tts/speech)``: ``routing`` con ``mode``,
``provider`` y ``model``; ``input``; ``voice``; y ``audio.encoding``.
La respuesta es audio binario y anuncia formato en Content-Type y
X-Speko-Audio-Format.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from canal.pipeline.etapas import Narracion


class ErrorSpeko(RuntimeError):
    """Error de solicitud o respuesta Speko, sin datos sensibles."""


def dividir_guion(texto: str, limite: int = 4500) -> list[str]:
    """Agrupa oraciones hasta el límite; corta por palabras si una oración lo excede."""
    if limite <= 0 or limite > 5000:
        raise ValueError("limite debe estar entre 1 y 5000")
    oraciones = [s.strip() for s in re.findall(r".*?(?:[.!?…]+(?:[\"'”’)]*)?(?=\s|$)|$)", texto, re.S) if s.strip()]
    partes: list[str] = []
    actual = ""
    for oracion in oraciones:
        palabras = oracion.split()
        trozos: list[str] = []
        trozo = ""
        for palabra in palabras:
            if len(palabra) > limite:
                if trozo: trozos.append(trozo); trozo = ""
                trozos.extend(palabra[i:i+limite] for i in range(0, len(palabra), limite))
            elif not trozo or len(trozo) + 1 + len(palabra) <= limite:
                trozo = f"{trozo} {palabra}".strip()
            else:
                trozos.append(trozo); trozo = palabra
        if trozo: trozos.append(trozo)
        for t in trozos:
            if actual and len(actual) + 1 + len(t) <= limite:
                actual += " " + t
            else:
                if actual: partes.append(actual)
                actual = t
    if actual: partes.append(actual)
    return partes


class ClienteSpeko:
    URL = "https://router.speko.dev/v1/tts/speech"

    def __init__(self, clave_path, voz="HRUUrQrYM9LfgDbWoMXS", proveedor="elevenlabs",
                 modelo="eleven_v3_conversational", abrir=urllib.request.urlopen,
                 sleep=time.sleep, reintentos=4, registrar_uso=None,
                 pausa_min_s=0.0) -> None:
        if reintentos < 0 or pausa_min_s < 0:
            raise ValueError("reintentos y pausa_min_s deben ser no negativos")
        self.clave_path, self.voz, self.proveedor, self.modelo = Path(clave_path), voz, proveedor, modelo
        self.abrir, self.sleep, self.reintentos = abrir, sleep, reintentos
        self.registrar_uso, self.pausa_min_s = registrar_uso, pausa_min_s
        self._ultima: float | None = None
        self.ultima_cache = False

    def sintetizar(self, texto: str, directorio: Path) -> Path:
        digest = hashlib.sha256((texto + "\0" + self.voz).encode("utf-8")).hexdigest()
        directorio.mkdir(parents=True, exist_ok=True)
        # Extensión identificada por headers; cache indexado por texto+voz.
        marker = directorio / f"{digest}.meta"
        if marker.is_file():
            try:
                nombre = marker.read_text(encoding="utf-8").strip()
                cached = directorio / nombre
                if cached.is_file() and cached.stat().st_size:
                    self.ultima_cache = True
                    return cached
            except OSError:
                pass
        try:
            clave = self.clave_path.read_text(encoding="utf-8").strip()
        except OSError:
            raise ErrorSpeko("No se pudo leer la clave de Speko") from None
        if not clave:
            raise ErrorSpeko("El archivo de clave de Speko está vacío")
        body = json.dumps({"routing": {"mode": "explicit", "provider": self.proveedor, "model": self.modelo},
                           "input": texto, "voice": self.voz,
                           "audio": {"encoding": "pcm_s16le", "sample_rate_hz": 24000, "channels": 1}}).encode()
        self.ultima_cache = False
        req = urllib.request.Request(self.URL, data=body, headers={
            "Authorization": f"Bearer {clave}", "Idempotency-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, digest)),
            "Content-Type": "application/json", "Accept": "audio/*, application/octet-stream"}, method="POST")
        for intento in range(self.reintentos + 1):
            if self._ultima is not None and self.pausa_min_s:
                self.sleep(self.pausa_min_s)
            self._ultima = time.monotonic()
            try:
                with self.abrir(req, timeout=60) as response:
                    data = response.read()
                    headers = response.headers
                ctype = str(headers.get("X-Speko-Audio-Format") or headers.get("Content-Type") or "").lower()
                if not data or not (ctype.startswith("audio/") or "application/octet-stream" in ctype):
                    raise ErrorSpeko("Speko devolvió una respuesta que no es audio")
                if "mpeg" in ctype or "mp3" in ctype:
                    ext = ".mp3"
                elif "wav" in ctype and data[:4] == b"RIFF":
                    ext = ".wav"
                else:  # PCM crudo (pcm_s16le, mono, 24 kHz): se envuelve en WAV
                    ext = ".wav"
                    import io, wave
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                        w.writeframes(data)
                    data = buf.getvalue()
                destino = directorio / f"{digest}{ext}"
                destino.write_bytes(data)
                marker.write_text(destino.name, encoding="utf-8")
                return destino
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or intento >= self.reintentos:
                    raise ErrorSpeko(f"Error HTTP de Speko ({exc.code})") from None
                self.sleep(2 ** intento)
            except (TimeoutError, urllib.error.URLError) as exc:
                if isinstance(exc, urllib.error.URLError) and not isinstance(exc.reason, TimeoutError):
                    raise ErrorSpeko("No se pudo conectar con Speko") from None
                if intento >= self.reintentos:
                    raise ErrorSpeko("Speko agotó los reintentos por timeout") from None
                self.sleep(2 ** intento)
        raise ErrorSpeko("Speko agotó los reintentos")


class NarradorSpeko:
    def __init__(self, cliente: ClienteSpeko, *, ffmpeg="ffmpeg", ffprobe="ffprobe",
                 ejecutor=None, max_caracteres_por_video=None) -> None:
        self.cliente, self.ffmpeg, self.ffprobe = cliente, ffmpeg, ffprobe
        self.ejecutor = ejecutor or subprocess
        self.max_caracteres_por_video = max_caracteres_por_video

    def narrar(self, contexto, tema, guion, verificacion) -> Narracion:
        texto = guion.texto.strip()
        limite = self.max_caracteres_por_video or (3000 if contexto.tipo == "short" else 20000)
        if len(texto) > limite:
            raise ErrorSpeko(f"El guion excede el máximo de {limite} caracteres")
        partes = dividir_guion(texto)
        trabajo = Path(contexto.directorio_trabajo)
        cache = trabajo / "speko_cache"
        rutas = []
        nuevas = []
        for parte in partes:
            rutas.append(self.cliente.sintetizar(parte, cache))
            if not self.cliente.ultima_cache:
                nuevas.append(rutas[-1])
        trabajo.mkdir(parents=True, exist_ok=True)
        salida = trabajo / f"{contexto.video_key}_narracion.mp3"
        concat = trabajo / f"{contexto.video_key}_speko_concat.txt"
        concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in rutas), encoding="utf-8")
        self.ejecutor.run([self.ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:a", "libmp3lame", str(salida)], check=True)
        raw = self.ejecutor.check_output([self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(salida)])
        duracion = float(raw.decode() if isinstance(raw, bytes) else raw)
        duracion_nueva = 0.0
        for ruta in nuevas:
            raw_fragmento = self.ejecutor.check_output([self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)])
            duracion_nueva += float(raw_fragmento.decode() if isinstance(raw_fragmento, bytes) else raw_fragmento)
        costo = duracion_nueva / 60 * 0.045
        if self.cliente.registrar_uso:
            self.cliente.registrar_uso(costo)
        return Narracion(salida, costo, duracion)

    def narrar_segmentos(self, textos, directorio: Path | str | None = None) -> list[Path]:
        """Sintetiza cada segmento por separado usando la caché texto+voz existente."""
        if not isinstance(textos, (list, tuple)) or any(not isinstance(t, str) or not t.strip() for t in textos):
            raise ValueError("textos debe ser una lista de textos no vacíos")
        cache = Path(directorio) if directorio is not None else Path("speko_cache")
        rutas = []
        nuevas = []
        for texto in textos:
            ruta = self.cliente.sintetizar(texto.strip(), cache)
            rutas.append(ruta)
            if not self.cliente.ultima_cache:
                nuevas.append(ruta)
        costo = 0.0
        for ruta in nuevas:
            raw = self.ejecutor.check_output([self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)])
            costo += float(raw.decode() if isinstance(raw, bytes) else raw) / 60 * .045
        if costo and self.cliente.registrar_uso:
            self.cliente.registrar_uso(costo)
        return rutas
