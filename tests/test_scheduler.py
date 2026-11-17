from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from canal.alerts import Nivel
from canal.scheduler.diario import LockCicloOcupado, ejecutar_ciclo


class Ledger:
    def __init__(self, tope=100):
        self.gasto = 0.0
        self.tope = tope

    def gasto_mes(self):
        return self.gasto

    def estado(self):
        pct = self.gasto / self.tope * 100 if self.tope else None
        return SimpleNamespace(porcentaje=pct)


class Notificador:
    def __init__(self):
        self.alertas = []

    def notificar(self, alerta):
        self.alertas.append(alerta)

    def vaciar_resumen(self, nivel):
        return True


class Orq:
    def __init__(self, base, dias=0, pasos=None, ledger=None):
        self.directorio_base = Path(base)
        self.notificador = Notificador()
        self.dias = dias
        self.programados = set()
        self.pasos = list(pasos or [])
        self.ledger = ledger

    def estado_reserva(self, hoy):
        return {"dias": self.dias, "necesita_reponer": self.dias < 5}

    def programar_dia(self, fecha):
        self.programados.add(fecha)
        return fecha

    def ejecutar_hasta_vaciar(self, max_pasos):
        if not self.pasos:
            return [SimpleNamespace(estado="sin_tareas")]
        paso = self.pasos.pop(0)
        if self.ledger and hasattr(paso, "costo"):
            self.ledger.gasto += paso.costo
        return [paso]


def bundle(tmp_path, dias=0, pasos=None, ledger=None):
    ledger = ledger or Ledger()
    orq = Orq(tmp_path, dias, pasos, ledger)
    return SimpleNamespace(orquestador=orq, ledger=ledger, cliente=SimpleNamespace(unidades_cuota_consumidas=42)), orq, ledger


def test_rellena_reserva_hasta_siete_dias(tmp_path):
    e, orq, _ = bundle(tmp_path, dias=2)
    resultado = ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=0)
    assert len(orq.programados) == 5
    assert resultado["reserva_dias"] == 2


def test_idempotencia_programa_mismas_fechas(tmp_path):
    e, orq, _ = bundle(tmp_path, dias=5)
    ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=0)
    ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=0)
    assert not orq.programados


def test_lock_rechaza_ciclo_concurrente(tmp_path):
    e, orq, _ = bundle(tmp_path)
    lock = tmp_path / ".scheduler.lock"
    lock.touch()
    import fcntl
    with lock.open("r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(LockCicloOcupado):
            ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=0)
        fcntl.flock(f, fcntl.LOCK_UN)


def test_tope_costo_diario_aborta_y_alerta(tmp_path):
    ledger = Ledger()
    paso = SimpleNamespace(estado="ok", costo=2.0)
    e, orq, _ = bundle(tmp_path, dias=5, pasos=[paso], ledger=ledger)
    resultado = ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=5, presupuesto_dia_usd=1)
    assert resultado["presupuesto_excedido"]
    assert len(orq.pasos) == 0
    assert any(a.nivel is Nivel.CRITICO and "excedido" in a.asunto for a in orq.notificador.alertas)


def test_apartado_no_detiene_siguientes_pasos(tmp_path):
    pasos = [SimpleNamespace(estado="apartado"), SimpleNamespace(estado="ok")]
    e, orq, _ = bundle(tmp_path, dias=5, pasos=pasos)
    resultado = ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=2)
    assert resultado["apartados"] == 1
    assert resultado["producidos"] == 1


def test_alerta_critica_por_reserva_y_presupuesto_mensual(tmp_path):
    ledger = Ledger(tope=10)
    ledger.gasto = 8.5
    e, orq, _ = bundle(tmp_path, dias=1, ledger=ledger)
    ejecutar_ciclo(e, date(2026, 1, 1), max_pasos=0)
    criticas = [a for a in orq.notificador.alertas if a.nivel is Nivel.CRITICO]
    assert any("crítica" in a.asunto for a in criticas)
