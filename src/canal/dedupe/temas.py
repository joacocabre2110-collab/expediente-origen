"""Control de repetición de temas con alias y persistencia opcional.

El banco de temas debe asignar un caso_id canónico a cada tema antes de producir.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping

def siguiente_numero_expediente(historial: Iterable[Any]) -> int:
    """Siguiente folio consecutivo a partir de títulos/ids del historial."""
    numeros = []
    for tema in historial:
        texto = " ".join(str(_campo(tema, k, "")) for k in ("tema_canonico", "titulo", "caso_id"))
        numeros.extend(int(x) for x in re.findall(r"(?i)expediente\s*#?\s*(\d+)", texto))
    return max(numeros, default=0) + 1

_STOP = set("a al algo algunas algunos ante antes como con contra cual cuando de del desde donde durante e el ella ellas ellos en entre era erais eran eras eres es esa esas ese eso esos esta estaba estaban estado estamos estan estar estas este esto estos fue fueron ha habeis habia han hasta hay la las le les lo los mas me mi mis mucho muy nada ni no nos o os otra otras otro otros para pero poco por porque que quien se sea ser si sin sobre son su sus te tiene todo tu tus un una unas uno unos y ya".split())


def normalizar_tema(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto).lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(p for p in re.findall(r"[a-z0-9]+", texto) if p not in _STOP)


def _tokens(s: str) -> set[str]:
    return set(normalizar_tema(s).split())


def _coincide(a: str, b: str, umbral: float = 0.6) -> bool:
    if a == b:
        return True
    ta, tb = _tokens(a), _tokens(b)
    union = ta | tb
    return bool(union) and len(ta & tb) / len(union) >= umbral


def _campo(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


@dataclass
class TemaRegistrado:
    tema_canonico: str
    alias: list[str] = field(default_factory=list)
    pilar: str = ""
    fecha: str = ""
    video_key: str = ""
    video_origen: str = ""
    caso_id: str = ""


@dataclass
class ResultadoTema:
    aprobado: bool
    motivos: list[str]
    coincidencia: Any = None


class RegistroTemas:
    def __init__(self, temas: Iterable[Any] = (), *, ruta: str | Path | None = None):
        self.ruta = Path(ruta) if ruta is not None else None
        if self.ruta is not None and self.ruta.exists():
            temas = json.loads(self.ruta.read_text(encoding="utf-8"))
        self.temas = [t if isinstance(t, TemaRegistrado) else TemaRegistrado(**t) for t in temas]

    def agregar(self, tema_canonico: str, alias: Iterable[str] | None = None, pilar: str = "",
                fecha: Any = None, video_key: str = "", video_origen: str = "",
                caso_id: str = "", **kwargs: Any) -> TemaRegistrado:
        fecha = fecha or datetime.now().date().isoformat()
        item = TemaRegistrado(str(tema_canonico), list(alias or []), pilar,
                              fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha),
                              video_key, video_origen, caso_id)
        self.temas.append(item)
        self._guardar()
        return item

    append = agregar

    def _guardar(self) -> None:
        if self.ruta is None:
            return
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_name(self.ruta.name + ".tmp")
        temporal.write_text(json.dumps([asdict(t) for t in self.temas], ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(self.ruta)

    def __iter__(self):
        return iter(self.temas)

    def __len__(self):
        return len(self.temas)


def _fecha(valor: Any) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def tema_repetido(candidato_tema: str, candidato_alias: Iterable[str] | None,
                  registro: RegistroTemas | Iterable[Any], *, cooldown_dias: int = 180,
                  ahora: Any = None, angulo_nuevo: bool = False,
                  cooldown_minimo_angulo_dias: int = 30,
                  video_origen: str = "", video_key: str = "",
                  caso_id: str = "") -> ResultadoTema:
    ahora_fecha = _fecha(ahora or date.today())
    candidatos = [str(candidato_tema), *(candidato_alias or [])]
    candidatos_norm = [normalizar_tema(x) for x in candidatos if normalizar_tema(x)]
    motivos: list[str] = []
    for previo in registro:
        # Un derivado corto del mismo largo pertenece a la misma publicación.
        origen = video_origen or _campo(candidato_tema, "video_origen", "")
        previo_key = _campo(previo, "video_key", "")
        previo_origen = _campo(previo, "video_origen", "")
        if origen and (origen == previo_key or origen == previo_origen):
            continue
        if video_key and previo_origen == video_key:
            continue
        coincide = bool(caso_id and caso_id == _campo(previo, "caso_id", ""))
        previos = [str(_campo(previo, "tema_canonico", "")), *(_campo(previo, "alias", []) or [])]
        previos_norm = [normalizar_tema(x) for x in previos if normalizar_tema(x)]
        if not coincide and not any(_coincide(a, b) for a in candidatos_norm for b in previos_norm):
            continue
        try:
            dias = (ahora_fecha - _fecha(_campo(previo, "fecha"))).days
        except (ValueError, TypeError):
            dias = 0
        if dias > cooldown_dias:
            motivos.append("tema_reusable_con_nuevo_angulo")
            continue
        if angulo_nuevo and dias >= cooldown_minimo_angulo_dias:
            motivos.append("angulo_nuevo")
            continue
        return ResultadoTema(False, ["tema_repetido"], previo)
    return ResultadoTema(True, motivos, None)
