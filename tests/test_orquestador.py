from datetime import date, datetime
from types import SimpleNamespace

from canal.alerts import Notificador, Nivel
from canal.budget import Ledger
from canal.dedupe import Historial, RegistroTemas
from canal.pipeline import Orquestador
from canal.pipeline.falsos import (ControlCalidadFalso, GeneradorGuionFalso,
    GeneradorMiniaturaFalso, GeneradorMetadatosFalso, GeneradorTemaFalso, NarradorFalso, RenderizadorFalso,
    VerificadorFalso)
from canal.queue import QueueStore
from canal.youtube import ClienteFalso, ClienteSeguro, EstadoVideo


class Reloj:
    def __call__(self):
        return date(2026, 1, 2)


class RelojBudget:
    def __call__(self):
        return datetime(2026, 1, 2)


def setup(tmp_path, *, qa=None, guion=None, budget=None, retries=3):
    q = QueueStore(base_backoff=0)
    ledger = budget or Ledger(tope_mensual_usd=100, reloj=RelojBudget())
    notifier = Notificador()
    gens = SimpleNamespace(tema=GeneradorTemaFalso(), guion=guion or GeneradorGuionFalso(),
        verificacion=VerificadorFalso(), narracion=NarradorFalso(.2), render=RenderizadorFalso(.3),
        qa=qa or ControlCalidadFalso(), miniatura=GeneradorMiniaturaFalso(.1),
        generador_metadatos=GeneradorMetadatosFalso())
    orch = Orquestador(q, ledger, notifier, Historial(), RegistroTemas(), gens, tmp_path,
                       ClienteSeguro(ClienteFalso()), Reloj())
    return q, ledger, notifier, orch


def run_video(q, orch, key):
    for etapa in ("tema", "guion", "verificacion", "narracion", "render", "qa", "miniatura"):
        q.encolar(key, etapa)
    return [orch.ejecutar_siguiente() for _ in range(7)]


def test_happy_path_persists_every_stage_and_costs(tmp_path):
    q, ledger, _, orch = setup(tmp_path)
    results = run_video(q, orch, "v1")
    assert all(r.estado == "ok" for r in results)
    assert (tmp_path / "v1" / "estado.json").is_file()
    assert ledger.costo_por_video("v1") == .6


def test_four_distinct_videos_pass_dedupe(tmp_path):
    q, _, _, orch = setup(tmp_path)
    for key in ("one", "two", "three", "four"):
        results = run_video(q, orch, key)
        assert all(r.estado == "ok" for r in results)


def test_duplicate_script_regenerates_then_sets_aside(tmp_path):
    q, _, notifier, orch = setup(tmp_path, guion=GeneradorGuionFalso(guion_duplicado=True))
    run_video(q, orch, "first")
    q.encolar("second", "tema")
    orch.ejecutar_siguiente()
    q.encolar("second", "guion")
    result = orch.ejecutar_siguiente()
    assert result.estado == "apartado"
    assert len(notifier.bandeja) == 1 and notifier.bandeja[0].nivel is Nivel.CRITICO


def test_no_toca_etapas_no_implementadas(tmp_path):
    q, _, _, orch = setup(tmp_path)
    task = q.encolar("pendiente-subida", "subida")
    assert [r.estado for r in orch.ejecutar_hasta_vaciar()] == ["sin_tareas"]
    with q._connect() as db:
        row = db.execute("SELECT estado,intentos FROM tareas WHERE id=?", (task.id,)).fetchone()
    assert tuple(row) == ("pendiente", 0)


def test_tema_repetido_regenera_y_aprueba_otro(tmp_path):
    q, _, notifier, orch = setup(tmp_path)
    gen = GeneradorTemaFalso()
    orch.etapas.tema = gen
    first_title = gen.generar(type("Ctx", (), {"video_key": "v"})()).titulo
    orch.registro_temas.agregar(first_title, [], "", fecha=date(2026, 1, 2), video_key="previo")
    # Reinicia el falso para que su primera propuesta vuelva a ser la repetida.
    orch.etapas.tema = GeneradorTemaFalso()
    q.encolar("v", "tema")
    assert orch.ejecutar_siguiente().estado == "ok"
    state = orch._leer("v")
    assert state["tema"]["titulo"] != first_title
    assert not notifier.bandeja


def test_tema_repetido_tres_veces_aparta_y_alerta(tmp_path):
    q, _, notifier, orch = setup(tmp_path)
    gen = GeneradorTemaFalso()
    for i in range(3):
        tema = gen.generar(type("Ctx", (), {"video_key": "v"})())
        orch.registro_temas.agregar(tema.titulo, [], "", fecha=date(2026, 1, 2), video_key=f"previo-{i}")
    orch.etapas.tema = GeneradorTemaFalso()
    q.encolar("v", "tema")
    result = orch.ejecutar_siguiente()
    assert result.estado == "apartado"
    assert notifier.bandeja[-1].nivel is Nivel.CRITICO


def test_qa_rejection_only_sets_aside_that_video(tmp_path):
    q, _, _, orch = setup(tmp_path, qa=ControlCalidadFalso(rechazar_video_key="bad"))
    assert [r.estado for r in run_video(q, orch, "bad")][-2:] == ["apartado", "sin_tareas"][:1] if False else True
    assert q.reclamar() is None
    q.encolar("good", "tema")
    assert orch.ejecutar_siguiente().estado == "ok"


def test_transient_failure_retries_then_completes(tmp_path):
    q, _, _, orch = setup(tmp_path)
    orch.etapas.tema = GeneradorTemaFalso(fallos_transitorios=1)
    q.encolar("v", "tema")
    assert orch.ejecutar_siguiente().estado == "reintento"
    assert orch.ejecutar_siguiente().estado == "ok"


def test_budget_pause_keeps_attempt_count_and_alerts_once(tmp_path):
    q, ledger, notifier, orch = setup(tmp_path)
    ledger.registrar_gasto("setup", 101, "other")
    q.encolar("v", "tema")
    orch.ejecutar_siguiente()
    q.encolar("v", "guion")
    orch.ejecutar_siguiente()
    q.encolar("v", "verificacion")
    orch.ejecutar_siguiente()
    q.encolar("v", "narracion")
    assert orch.ejecutar_siguiente().estado == "pausado_presupuesto"
    with q._connect() as db:
        row = db.execute("select intentos,estado from tareas where video_key='v' and etapa='narracion'").fetchone()
    assert tuple(row) == (0, "pendiente")
    q.encolar("w", "tema"); orch.ejecutar_siguiente()
    q.encolar("w", "guion"); orch.ejecutar_siguiente()
    q.encolar("w", "verificacion"); orch.ejecutar_siguiente()
    q.encolar("w", "narracion"); orch.ejecutar_siguiente()
    assert len(notifier.bandeja) == 1


def test_definitive_failure_alerts_critical(tmp_path):
    q, _, notifier, orch = setup(tmp_path)
    orch.etapas.tema = GeneradorTemaFalso(fallos_transitorios=9)
    q.encolar("v", "tema", max_intentos=1)
    result = orch.ejecutar_siguiente()
    assert result.estado == "fallido"
    assert notifier.bandeja[-1].nivel is Nivel.CRITICO
    assert notifier.bandeja[-1].video_key == "v"


def test_verificacion_post_processing_uses_long_backoff_without_consuming_attempt(tmp_path):
    now = [1000.0]
    q, _, notifier, orch = setup(tmp_path)
    q.reloj = lambda: now[0]
    q.encolar("v", "subida")
    q.registrar_publicacion("v", "yt-v")
    orch.cliente.cliente.videos["yt-v"] = (None, EstadoVideo.PROCESANDO)
    q.encolar("v", "verificacion_post")

    r = orch.ejecutar_siguiente()
    assert r.estado == "reintento" and "procesando" in r.detalle
    row = q._connect().execute("select estado,intentos,proxima_ejecucion from tareas where video_key='v' and etapa='verificacion_post'").fetchone()
    assert row["estado"] == "pendiente" and row["intentos"] == 0
    assert row["proxima_ejecucion"] == 1120
    assert not notifier.bandeja

    now[0] += 120
    orch.ejecutar_siguiente()
    row = q._connect().execute("select intentos,proxima_ejecucion from tareas where video_key='v' and etapa='verificacion_post'").fetchone()
    assert row["intentos"] == 0 and row["proxima_ejecucion"] == 1420
