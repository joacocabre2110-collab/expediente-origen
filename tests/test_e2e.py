from datetime import date, datetime
from types import SimpleNamespace

import pytest

from canal.alerts import Notificador
from canal.alerts import Nivel
from canal.budget import Ledger
from canal.dedupe import Historial, RegistroTemas
from canal.pipeline import Orquestador
from canal.pipeline.falsos import (ControlCalidadFalso, GeneradorGuionFalso,
    GeneradorMetadatosFalso, GeneradorMiniaturaFalso, GeneradorTemaFalso,
    NarradorFalso, RenderizadorFalso, VerificadorFalso)
from canal.queue import QueueStore
from canal.youtube import ClienteFalso, ClienteSeguro


def crear_orquestador(tmp_path, *, cliente_falso=None, qa=None, tope=100):
    reloj = lambda: date(2026, 1, 1)
    cliente_falso = cliente_falso or ClienteFalso()
    cliente = ClienteSeguro(cliente_falso)
    queue_path = str(tmp_path / "queue.sqlite")
    ledger = Ledger(str(tmp_path / "ledger.sqlite"), tope_mensual_usd=tope,
                    reloj=lambda: datetime(2026, 1, 1))
    etapas = SimpleNamespace(tema=GeneradorTemaFalso(), guion=GeneradorGuionFalso(),
        verificacion=VerificadorFalso(), narracion=NarradorFalso(.2),
        render=RenderizadorFalso(.3), qa=qa or ControlCalidadFalso(),
        miniatura=GeneradorMiniaturaFalso(.1), generador_metadatos=GeneradorMetadatosFalso())
    orch = Orquestador(QueueStore(queue_path, base_backoff=0), ledger, Notificador(),
            Historial(ruta=tmp_path / "historial.json"), RegistroTemas(ruta=tmp_path / "temas.json"),
            etapas, tmp_path, cliente, reloj)
    return orch, cliente_falso


def test_programacion_diaria_y_subida_privada_idempotente(tmp_path):
    cliente_falso = ClienteFalso()
    def crear():
        return crear_orquestador(tmp_path, cliente_falso=cliente_falso)[0]
    orch, _ = crear_orquestador(tmp_path, cliente_falso=cliente_falso)
    ledger = orch.ledger
    for dia in range(1, 4):
        orch.programar_dia(date(2026, 1, dia))
    resultados = orch.ejecutar_hasta_vaciar()
    assert len(cliente_falso.videos) == 12
    assert all(s.privacy_status == "private" and s.publish_at is None
               for s, _ in cliente_falso.videos.values())
    assert all("Narración con voz generada por IA" in s.descripcion
               for s, _ in cliente_falso.videos.values())
    assert all(s.es_short == ("#shorts" in s.titulo)
               for s, _ in cliente_falso.videos.values())
    assert all(orch.cola.publicacion(k) for k in
               [f"largo-2026-01-{d:02}" for d in range(1, 4)] +
               [f"short-2026-01-{d:02}-{i}" for d in range(1, 4) for i in range(1, 4)])
    assert len([k for k in cliente_falso.videos if orch.cola.publicacion(
        cliente_falso.videos[k][0].video_key)]) == 12
    assert ledger.gasto_mes() == 7.2
    assert ledger.costo_por_video("largo-2026-01-01") == .6
    assert not any(r.estado == "fallido" for r in resultados)
    reiniciado = crear()
    for dia in range(1, 4):
        reiniciado.programar_dia(date(2026, 1, dia))
    reiniciado.ejecutar_hasta_vaciar()
    assert len(cliente_falso.videos) == 12


def test_qa_rechaza_un_video_y_los_otros_once_completan(tmp_path):
    rechazado = "largo-2026-01-01"
    orch, cliente = crear_orquestador(tmp_path,
        qa=ControlCalidadFalso(rechazar_video_key=rechazado))
    for dia in range(1, 4):
        orch.programar_dia(date(2026, 1, dia))

    resultados = orch.ejecutar_hasta_vaciar()
    with orch.cola._connect() as db:
        apartado = db.execute("SELECT motivo FROM apartados WHERE video_key=?", (rechazado,)).fetchone()
    assert apartado is not None
    assert len(cliente.videos) == 11
    assert sum(r.etapa == "verificacion_post" and r.estado == "ok" for r in resultados) == 11
    alertas = orch.notificador.bandeja
    assert any(a.nivel is Nivel.CRITICO and a.video_key == rechazado for a in alertas)


def test_fallo_transitorio_de_subida_reintenta_sin_duplicar(tmp_path):
    orch, cliente = crear_orquestador(tmp_path, cliente_falso=ClienteFalso(fallos_transitorios=1))
    orch.programar_dia(date(2026, 1, 1))
    resultados = orch.ejecutar_hasta_vaciar()
    assert any(r.estado == "reintento" and r.etapa == "subida" for r in resultados)
    assert len(cliente.videos) == 4
    assert len({s.video_key for s, _ in cliente.videos.values()}) == 4
    assert all(orch.cola.publicacion(key) for key in (s.video_key for s, _ in cliente.videos.values()))


def test_caida_despues_de_subir_recupera_publicacion_sin_duplicar(tmp_path):
    orch, cliente = crear_orquestador(tmp_path,
        cliente_falso=ClienteFalso(fallar_despues_de_subir=True))
    orch.programar_dia(date(2026, 1, 1))
    resultados = orch.ejecutar_hasta_vaciar()
    assert any(r.estado == "reintento" and r.etapa == "subida" for r in resultados)
    assert len(cliente.videos) == 4
    for solicitud, _ in cliente.videos.values():
        assert orch.cola.publicacion(solicitud.video_key) is not None


def test_presupuesto_pausa_sin_consumir_intento_y_luego_continua(tmp_path):
    orch, cliente = crear_orquestador(tmp_path, tope=.1)
    orch.programar_dia(date(2026, 1, 1))
    resultado = orch.ejecutar_hasta_vaciar()
    assert resultado[-1].estado == "pausado_presupuesto"
    with orch.cola._connect() as db:
        intentos = db.execute("SELECT intentos FROM tareas WHERE video_key=? AND etapa=?",
                              (resultado[-1].video_key, resultado[-1].etapa)).fetchone()[0]
    assert intentos == 0
    assert not cliente.videos

    orch.ledger.tope_mensual_usd = 100
    resultados = orch.ejecutar_hasta_vaciar()
    assert len(cliente.videos) == 4
    assert sum(r.etapa == "verificacion_post" and r.estado == "ok" for r in resultados) == 4


def test_orquestador_requiere_cliente_seguro_y_bloquea_publico(tmp_path):
    orch, _ = crear_orquestador(tmp_path)
    args = (orch.cola, orch.ledger, orch.notificador, orch.historial, orch.registro_temas,
            orch.etapas, tmp_path)
    with pytest.raises(TypeError):
        Orquestador(*args, ClienteFalso())
    with pytest.raises(ValueError):
        Orquestador(*args, ClienteSeguro(ClienteFalso(), True))


def test_reserva_de_siete_dias_y_necesidad_de_reponer(tmp_path):
    orch, _ = crear_orquestador(tmp_path)
    for dia in range(2, 9):
        orch.programar_dia(date(2026, 1, dia))
    assert orch.estado_reserva(date(2026, 1, 1)) == {
        "dias": 7, "necesita_reponer": False,
    }
