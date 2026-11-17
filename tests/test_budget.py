from datetime import datetime

import pytest

from canal.budget import Ledger


class Reloj:
    def __init__(self, valor):
        self.valor = datetime.fromisoformat(valor)

    def __call__(self):
        return self.valor


def test_acumulado_y_cambio_de_mes():
    reloj = Reloj("2025-01-31T12:00:00")
    ledger = Ledger(tope_mensual_usd=100, reloj=reloj)
    ledger.registrar_gasto("api", 12.5)
    ledger.registrar_gasto("api", 7.5)
    assert ledger.gasto_mes() == 20
    reloj.valor = datetime.fromisoformat("2025-02-01T00:00:00")
    assert ledger.gasto_mes() == 0


def test_aviso_80_por_ciento_una_vez_y_persistido(tmp_path):
    reloj = Reloj("2025-01-01T00:00:00")
    path = str(tmp_path / "budget.sqlite")
    ledger = Ledger(path, 100, reloj)
    ledger.registrar_gasto("api", 80)
    assert ledger.aviso_pendiente() is True
    assert ledger.aviso_pendiente() is False
    assert Ledger(path, 100, reloj).aviso_pendiente() is False


def test_pausa_y_alerta_100_por_ciento():
    ledger = Ledger(tope_mensual_usd=10, reloj=Reloj("2025-01-01T00:00:00"))
    ledger.registrar_gasto("api", 10)
    assert ledger.estado().nivel == "pausa"
    assert ledger.puede_producir() is True
    assert ledger.puede_producir(0.01) is False
    assert ledger.aviso_pendiente() is True  # umbral 80 %
    assert ledger.aviso_pendiente() is True  # umbral 100 %
    assert ledger.aviso_pendiente() is False


def test_sin_tope_no_produce():
    ledger = Ledger(reloj=Reloj("2025-01-01T00:00:00"))
    assert ledger.estado().nivel == "sin_tope"
    assert not ledger.puede_producir()


def test_desgloses_por_servicio_y_video():
    ledger = Ledger(tope_mensual_usd=100, reloj=Reloj("2025-01-01T00:00:00"))
    ledger.registrar_gasto("api", 2, "v1")
    ledger.registrar_gasto("render", 3, "v1")
    ledger.registrar_gasto("api", 4, "v2")
    assert ledger.gasto_por_servicio() == {"api": 6, "render": 3}
    assert ledger.costo_por_video("v1") == 5
    assert ledger.costo_por_video("v2") == 4


@pytest.mark.parametrize("monto", [-1, float("inf"), float("nan"), -float("inf")])
def test_montos_invalidos(monto):
    ledger = Ledger(tope_mensual_usd=100, reloj=Reloj("2025-01-01T00:00:00"))
    with pytest.raises(ValueError):
        ledger.registrar_gasto("api", monto)
    with pytest.raises(ValueError):
        ledger.puede_producir(monto)
