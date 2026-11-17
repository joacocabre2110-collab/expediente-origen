from pathlib import Path
from types import SimpleNamespace

from canal.pipeline.etapas import ContextoVideo, Guion, Narracion, Render, Tema, ResultadoQA
from canal.render.config import RenderConfig
from canal.render.render_real import ControlCalidadReal, RenderizadorReal


class Planificador:
    def planificar(self, contexto, tema, guion):
        return [
            {"texto": "Hola mundo.", "escena": {"tipo": "portada", "datos": {"expediente": "EXP", "titulo": "Hola mundo", "subtitulo": "Una historia"}}, "impacto": False},
            {"texto": "Fin de historia.", "escena": {"tipo": "cierre", "datos": {"frase": "Fin de historia", "adelanto": "Otro caso"}}, "impacto": True},
        ]


def test_renderizador_conecta_plan_y_audios_segmentados(tmp_path):
    calls = {}
    class Narrador:
        def narrar_segmentos(self, textos, directorio):
            calls["textos"] = textos
            return [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    def montar(plan, cfg, salida, **kwargs):
        calls["plan"] = plan
        calls["salida"] = salida
        return salida
    contexto = ContextoVideo("video", "short", "2026-01-01", tmp_path)
    narracion = Narracion(tmp_path / "total.mp3", .2, 10)
    result = RenderizadorReal(Planificador(), narrador=Narrador(), config=RenderConfig(dir_trabajo=tmp_path), montar_fn=montar).renderizar(
        contexto, Tema("Caso", "caso", "espacio", []), Guion("Hola mundo. Fin de historia.", "", "", "", "espacio"), narracion)
    assert result == Render(tmp_path / "video.mp4", .2)
    assert [s.ruta_audio for s in calls["plan"].segmentos] == [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    assert calls["plan"].formato == "short"


def test_control_calidad_adapta_resultado(tmp_path):
    fake = SimpleNamespace(correcto=False, motivos=("falla",))
    ctl = ControlCalidadReal(verificar_fn=lambda *a, **kw: fake)
    ctx = ContextoVideo("v", "short", "2026-01-01", tmp_path)
    result = ctl.controlar(ctx, None, None, None, Render(tmp_path / "v.mp4", 0))
    assert result == ResultadoQA(False, ["falla"])
