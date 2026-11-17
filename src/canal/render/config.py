"""Configuración explícita para los procesos de render."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RenderConfig:
    dir_trabajo: Path | str = Path(".")
    ruta_sticker: Path | str = Path("sticker.png")
    ruta_musica: Path | str = Path("musica.wav")
    ruta_efectos: Path | str = Path(".")
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    fps: int = 30
    executor: Any = None

    def __post_init__(self):
        object.__setattr__(self, "dir_trabajo", Path(self.dir_trabajo))
        object.__setattr__(self, "ruta_sticker", Path(self.ruta_sticker))
        object.__setattr__(self, "ruta_musica", Path(self.ruta_musica))
        object.__setattr__(self, "ruta_efectos", Path(self.ruta_efectos))

