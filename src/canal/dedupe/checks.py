"""Comparación de guiones y control de repetición narrativa."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


def _normalizar(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", texto)


def _ngrams(texto: str, n: int = 3) -> set[tuple[str, ...]]:
    palabras = _normalizar(texto)
    if len(palabras) < n:
        return {tuple(palabras)} if palabras else set()
    return {tuple(palabras[i:i + n]) for i in range(len(palabras) - n + 1)}


def similitud(a: str, b: str) -> float:
    """Jaccard de trigramas de palabras, tras normalizar acentos y puntuación."""
    na, nb = _ngrams(a), _ngrams(b)
    if not na and not nb:
        return 1.0
    return len(na & nb) / len(na | nb)


@dataclass
class Guion:
    video_key: str
    pilar: str
    estructura: str
    gancho: str
    intro: str
    texto: str


@dataclass
class Resultado:
    aprobado: bool
    motivos: list[str]


def _campo(item: Any, nombre: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(nombre, default)
    return getattr(item, nombre, default)


class Historial:
    """Historial acotado; opcionalmente lo guarda en un archivo JSON."""

    def __init__(self, guiones: Iterable[Any] = (), *, max_items: int = 60,
                 ruta: str | Path | None = None):
        if max_items < 1:
            raise ValueError("max_items debe ser positivo")
        self.max_items = max_items
        self.ruta = Path(ruta) if ruta is not None else None
        if self.ruta is not None and self.ruta.exists():
            data = json.loads(self.ruta.read_text(encoding="utf-8"))
            guiones = data
        self._guiones = list(guiones)[-max_items:]

    def agregar(self, guion: Any) -> None:
        self._guiones.append(guion)
        self._guiones = self._guiones[-self.max_items:]
        if self.ruta is not None:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            datos = [asdict(g) if hasattr(g, "__dataclass_fields__") else dict(g)
                     for g in self._guiones]
            self.ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    append = agregar

    def __iter__(self) -> Iterator[Any]:
        return iter(self._guiones)

    def __len__(self) -> int:
        return len(self._guiones)


def evaluar(candidato: Any, historial: Iterable[Any], *, umbral_similitud: float = 0.35,
            max_mismo_pilar_seguidos: int = 2, min_estructuras: int = 6) -> Resultado:
    anteriores = list(historial)
    motivos: list[str] = []
    texto = str(_campo(candidato, "texto"))
    for anterior in anteriores[-60:]:
        if similitud(texto, str(_campo(anterior, "texto"))) >= umbral_similitud:
            motivos.append("texto_similar")
            break
    for campo, label in (("gancho", "gancho_repetido"), ("intro", "intro_repetida")):
        valor = str(_campo(candidato, campo))
        if any(similitud(valor, str(_campo(previo, campo))) >= 0.6 for previo in anteriores):
            motivos.append(label)
    pilar = _campo(candidato, "pilar")
    seguidos = 0
    for previo in reversed(anteriores):
        if _campo(previo, "pilar") != pilar:
            break
        seguidos += 1
    if pilar and seguidos >= max_mismo_pilar_seguidos:
        motivos.append("pilar_repetido")
    ventana = max(0, min_estructuras - 1)
    estructura = _campo(candidato, "estructura")
    if ventana and any(_campo(previo, "estructura") == estructura for previo in anteriores[-ventana:]):
        motivos.append("estructura_repetida")
    return Resultado(not motivos, motivos)


def proxima_estructura(historial: Iterable[Any], estructuras_disponibles: Iterable[str]) -> str:
    """Elige la estructura menos usada recientemente; desempata por orden recibido."""
    opciones = list(estructuras_disponibles)
    if not opciones:
        raise ValueError("Se requiere al menos una estructura disponible")
    anteriores = list(historial)
    resultado: list[tuple[int, int, str]] = []
    for orden, estructura in enumerate(opciones):
        indices = [i for i, item in enumerate(anteriores)
                   if _campo(item, "estructura") == estructura]
        resultado.append((len(indices), indices[-1] if indices else -1, orden, estructura))
    return min(resultado)[-1]
