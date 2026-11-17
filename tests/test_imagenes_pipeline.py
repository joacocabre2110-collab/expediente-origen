from types import SimpleNamespace

from canal.app.ensamblado import GeneradorMetadatosConAviso
from canal.investigacion.imagenes import ImagenLibre, creditos
from canal.pipeline.etapas import ContextoVideo, Guion, Metadatos, Narracion, Tema
from canal.render.config import RenderConfig
from canal.render.render_real import RenderizadorReal


class Planner:
    def __init__(self, assign=True):
        self.assign, self.received = assign, None

    def planificar(self, contexto, tema, guion, imagenes=None):
        self.received = imagenes
        datos = {"frase": "Hola"}
        if self.assign and imagenes:
            datos["imagen"] = imagenes[0].url_local
        return [
            {"texto": "Hola.", "escena": {"tipo": "portada", "datos": datos}, "impacto": False},
            {"texto": "Fin.", "escena": {"tipo": "cierre", "datos": {"frase": "Fin", "adelanto": "Otro"}}, "impacto": False},
        ]


def _render(tmp_path, planner, client=None):
    ctx = ContextoVideo("v", "short", "2026-01-01", tmp_path)
    narr = Narracion(tmp_path / "audio.mp3", 0)
    renderer = RenderizadorReal(planner, config=RenderConfig(dir_trabajo=tmp_path),
        narrador=SimpleNamespace(narrar_segmentos=lambda *a: [tmp_path / "1.mp3", tmp_path / "2.mp3"]),
        montar_fn=lambda plan, cfg, salida, **kw: salida, cliente_imagenes=client)
    return renderer, renderer.renderizar(ctx, Tema("Tema", "id", "espacio", ["alias"]),
        Guion("Hola. Fin.", "", "", "", "espacio"), narr)


def test_render_planifica_con_imagenes_y_registra_solo_asignadas(tmp_path):
    img = ImagenLibre("/imagenes/a.jpg", "Título", "Autora", "CC BY 4.0", "https://fuente", 900, 600)
    planner = Planner()
    renderer = RenderizadorReal(planner, config=RenderConfig(dir_trabajo=tmp_path),
        narrador=SimpleNamespace(narrar_segmentos=lambda *a: [tmp_path / "1.mp3", tmp_path / "2.mp3"]),
        montar_fn=lambda plan, cfg, salida, **kw: salida, imagenes=[img])
    ctx = ContextoVideo("v", "short", "2026-01-01", tmp_path)
    renderer.renderizar(ctx, Tema("Tema", "id", "espacio", []), Guion("Hola. Fin.", "", "", "", "espacio"), Narracion(tmp_path / "a.mp3", 0))
    assert planner.received == [img]
    assert renderer.imagenes_usadas == [img]


def test_error_busqueda_continua_sin_imagenes(tmp_path):
    class Client:
        def buscar_para_tema(self, *args, **kwargs):
            raise OSError("sin red")
    planner = Planner()
    renderer = RenderizadorReal(planner, cliente_imagenes=Client(), config=RenderConfig(dir_trabajo=tmp_path),
        narrador=SimpleNamespace(narrar_segmentos=lambda *a: [tmp_path / "1.mp3", tmp_path / "2.mp3"]),
        montar_fn=lambda plan, cfg, salida, **kw: salida)
    ctx = ContextoVideo("v", "short", "2026-01-01", tmp_path)
    estado = renderer.preparar_imagenes(ctx, Tema("Expediente 3: Tema", "id", "", ["alias"]))
    assert estado.startswith("error: OSError")
    assert renderer.imagenes == []
    renderer.renderizar(ctx, Tema("Expediente 3: Tema", "id", "", ["alias"]),
        Guion("Hola. Fin.", "", "", "", "espacio"), Narracion(tmp_path / "a.mp3", 0))
    assert planner.received == []


def test_creditos_finales_exactos_en_descripcion():
    img = ImagenLibre("/a.jpg", "Título", "Autora", "CC BY", "https://fuente", 900, 600)
    base = SimpleNamespace(generar=lambda *a: Metadatos("Video", "Descripción suficientemente larga para validar.", []))
    gen = GeneradorMetadatosConAviso(base)
    gen.imagenes = [img]
    salida = gen.generar(SimpleNamespace(video_key="v"), None, None, None, None)
    assert salida.descripcion.endswith(creditos([img]))


def test_creditos_respetan_limite_sin_cortar_atribucion():
    imgs = [ImagenLibre(f"/{i}.jpg", f"Título {i}", "Autora", "CC BY 4.0", f"https://fuente/{i}", 900, 600) for i in range(30)]
    base = SimpleNamespace(generar=lambda *a: Metadatos("Video", "D" * 4950, []))
    gen = GeneradorMetadatosConAviso(base)
    gen.imagenes = imgs
    salida = gen.generar(SimpleNamespace(video_key="v"), None, None, None, None)
    assert len(salida.descripcion) <= 5000
    assert not salida.descripcion.endswith("https://fuente/0")
    assert "CC BY 4.0" not in salida.descripcion or salida.descripcion.endswith(creditos([imgs[0]]))
