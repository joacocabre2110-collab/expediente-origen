from datetime import date

from canal.dedupe.temas import RegistroTemas, normalizar_tema, tema_repetido


def test_redaccion_distinta_rechazada():
    r = RegistroTemas()
    r.agregar("Theia formo Luna", fecha="2026-01-01")
    resultado = tema_repetido("impacto de Theia formo Luna", [], r, ahora=date(2026, 2, 1))
    assert not resultado.aprobado


def test_alias_rechazado_y_tema_distinto_aprobado():
    r = RegistroTemas([{"tema_canonico": "El planeta Theia", "alias": ["impacto gigante"], "fecha": "2026-01-01"}])
    assert not tema_repetido("impacto gigante", [], r, ahora=date(2026, 1, 2)).aprobado
    assert tema_repetido("misiones a Marte", [], r, ahora=date(2026, 1, 2)).aprobado


def test_cooldown_vencido_y_angulo_nuevo():
    r = RegistroTemas([{"tema_canonico": "Theia y la Luna", "fecha": "2025-01-01"}])
    vencido = tema_repetido("Theia y la Luna", [], r, ahora=date(2026, 1, 1))
    assert vencido.aprobado and "tema_reusable_con_nuevo_angulo" in vencido.motivos
    reciente = tema_repetido("Theia y la Luna", [], r, ahora=date(2025, 2, 1), angulo_nuevo=True)
    assert reciente.aprobado and "angulo_nuevo" in reciente.motivos
    temprano = tema_repetido("Theia y la Luna", [], r, ahora=date(2025, 1, 20), angulo_nuevo=True)
    assert not temprano.aprobado


def test_short_derivado_permitido():
    r = RegistroTemas([{"tema_canonico": "Theia", "fecha": "2026-01-01", "video_key": "largo-1"}])
    assert tema_repetido("Theia", [], r, ahora=date(2026, 1, 2), video_origen="largo-1").aprobado


def test_shorts_hermanos_del_mismo_largo_permitidos():
    r = RegistroTemas([{"tema_canonico": "Theia", "fecha": "2026-01-01",
                        "video_key": "short-1", "video_origen": "largo-1"}])
    assert tema_repetido("Theia", [], r, ahora=date(2026, 1, 2),
                         video_origen="largo-1").aprobado


def test_mismo_caso_id_rechaza_redaccion_distinta():
    r = RegistroTemas([{"tema_canonico": "La formación lunar", "caso_id": "theia",
                        "fecha": "2026-01-01"}])
    assert not tema_repetido("Colisión que originó la Luna", [], r,
                             ahora=date(2026, 1, 2), caso_id="theia").aprobado


def test_caso_id_distinto_sigue_evaluando_texto():
    r = RegistroTemas([{"tema_canonico": "impacto de Theia en la Luna", "caso_id": "theia",
                        "fecha": "2026-01-01"}])
    assert not tema_repetido("impacto de Theia sobre la Luna", [], r,
                             ahora=date(2026, 1, 2), caso_id="otro").aprobado


def test_persistencia_y_tildes(tmp_path):
    ruta = tmp_path / "temas.json"
    RegistroTemas(ruta=ruta).agregar("La teoría del núcleo", ["núcleo terrestre"], fecha="2026-01-01")
    r = RegistroTemas(ruta=ruta)
    assert len(r) == 1
    assert normalizar_tema("¿Qué ocurrió en el núcleo terrestre?") == "ocurrio nucleo terrestre"
    assert not tema_repetido("nucleo terrestre", [], r, ahora=date(2026, 1, 2)).aprobado
