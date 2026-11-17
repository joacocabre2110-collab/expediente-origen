"""Registro persistente de gastos y límites mensuales."""

from __future__ import annotations

import math
import sqlite3
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class EstadoPresupuesto:
    gasto_mes: float
    tope: float | None
    porcentaje: float | None
    nivel: str


class Ledger:
    """Ledger SQLite de costos, con topes y alertas por mes calendario."""

    def __init__(self, db: str | sqlite3.Connection = ":memory:",
                 tope_mensual_usd: float | None = None,
                 reloj: Callable[[], datetime] = datetime.now) -> None:
        if tope_mensual_usd is not None:
            self._validar_monto(tope_mensual_usd)
            if tope_mensual_usd == 0:
                raise ValueError("El tope debe ser mayor que cero")
        self.tope_mensual_usd = tope_mensual_usd
        self.reloj = reloj
        self._lock = threading.RLock()
        self._external = db if isinstance(db, sqlite3.Connection) else None
        self._database = ":memory:" if self._external else str(db)
        self._uri = False
        self._keeper = None
        if self._external is None and self._database == ":memory:":
            self._database = f"file:budget-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._uri = True
            self._keeper = self._connect()
        self._init_schema()

    @staticmethod
    def _validar_monto(monto: float) -> None:
        if isinstance(monto, bool) or not isinstance(monto, (int, float)) or not math.isfinite(monto) or monto < 0:
            raise ValueError("El monto debe ser finito y no negativo")

    def _connect(self) -> sqlite3.Connection:
        if self._external is not None:
            return self._external
        conn = sqlite3.connect(self._database, uri=self._uri, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS gastos (id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, mes TEXT NOT NULL, servicio TEXT NOT NULL, monto REAL NOT NULL, video_key TEXT, nota TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS alertas (mes TEXT NOT NULL, nivel INTEGER NOT NULL, PRIMARY KEY(mes,nivel))")

    def _mes(self, mes: str | None = None) -> str:
        if mes is not None:
            return mes[:7]
        ahora = self.reloj()
        if not isinstance(ahora, datetime):
            raise TypeError("El reloj debe devolver datetime")
        return ahora.strftime("%Y-%m")

    def registrar_gasto(self, servicio: str, monto_usd: float, video_key: str | None = None, nota: str = "") -> None:
        self._validar_monto(monto_usd)
        ahora = self.reloj()
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO gastos(fecha,mes,servicio,monto,video_key,nota) VALUES(?,?,?,?,?,?)",
                         (ahora.isoformat(), ahora.strftime("%Y-%m"), str(servicio), monto_usd, video_key, str(nota)))

    def gasto_mes(self, mes: str | None = None) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(SUM(monto),0) FROM gastos WHERE mes=?", (self._mes(mes),)).fetchone()
        return float(row[0])

    def gasto_por_servicio(self, mes: str | None = None) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute("SELECT servicio,SUM(monto) FROM gastos WHERE mes=? GROUP BY servicio ORDER BY servicio", (self._mes(mes),)).fetchall()
        return {row[0]: float(row[1]) for row in rows}

    def costo_por_video(self, video_key: str) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(SUM(monto),0) FROM gastos WHERE video_key=?", (video_key,)).fetchone()
        return float(row[0])

    def estado(self) -> EstadoPresupuesto:
        gasto = self.gasto_mes()
        tope = self.tope_mensual_usd
        if tope is None:
            return EstadoPresupuesto(gasto, None, None, "sin_tope")
        porcentaje = gasto / tope * 100
        nivel = "pausa" if porcentaje >= 100 else "aviso" if porcentaje >= 80 else "ok"
        return EstadoPresupuesto(gasto, tope, porcentaje, nivel)

    def puede_producir(self, costo_estimado_usd: float = 0.0) -> bool:
        self._validar_monto(costo_estimado_usd)
        tope = self.tope_mensual_usd
        return tope is not None and self.gasto_mes() + costo_estimado_usd <= tope

    def aviso_pendiente(self) -> bool:
        estado = self.estado()
        if estado.tope is None:
            return False
        niveles = ([100] if estado.porcentaje >= 100 else [])
        if estado.porcentaje >= 80:
            niveles.insert(0, 80)
        mes = self._mes()
        with self._lock, self._connect() as conn:
            for nivel in niveles:
                cur = conn.execute("INSERT OR IGNORE INTO alertas(mes,nivel) VALUES(?,?)", (mes, nivel))
                if cur.rowcount:
                    return True
        return False
