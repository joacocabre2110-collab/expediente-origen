from datetime import date

import pytest

from canal.app import construir_orquestador
from canal.app.ensamblado import AVISO_IA, GeneradorMetadatosConAviso
from canal.pipeline.etapas import ContextoVideo, Metadatos


def test_dry_run_ensambla_y_cliente_nunca_es_publico(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("publish_public_enabled = true\npresupuesto_mensual_usd = 70\n", encoding="utf-8")
    e = construir_orquestador(cfg, tmp_path / "datos", "dry-run")
    assert e.cliente.publicacion_publica_habilitada is False
    assert any("ignorado" in a for a in e.advertencias)
    assert e.orquestador.etapas.generador_metadatos is not None


def test_modo_real_falla_claro_si_faltan_claves(tmp_path):
    with pytest.raises(FileNotFoundError, match="gemini_api_key.txt"):
        construir_orquestador(tmp_path / "no.toml", tmp_path / "datos", "real", dir_secretos=tmp_path)


def test_modo_invalido(tmp_path):
    with pytest.raises(ValueError):
        construir_orquestador(tmp_path / "c.toml", tmp_path, "publico")


def test_metadatos_agregan_aviso_e_id_interno_sin_duplicar(tmp_path):
    class Base:
        def generar(self, *a):
            return Metadatos("Titulo de prueba", "Descripción base del video de prueba.", ["a", "b", "c"])
    ctx = ContextoVideo("vid-1", "short", date(2026, 1, 1), tmp_path)
    g = GeneradorMetadatosConAviso(Base())
    m = g.generar(ctx, None, None, None, None)
    assert AVISO_IA in m.descripcion and "ID-interno: vid-1" in m.descripcion
    m2 = GeneradorMetadatosConAviso(type("B", (), {"generar": lambda s, *a: m})()).generar(ctx, None, None, None, None)
    assert m2.descripcion.count(AVISO_IA) == 1 and m2.descripcion.count("ID-interno: vid-1") == 1
