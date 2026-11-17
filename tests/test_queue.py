import threading

import pytest

from canal.queue import QueueStore


class Clock:
    value = 1000.0

    def __call__(self):
        return self.value


def test_idempotencia():
    q = QueueStore()
    a = q.encolar("largo-1", "tema")
    b = q.encolar("largo-1", "tema")
    assert a.id == b.id


def test_backoff_y_agotamiento():
    c = Clock()
    q = QueueStore(reloj=c, base_backoff=2, tope_backoff=5)
    task = q.encolar("v", "tema", max_intentos=2)
    first = q.reclamar()
    failed = q.fallar(first.id, "error")
    assert failed.estado == "pendiente" and failed.proxima_ejecucion == 1002
    assert q.reclamar() is None
    c.value = 1002
    second = q.reclamar()
    failed = q.fallar(second.id, "final")
    assert failed.estado == "fallido" and failed.ultimo_error == "final"


def test_claim_concurrente():
    q = QueueStore()
    q.encolar("v", "tema")
    results = []
    threads = [threading.Thread(target=lambda: results.append(q.reclamar())) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r is not None for r in results) == 1


def test_recupera_abandonada():
    c = Clock()
    q = QueueStore(reloj=c, timeout_abandono=10)
    task = q.encolar("v", "tema")
    assert q.reclamar().id == task.id
    c.value += 11
    assert q.reclamar().id == task.id


def test_liberar_devuelve_a_pendiente_sin_consumir_intento():
    q = QueueStore(reloj=Clock())
    task = q.encolar("v", "tema")
    claimed = q.reclamar()
    q.liberar(task.id)
    row = q._keeper.execute("SELECT estado,intentos,inicio FROM tareas WHERE id=?", (task.id,)).fetchone()
    assert tuple(row) == ("pendiente", 0, None)
    assert q.reclamar().id == claimed.id


def test_orden_etapas():
    q = QueueStore()
    q.encolar("v", "guion")
    assert q.reclamar() is None
    q.encolar("v", "tema")
    first = q.reclamar()
    assert first.etapa == "tema"
    q.completar(first.id)
    assert q.reclamar().etapa == "guion"


def test_publicacion_duplicada_y_bloquea_subida():
    q = QueueStore()
    q.encolar("v", "subida")
    q.registrar_publicacion("v", "yt1")
    assert q.reclamar() is None
    with pytest.raises(Exception):
        q.registrar_publicacion("v", "yt2")


def test_apartar_aislado():
    q = QueueStore()
    q.encolar("a", "tema")
    q.encolar("a", "guion")
    q.encolar("b", "tema")
    assert q.apartar("a", "pausa") == 2
    task = q.reclamar()
    assert task.video_key == "b"


def test_abandono_agotado_falla_y_no_se_reintenta():
    c = Clock()
    q = QueueStore(reloj=c, timeout_abandono=1)
    task = q.encolar("v", "tema", max_intentos=1)
    q.reclamar()
    c.value += 2
    assert q.reclamar() is None
    row = q._keeper.execute("SELECT estado, ultimo_error FROM tareas WHERE id=?", (task.id,)).fetchone()
    assert row["estado"] == "fallido"
    assert "abandono" in row["ultimo_error"].lower()


def test_subida_pendiente_de_verificar_y_publicacion_completa():
    q = QueueStore()
    for etapa in ("tema", "guion", "verificacion", "narracion", "render", "qa", "miniatura"):
        q.encolar("v", etapa)
        claimed_prev = q.reclamar()
        assert claimed_prev.etapa == etapa
        q.completar(claimed_prev.id)
    task = q.encolar("v", "subida")
    assert q.subida_pendiente_de_verificar("v") is False
    claimed = q.reclamar()
    assert claimed.id == task.id
    assert q.subida_pendiente_de_verificar("v") is True
    q.registrar_publicacion("v", "yt1")
    assert q.subida_pendiente_de_verificar("v") is False
    q.completar(task.id)
    assert q.subida_pendiente_de_verificar("v") is False


def test_apartar_en_curso_persiste_para_encolar_y_bloquea_operaciones():
    q = QueueStore()
    task = q.encolar("v", "tema")
    assert q.reclamar().id == task.id
    assert q.apartar("v", "pausa") == 1
    q.completar(task.id)
    assert q.fallar(task.id, "error").estado == "apartado"
    assert q.encolar("v", "guion").estado == "apartado"
    assert q.reclamar() is None
