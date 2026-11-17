"""Coordinación segura e idempotente del ciclo diario."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from canal.alerts import Alerta, Nivel


class LockCicloOcupado(RuntimeError):
    """Ya hay otro ciclo usando este directorio de datos."""


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as archivo:
        try:
            fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockCicloOcupado(f"Ciclo ya activo: {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)


def ejecutar_ciclo(ensamblado: Any, hoy: date, max_pasos: int = 1000,
                   presupuesto_dia_usd: float = 10.0) -> dict[str, Any]:
    """Rellena reserva, ejecuta tareas y emite el resumen diario."""
    if max_pasos < 0 or presupuesto_dia_usd < 0:
        raise ValueError("max_pasos y presupuesto_dia_usd deben ser no negativos")
    orq, ledger = ensamblado.orquestador, ensamblado.ledger
    notificador = orq.notificador
    lock_path = orq.directorio_base / ".scheduler.lock"
    with _lock(lock_path):
        inicio = ledger.gasto_mes()
        estado = orq.estado_reserva(hoy)
        antes = int(estado.get("dias", 0))
        if estado.get("necesita_reponer", antes < 5):
            # Se completan hasta siete días futuros, a razón de cuatro videos diarios.
            for offset in range(max(0, antes), 7):
                orq.programar_dia(hoy + timedelta(days=offset + 1))
        tareas = []
        for _ in range(max_pasos):
            paso = orq.ejecutar_hasta_vaciar(max_pasos=1)
            if not paso:
                break
            tareas.extend(paso)
            if paso[-1].estado == "fallido" and paso[-1].video_key:
                # El fallo agotó los reintentos de esta etapa; aislar todo el video.
                ensamblado.cola.apartar(paso[-1].video_key, paso[-1].detalle or "fallo grave")
            gasto_actual = max(0.0, ledger.gasto_mes() - inicio)
            if gasto_actual > presupuesto_dia_usd or paso[-1].estado in ("sin_tareas", "pausado_presupuesto"):
                break
        gasto_dia = max(0.0, ledger.gasto_mes() - inicio)
        excedido = gasto_dia > presupuesto_dia_usd
        if excedido:
            notificador.notificar(Alerta(Nivel.CRITICO, "Presupuesto diario excedido",
                f"Gasto del ciclo: ${gasto_dia:.2f}; límite: ${presupuesto_dia_usd:.2f}. Producción detenida."))
        resumen_reserva = orq.estado_reserva(hoy)
        presupuesto = ledger.estado()
        apartados = sum(1 for r in tareas if r.estado == "apartado")
        producidos = sum(1 for r in tareas if r.estado == "ok")
        cuota = getattr(ensamblado.cliente, "unidades_cuota_consumidas", 0)
        cuerpo = (f"Fecha: {hoy.isoformat()}\nProducidos: {producidos}\nApartados: {apartados}"
                  f"\nCosto diario: ${gasto_dia:.4f}\nCuota YouTube: {cuota}"
                  f"\nReserva: {resumen_reserva.get('dias', 0)} días")
        notificador.notificar(Alerta(Nivel.DIARIO, f"Resumen diario {hoy.isoformat()}", cuerpo))
        if hasattr(notificador, "vaciar_resumen"):
            notificador.vaciar_resumen(Nivel.DIARIO)
        pct = presupuesto.porcentaje
        if resumen_reserva.get("dias", 0) < 2 or (pct is not None and pct > 80):
            motivos = []
            if resumen_reserva.get("dias", 0) < 2:
                motivos.append(f"reserva crítica: {resumen_reserva.get('dias', 0)} días")
            if pct is not None and pct > 80:
                motivos.append(f"presupuesto mensual al {pct:.1f}%")
            notificador.notificar(Alerta(Nivel.CRITICO, "Alerta crítica del ciclo diario", "; ".join(motivos)))
        return {"fecha": hoy, "producidos": producidos, "apartados": apartados,
                "costo_diario_usd": gasto_dia, "presupuesto_excedido": excedido,
                "cuota_youtube": cuota, "reserva_dias": resumen_reserva.get("dias", 0),
                "resultados": tareas}
