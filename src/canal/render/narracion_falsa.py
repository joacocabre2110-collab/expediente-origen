"""Generación local de WAV de prueba, sin llamadas a servicios externos."""
from pathlib import Path
import math
import wave


def narrar_falso(texto: str, ruta: Path, *, caracteres_por_segundo: float = 15.0) -> Path:
    """Escribe silencio WAV PCM cuya duración depende de la longitud del texto."""
    if caracteres_por_segundo <= 0:
        raise ValueError("caracteres_por_segundo debe ser positivo")
    duracion = max(0.1, len(texto) / caracteres_por_segundo)
    sample_rate = 8000
    frames = int(round(duracion * sample_rate))
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * frames)
    return ruta
