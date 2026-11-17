"""Control de cuota de API y planificación de publicaciones."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as hora, timedelta, timezone
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

CUOTA_DIARIA = 10_000
COSTO_SUBIDA = 1_600
COSTO_MINIATURA = 50
COSTO_LECTURA = 1
ZONA_CUOTA = ZoneInfo("America/Los_Angeles")
ZONA_PUBLICACION = ZoneInfo("America/Argentina/Buenos_Aires")


def _ahora(reloj: Callable[[], object]) -> datetime:
    valor = reloj()
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(valor), timezone.utc)


class CuotaDiaria:
    def __init__(self, db: str | sqlite3.Connection = ":memory:", reloj: Callable[[], object] = time.time,
                 *, cuota_diaria: int = CUOTA_DIARIA) -> None:
        self.reloj = reloj
        self.cuota_diaria = cuota_diaria
        self._db = db if isinstance(db, sqlite3.Connection) else sqlite3.connect(db, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS cuota_operaciones (id INTEGER PRIMARY KEY, dia TEXT NOT NULL, operacion TEXT NOT NULL, unidades INTEGER NOT NULL)")
        self._db.commit()

    def _dia(self, dia: date | str | None) -> str:
        if dia is None:
            return _ahora(self.reloj).astimezone(ZONA_CUOTA).date().isoformat()
        return dia.isoformat() if isinstance(dia, date) else str(dia)

    def registrar(self, operacion: str, unidades: int) -> None:
        if unidades < 0:
            raise ValueError("unidades debe ser >= 0")
        with self._db:
            self._db.execute("INSERT INTO cuota_operaciones(dia,operacion,unidades) VALUES(?,?,?)", (self._dia(None), operacion, unidades))

    def usadas(self, dia: date | str | None = None) -> int:
        row = self._db.execute("SELECT COALESCE(SUM(unidades),0) FROM cuota_operaciones WHERE dia=?", (self._dia(dia),)).fetchone()
        return int(row[0])

    def disponibles(self, dia: date | str | None = None) -> int:
        return max(0, self.cuota_diaria - self.usadas(dia))

    def puede(self, unidades: int) -> bool:
        return unidades >= 0 and self.disponibles() >= unidades


@dataclass(frozen=True)
class Video:
    video_key: str
    tipo: str = "largo"

    def __post_init__(self) -> None:
        if self.tipo not in ("largo", "short"):
            raise ValueError("tipo debe ser 'largo' o 'short'")


@dataclass(frozen=True)
class Publicacion:
    video_key: str
    fecha_publicacion: datetime
    dia_de_subida: date


@dataclass
class Plan:
    publicaciones: list[Publicacion] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def videos(self) -> list[Publicacion]:
        return self.publicaciones

    def __iter__(self):
        return iter(self.publicaciones)


def planificar_subidas(videos: list[Video], desde: date, reserva_dias: tuple[int, int] = (5, 7),
                       margen_unidades: int = 1500, *,
                       hora_largo: hora | str = hora(18),
                       horas_shorts: tuple[hora | str, ...] = (hora(12), hora(18), hora(21)),
                       zona: ZoneInfo = ZONA_PUBLICACION,
                       ahora: datetime | None = None,
                       cuota: CuotaDiaria | None = None) -> Plan:
    """Programa publicaciones y reserva cuota de subida de forma independiente."""
    minimo, maximo = reserva_dias
    if minimo < 0 or maximo < minimo:
        raise ValueError("reserva_dias debe ser un rango válido")
    if margen_unidades < 0 or margen_unidades >= CUOTA_DIARIA:
        raise ValueError("margen_unidades inválido")
    def parse_hora(v: hora | str) -> hora:
        return hora.fromisoformat(v) if isinstance(v, str) else v
    hl = parse_hora(hora_largo)
    hs = tuple(parse_hora(v) for v in horas_shorts)
    ahora = (ahora or datetime.now(zona)).astimezone(zona)
    hoy = ahora.date()
    primer_dia = max(desde, hoy)
    largos = [v for v in videos if v.tipo == "largo"]
    shorts = [v for v in videos if v.tipo == "short"]
    plan = Plan(avisos=[f"Tipo desconocido para {v.video_key}" for v in videos if v.tipo not in ("largo", "short")])
    limite = primer_dia + timedelta(days=maximo)
    subidas: dict[date, int] = {}
    for d in _dias(primer_dia, limite):
        if cuota is not None:
            subidas[d] = cuota.usadas(d)
    costo_video = COSTO_SUBIDA + COSTO_MINIATURA
    tope = CUOTA_DIARIA - margen_unidades
    for dia_pub in _dias(primer_dia, limite):
        lote = ([(largos[0], hl)] if largos else []) + [(v, hs[i % len(hs)]) for i, v in enumerate(shorts[:3])]
        for v, hora_pub in lote:
            publicacion = datetime.combine(dia_pub, hora_pub, tzinfo=zona)
            if publicacion <= ahora:
                plan.avisos.append(f"{v.video_key}: publicación pasada; se difiere")
                continue
            dia_subida = primer_dia
            while dia_subida <= dia_pub and subidas.get(dia_subida, 0) + costo_video > tope:
                dia_subida += timedelta(days=1)
            if dia_subida > dia_pub:
                plan.avisos.append(f"{v.video_key}: capacidad insuficiente antes de publicación; se difiere")
                continue
            subidas[dia_subida] = subidas.get(dia_subida, 0) + costo_video
            plan.publicaciones.append(Publicacion(v.video_key, publicacion, dia_subida))
            if v.tipo == "largo":
                largos.remove(v)
            else:
                shorts.remove(v)
    if largos or shorts:
        plan.avisos.append(f"Quedaron {len(largos) + len(shorts)} videos fuera de la reserva de {maximo} días")
    return plan


def _dias(inicio: date, fin: date):
    for n in range((fin - inicio).days + 1):
        yield inicio + timedelta(days=n)


def dias_de_reserva(publicaciones: Iterable[Publicacion], hoy: date) -> int:
    por_dia: dict[date, list[str]] = {}
    for p in publicaciones:
        d = p.fecha_publicacion.date()
        por_dia.setdefault(d, []).append(p.video_key)
    d = hoy + timedelta(days=1)
    cantidad = 0
    while True:
        claves = por_dia.get(d, [])
        if len(claves) != 4:
            break
        cantidad += 1
        d += timedelta(days=1)
    return cantidad


def necesita_reponer(publicaciones: Iterable[Publicacion], hoy: date, minimo: int = 5) -> bool:
    return dias_de_reserva(publicaciones, hoy) < minimo
