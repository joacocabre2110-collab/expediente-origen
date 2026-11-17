"""Cola persistente de etapas de publicación."""

from __future__ import annotations

import sqlite3
import time
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

ETAPAS = ("tema", "guion", "verificacion", "narracion", "render", "qa", "miniatura", "subida", "verificacion_post")
ESTADOS = ("pendiente", "en_curso", "hecho", "fallido", "apartado")


def _fecha(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


@dataclass(frozen=True)
class Tarea:
    id: int
    video_key: str
    etapa: str
    estado: str
    intentos: int
    max_intentos: int
    proxima_ejecucion: float
    ultimo_error: str | None


class QueueStore:
    """Almacena, reclama y completa etapas usando SQLite."""

    def __init__(self, database: str = ":memory:", *, reloj: Callable[[], float] = time.time,
                 base_backoff: float = 1.0, tope_backoff: float = 3600.0,
                 timeout_abandono: float = 300.0) -> None:
        self.database = database
        self.reloj = reloj
        self.base_backoff = base_backoff
        self.tope_backoff = tope_backoff
        self.timeout_abandono = timeout_abandono
        self._claim_lock = threading.RLock()
        self._in_memory_uri = f"file:queue-{uuid.uuid4().hex}?mode=memory&cache=shared" if database == ":memory:" else database
        self._uri = database == ":memory:"
        self._keeper = self._connect()
        self._keeper.executescript("""
            CREATE TABLE IF NOT EXISTS tareas (
                id INTEGER PRIMARY KEY, video_key TEXT NOT NULL, etapa TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente', intentos INTEGER NOT NULL DEFAULT 0,
                max_intentos INTEGER NOT NULL DEFAULT 3, proxima_ejecucion REAL NOT NULL,
                ultimo_error TEXT, creado TEXT NOT NULL, actualizado TEXT NOT NULL,
                inicio REAL, UNIQUE(video_key, etapa));
            CREATE TABLE IF NOT EXISTS publicaciones (
                video_key TEXT PRIMARY KEY, youtube_id TEXT NOT NULL, creado TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS apartados (
                video_key TEXT PRIMARY KEY, motivo TEXT NOT NULL, creado TEXT NOT NULL);
        """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._in_memory_uri, uri=self._uri, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def encolar(self, video_key: str, etapa: str, *, max_intentos: int = 3) -> Tarea:
        if etapa not in ETAPAS:
            raise ValueError(f"Etapa inválida: {etapa}")
        now = self.reloj()
        with self._connect() as db:
            apartado = db.execute("SELECT motivo FROM apartados WHERE video_key=?", (video_key,)).fetchone()
            db.execute("INSERT OR IGNORE INTO tareas(video_key,etapa,estado,max_intentos,proxima_ejecucion,ultimo_error,creado,actualizado) VALUES(?,?,?,?,?,?,?,?)",
                       (video_key, etapa, "apartado" if apartado else "pendiente", max_intentos, now,
                        apartado["motivo"] if apartado else None, _fecha(now), _fecha(now)))
            row = db.execute("SELECT * FROM tareas WHERE video_key=? AND etapa=?", (video_key, etapa)).fetchone()
        return self._tarea(row)

    def _tarea(self, row: sqlite3.Row) -> Tarea:
        return Tarea(row["id"], row["video_key"], row["etapa"], row["estado"], row["intentos"],
                     row["max_intentos"], row["proxima_ejecucion"], row["ultimo_error"])

    def reclamar(self, etapas: Iterable[str] | None = None) -> Tarea | None:
        with self._claim_lock:
            return self._reclamar_atomico(etapas)

    def _reclamar_atomico(self, etapas: Iterable[str] | None = None) -> Tarea | None:
        etapas = None if etapas is None else tuple(dict.fromkeys(etapas))
        if etapas == ():
            return None
        now = self.reloj()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            stale = now - self.timeout_abandono
            filtro_etapas = "" if etapas is None else " AND etapa IN (" + ",".join("?" for _ in etapas) + ")"
            params_etapas = () if etapas is None else etapas
            db.execute("""UPDATE tareas SET
                estado=CASE WHEN intentos>=max_intentos THEN 'fallido' ELSE 'pendiente' END,
                ultimo_error=CASE WHEN intentos>=max_intentos THEN 'Abandono: máximo de intentos alcanzado' ELSE ultimo_error END,
                inicio=NULL, actualizado=? WHERE estado='en_curso' AND inicio<=?""" + filtro_etapas + """
                AND NOT EXISTS(SELECT 1 FROM apartados a WHERE a.video_key=tareas.video_key)""", (_fecha(now), stale, *params_etapas))
            row = db.execute("""SELECT t.* FROM tareas t
                WHERE t.estado='pendiente' AND t.proxima_ejecucion<=?
                """ + ("" if etapas is None else " AND t.etapa IN (" + ",".join("?" for _ in etapas) + ")") + """
                AND (t.etapa='tema' OR EXISTS (
                    SELECT 1 FROM tareas prev WHERE prev.video_key=t.video_key
                    AND prev.etapa=CASE t.etapa
                        WHEN 'guion' THEN 'tema' WHEN 'verificacion' THEN 'guion'
                        WHEN 'narracion' THEN 'verificacion' WHEN 'render' THEN 'narracion'
                        WHEN 'qa' THEN 'render' WHEN 'miniatura' THEN 'qa'
                        WHEN 'subida' THEN 'miniatura' WHEN 'verificacion_post' THEN 'subida' END
                    AND prev.estado='hecho'))
                AND NOT EXISTS(SELECT 1 FROM apartados a WHERE a.video_key=t.video_key)
                AND NOT (t.etapa='subida' AND EXISTS(SELECT 1 FROM publicaciones p WHERE p.video_key=t.video_key))
                ORDER BY t.proxima_ejecucion,t.id LIMIT 1""", (now, *params_etapas)).fetchone()
            if row is None:
                db.commit()
                return None
            db.execute("UPDATE tareas SET estado='en_curso',intentos=intentos+1,inicio=?,actualizado=? WHERE id=?", (now, _fecha(now), row["id"]))
            row = db.execute("SELECT * FROM tareas WHERE id=?", (row["id"],)).fetchone()
            db.commit()
            return self._tarea(row)
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def completar(self, tarea_id: int) -> None:
        now = self.reloj()
        with self._connect() as db:
            db.execute("UPDATE tareas SET estado='hecho',inicio=NULL,actualizado=? WHERE id=? AND estado='en_curso'", (_fecha(now), tarea_id))

    def liberar(self, tarea_id: int) -> None:
        """Devuelve una tarea reclamada a pendiente sin consumir ese intento."""
        now = self.reloj()
        with self._connect() as db:
            db.execute("""UPDATE tareas SET estado='pendiente',intentos=intentos-1,inicio=NULL,
                proxima_ejecucion=?,actualizado=? WHERE id=? AND estado='en_curso'""",
                (now, _fecha(now), tarea_id))

    def fallar(self, tarea_id: int, error: str) -> Tarea:
        now = self.reloj()
        with self._connect() as db:
            row = db.execute("SELECT * FROM tareas WHERE id=?", (tarea_id,)).fetchone()
            if row is None:
                raise KeyError(tarea_id)
            if row["estado"] == "apartado":
                return self._tarea(row)
            state = "fallido" if row["intentos"] >= row["max_intentos"] else "pendiente"
            delay = min(self.tope_backoff, self.base_backoff * (2 ** max(0, row["intentos"] - 1)))
            nxt = now + delay if state == "pendiente" else now
            db.execute("UPDATE tareas SET estado=?,proxima_ejecucion=?,ultimo_error=?,inicio=NULL,actualizado=? WHERE id=?",
                       (state, nxt, error, _fecha(now), tarea_id))
            return self._tarea(db.execute("SELECT * FROM tareas WHERE id=?", (tarea_id,)).fetchone())

    def reintentar_programado(self, tarea_id: int, error: str, demora: float) -> Tarea:
        """Programa un reintento diferido sin consumir un intento de fallo."""
        now = self.reloj()
        with self._connect() as db:
            db.execute("""UPDATE tareas SET estado='pendiente',intentos=MAX(0,intentos-1),
                proxima_ejecucion=?,ultimo_error=?,inicio=NULL,actualizado=?
                WHERE id=? AND estado='en_curso'""",
                (now + max(0, demora), error, _fecha(now), tarea_id))
            return self._tarea(db.execute("SELECT * FROM tareas WHERE id=?", (tarea_id,)).fetchone())

    def fallo_definitivo(self, tarea_id: int, error: str) -> Tarea:
        """Marca fallido aunque la etapa no haya agotado sus intentos normales."""
        now = self.reloj()
        with self._connect() as db:
            db.execute("""UPDATE tareas SET estado='fallido',intentos=max_intentos,
                ultimo_error=?,inicio=NULL,actualizado=? WHERE id=? AND estado='en_curso'""",
                (error, _fecha(now), tarea_id))
            return self._tarea(db.execute("SELECT * FROM tareas WHERE id=?", (tarea_id,)).fetchone())

    def registrar_publicacion(self, video_key: str, youtube_id: str) -> None:
        now = self.reloj()
        with self._connect() as db:
            db.execute("INSERT INTO publicaciones(video_key,youtube_id,creado) VALUES(?,?,?)", (video_key, youtube_id, _fecha(now)))
            db.execute("UPDATE tareas SET estado='hecho',inicio=NULL,actualizado=? WHERE video_key=? AND etapa='subida' AND estado IN ('en_curso','pendiente')", (_fecha(now), video_key))

    def publicacion(self, video_key: str) -> str | None:
        """Devuelve el ID de YouTube registrado para el video, si existe."""
        with self._connect() as db:
            row = db.execute("SELECT youtube_id FROM publicaciones WHERE video_key=?", (video_key,)).fetchone()
        return row["youtube_id"] if row else None

    def subida_pendiente_de_verificar(self, video_key: str) -> bool:
        """Indica si una subida iniciada puede haber llegado a YouTube sin registrarse.

        Antes de reintentar, consultar YouTube por video_key en la descripción o
        etiqueta; si existe, registrar el resultado con registrar_publicacion.
        """
        with self._connect() as db:
            return db.execute("""SELECT 1 FROM tareas t WHERE t.video_key=? AND t.etapa='subida'
                AND t.intentos>0 AND t.estado NOT IN ('hecho','apartado')
                AND NOT EXISTS(SELECT 1 FROM publicaciones p WHERE p.video_key=t.video_key)""", (video_key,)).fetchone() is not None

    def apartar(self, video_key: str, motivo: str) -> int:
        now = self.reloj()
        with self._connect() as db:
            db.execute("INSERT INTO apartados(video_key,motivo,creado) VALUES(?,?,?) ON CONFLICT(video_key) DO UPDATE SET motivo=excluded.motivo", (video_key, motivo, _fecha(now)))
            cur = db.execute("UPDATE tareas SET estado='apartado',ultimo_error=?,inicio=NULL,actualizado=? WHERE video_key=? AND estado IN ('pendiente','en_curso')", (motivo, _fecha(now), video_key))
            return cur.rowcount
