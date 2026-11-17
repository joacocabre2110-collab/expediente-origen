from datetime import datetime, timezone

import pytest

from canal.queue import QueueStore
from canal.youtube import (
    ClienteFalso,
    ClienteSeguro,
    EstadoVideo,
    FalloTransitorio,
    PublicacionBloqueada,
    SolicitudSubida,
    crear_cliente_seguro,
    subir_idempotente,
)


def solicitud(**cambios):
    datos = dict(
        video_key="video-1",
        titulo="Título",
        descripcion="Descripción",
        etiquetas=["prueba"],
        ruta_video="video.mp4",
        ruta_miniatura="miniatura.jpg",
        privacy_status="private",
        publish_at=None,
        es_short=False,
    )
    datos.update(cambios)
    return SolicitudSubida(**datos)


@pytest.mark.parametrize("privacy", ["public", "unlisted"])
def test_seguro_bloquea_public_y_unlisted(privacy):
    cliente = ClienteFalso()
    with pytest.raises(PublicacionBloqueada):
        ClienteSeguro(cliente).subir(solicitud(privacy_status=privacy))
    assert cliente.intentos_subida == 0


def test_seguro_bloquea_publish_at_aunque_sea_private():
    with pytest.raises(PublicacionBloqueada):
        ClienteSeguro(ClienteFalso()).subir(
            solicitud(publish_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        )


def test_fabrica_segura_bloquea_public_y_publish_at_por_defecto():
    cliente = ClienteFalso()
    seguro = crear_cliente_seguro(cliente)
    with pytest.raises(PublicacionBloqueada):
        seguro.subir(solicitud(privacy_status="public"))
    with pytest.raises(PublicacionBloqueada):
        seguro.subir(solicitud(publish_at=datetime(2030, 1, 1, tzinfo=timezone.utc)))
    assert cliente.intentos_subida == 0


def test_seguro_permite_private_sin_programacion():
    assert ClienteSeguro(ClienteFalso()).subir(solicitud()).startswith("fake-")


def test_marcador_agregado_a_descripcion():
    req = solicitud()
    assert "[video_key:video-1]" in req.descripcion
    req2 = solicitud(descripcion="ya [video_key:video-1] está")
    assert req2.descripcion.count("[video_key:video-1]") == 1


def test_idempotencia_recupera_subida_tras_crash_sin_duplicar():
    q = QueueStore()
    for etapa in ("tema", "guion", "verificacion", "narracion", "render", "qa", "miniatura"):
        q.encolar("video-1", etapa)
        previa = q.reclamar()
        assert previa is not None and previa.etapa == etapa
        q.completar(previa.id)
    tarea = q.encolar("video-1", "subida")
    assert q.reclamar().id == tarea.id
    cliente = ClienteFalso(fallar_despues_de_subir=True)
    with pytest.raises(FalloTransitorio):
        subir_idempotente(cliente, q, solicitud())
    assert len(cliente.videos) == 1
    youtube_id = subir_idempotente(cliente, q, solicitud())
    assert youtube_id == "fake-1"
    assert len(cliente.videos) == 1
    assert q.subida_pendiente_de_verificar("video-1") is False


def test_video_existente_se_registra_aunque_no_haya_intentos_previos():
    q = QueueStore()
    cliente = ClienteFalso()
    youtube_id = cliente.subir(solicitud())

    assert subir_idempotente(cliente, q, solicitud()) == youtube_id
    assert cliente.intentos_subida == 1
    assert q.subida_pendiente_de_verificar("video-1") is False


def test_video_ya_registrado_no_falla_ni_duplica():
    q = QueueStore()
    cliente = ClienteFalso()
    youtube_id = cliente.subir(solicitud())
    q.registrar_publicacion("video-1", youtube_id)

    assert subir_idempotente(cliente, q, solicitud()) == youtube_id
    assert cliente.intentos_subida == 1


def test_reintenta_fallo_transitorio():
    q = QueueStore()
    cliente = ClienteFalso(fallos_transitorios=1)
    with pytest.raises(FalloTransitorio):
        subir_idempotente(cliente, q, solicitud())
    assert subir_idempotente(cliente, q, solicitud()) == "fake-1"
    assert cliente.intentos_subida == 2


def test_verificar_devuelve_estado():
    cliente = ClienteFalso()
    youtube_id = cliente.subir(solicitud())
    assert cliente.verificar(youtube_id) is EstadoVideo.DISPONIBLE
    assert cliente.verificar("inexistente") is EstadoVideo.DESCONOCIDO
