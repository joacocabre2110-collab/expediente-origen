from datetime import date

import pytest

from canal.pipeline.etapas import ContextoVideo
from canal.pipeline.falsos import (
    AVISO_IA, ESTRUCTURAS, ControlCalidadFalso, FalloTransitorio,
    GeneradorGuionFalso, GeneradorMetadatosFalso, GeneradorMiniaturaFalso,
    GeneradorTemaFalso, NarradorFalso, RenderizadorFalso, VerificadorFalso,
)


def contexto(tmp_path, key="video-1", tipo="largo"):
    return ContextoVideo(key, tipo, date(2026, 1, 2), tmp_path)


def test_falsos_cumplen_contratos_y_crean_archivos(tmp_path):
    ctx = contexto(tmp_path)
    tema = GeneradorTemaFalso().generar(ctx)
    guion = GeneradorGuionFalso().generar(ctx, tema)
    verificacion = VerificadorFalso().verificar(ctx, tema, guion)
    narracion = NarradorFalso().narrar(ctx, tema, guion, verificacion)
    render = RenderizadorFalso().renderizar(ctx, tema, guion, narracion)
    qa = ControlCalidadFalso().controlar(ctx, tema, guion, narracion, render)
    miniatura = GeneradorMiniaturaFalso().generar(ctx, tema, guion, render, qa)
    metadatos = GeneradorMetadatosFalso().generar(ctx, tema, guion, render, miniatura)

    assert tema.caso_id == f"caso-{ctx.video_key}" and tema.alias
    assert guion.texto and guion.estructura in ESTRUCTURAS
    assert verificacion.aprobado and qa.aprobado
    assert narracion.costo_usd == render.costo_usd == miniatura.costo_usd == 0.0
    assert narracion.ruta_audio.read_text(encoding="utf-8") == guion.texto
    assert render.ruta_video.is_file() and miniatura.ruta.is_file()
    assert AVISO_IA in metadatos.descripcion


def test_rotacion_de_seis_estructuras_y_guion_duplicado(tmp_path):
    ctx = contexto(tmp_path)
    tema = GeneradorTemaFalso().generar(ctx)
    generador = GeneradorGuionFalso()
    assert [generador.generar(ctx, tema).estructura for _ in range(8)] == list(ESTRUCTURAS) + list(ESTRUCTURAS[:2])
    duplicado = GeneradorGuionFalso(guion_duplicado=True)
    assert duplicado.generar(ctx, tema).texto == duplicado.generar(ctx, tema).texto


def test_fallos_transitorios_y_rechazo_qa(tmp_path):
    ctx = contexto(tmp_path)
    tema = GeneradorTemaFalso(fallos_transitorios=2)
    for _ in range(2):
        with pytest.raises(FalloTransitorio):
            tema.generar(ctx)
    resultado_tema = tema.generar(ctx)
    guion = GeneradorGuionFalso().generar(ctx, resultado_tema)
    verificacion = VerificadorFalso().verificar(ctx, resultado_tema, guion)
    narracion = NarradorFalso(fallos_transitorios=1)
    with pytest.raises(FalloTransitorio):
        narracion.narrar(ctx, resultado_tema, guion, verificacion)
    audio = narracion.narrar(ctx, resultado_tema, guion, verificacion)
    render = RenderizadorFalso().renderizar(ctx, resultado_tema, guion, audio)
    qa = ControlCalidadFalso(rechazar_video_key=ctx.video_key).controlar(ctx, resultado_tema, guion, audio, render)
    assert not qa.aprobado and qa.motivos == ["rechazado_por_clave"]


def test_short_termina_titulo_con_hashtag(tmp_path):
    ctx = contexto(tmp_path, tipo="short")
    tema = GeneradorTemaFalso().generar(ctx)
    guion = GeneradorGuionFalso().generar(ctx, tema)
    audio = NarradorFalso().narrar(ctx, tema, guion, None)
    render = RenderizadorFalso().renderizar(ctx, tema, guion, audio)
    miniatura = GeneradorMiniaturaFalso().generar(ctx, tema, guion, render, None)
    metadata = GeneradorMetadatosFalso().generar(ctx, tema, guion, render, miniatura)
    assert metadata.titulo.endswith("#shorts")
