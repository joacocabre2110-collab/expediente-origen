"""Cliente abstracto y falso para integrar subidas a YouTube."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import random
import sqlite3
import time
from typing import Protocol

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


class EstadoVideo(str, Enum):
    DESCONOCIDO = "desconocido"
    PROCESANDO = "procesando"
    DISPONIBLE = "disponible"
    RECHAZADO = "rechazado"


@dataclass
class SolicitudSubida:
    video_key: str
    titulo: str
    descripcion: str
    etiquetas: list[str]
    ruta_video: str
    ruta_miniatura: str
    privacy_status: str
    publish_at: datetime | None
    es_short: bool

    def __post_init__(self) -> None:
        marker = f"[video_key:{self.video_key}]"
        if marker not in self.descripcion:
            self.descripcion = f"{self.descripcion.rstrip()}\n\n{marker}" if self.descripcion else marker
        if self.publish_at is not None and self.publish_at.utcoffset() is None:
            raise ValueError("publish_at debe incluir zona horaria")


class ClienteYouTube(Protocol):
    def buscar_por_video_key(self, video_key: str) -> str | None:
        """Busca un video por su marcador [video_key:...].

        Una implementación real NO debe usar search.list (100 unidades de
        cuota): debe listar la playlist de subidas del canal con
        playlistItems.list (~1 unidad) y comparar el marcador. ClienteSeguro
        debe ser la única forma de exponer un cliente real al resto del sistema.
        """
        ...

    def subir(self, solicitud: SolicitudSubida) -> str: ...

    def verificar(self, youtube_id: str) -> EstadoVideo: ...


class PublicacionBloqueada(Exception):
    """La configuración segura impide una publicación pública o programada."""


class FalloTransitorio(Exception):
    """Error temporal simulado por el cliente falso."""


class CuotaYouTubeAgotada(Exception):
    """YouTube respondió quotaExceeded; es un error no reintentable hoy."""


class ClienteYouTubeReal:
    """Adaptador YouTube Data API v3. Acepta un servicio falso para pruebas."""

    def __init__(self, servicio=None, *, dir_secretos="secrets", chunk_size=8 * 1024 * 1024,
                 max_reintentos=5, sleep=time.sleep, random_fn=random.random, cuota=None):
        if servicio is None:
            from googleapiclient.discovery import build
            from .auth import cargar_credenciales
            servicio = build("youtube", "v3", credentials=cargar_credenciales(dir_secretos), cache_discovery=False)
        self.servicio = servicio
        self.chunk_size = chunk_size
        self.max_reintentos = max_reintentos
        self.sleep = sleep
        self.random_fn = random_fn
        self.cuota = cuota
        self.unidades_cuota_consumidas = 0
        self._uploads_playlist = None

    def _registrar_cuota(self, operacion, unidades):
        self.unidades_cuota_consumidas += unidades
        if self.cuota is not None:
            self.cuota.registrar(operacion, unidades)

    @staticmethod
    def _es_quota(exc):
        contenido = getattr(exc, "content", b"")
        if isinstance(contenido, bytes):
            contenido = contenido.decode("utf-8", "ignore")
        return "quotaExceeded" in str(contenido)

    @staticmethod
    def _transitorio(exc):
        status = getattr(getattr(exc, "resp", None), "status", None)
        return status is None or status >= 500 or status in (408, 429)

    def _ejecutar(self, operacion, request):
        for intento in range(self.max_reintentos + 1):
            try:
                return request()
            except HttpError as exc:
                if self._es_quota(exc):
                    raise CuotaYouTubeAgotada("Cuota de YouTube agotada (quotaExceeded)") from exc
                if not self._transitorio(exc) or intento >= self.max_reintentos:
                    raise
            except (TimeoutError, ConnectionError, OSError):
                if intento >= self.max_reintentos:
                    raise
            self.sleep(min(64, 2 ** intento + self.random_fn()))

    def _pagina_playlist(self, **kwargs):
        return self._ejecutar("playlistItems.list", lambda: self.servicio.playlistItems().list(**kwargs).execute())

    def buscar_por_video_key(self, video_key):
        if self._uploads_playlist is None:
            canales = self._ejecutar("channels.list", lambda: self.servicio.channels().list(part="contentDetails", mine=True).execute())
            self._registrar_cuota("list", 1)
            items = canales.get("items", [])
            if not items:
                return None
            self._uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        token = None
        marker = f"ID-interno: {video_key}"
        while True:
            args = {"part": "snippet,contentDetails", "playlistId": self._uploads_playlist, "maxResults": 50}
            if token:
                args["pageToken"] = token
            data = self._pagina_playlist(**args)
            self._registrar_cuota("list", 1)
            for item in data.get("items", []):
                desc = item.get("snippet", {}).get("description", "")
                if marker in desc or f"[video_key:{video_key}]" in desc:
                    return item.get("contentDetails", {}).get("videoId") or item.get("snippet", {}).get("resourceId", {}).get("videoId")
            token = data.get("nextPageToken")
            if not token:
                return None

    def subir(self, solicitud: SolicitudSubida) -> str:
        descripcion = solicitud.descripcion.rstrip()
        marcador = f"ID-interno: {solicitud.video_key}"
        if marcador not in descripcion:
            descripcion = f"{descripcion}\n{marcador}" if descripcion else marcador
        cuerpo = {"snippet": {"title": solicitud.titulo, "description": descripcion,
                               "tags": solicitud.etiquetas, "categoryId": "22"},
                  "status": {"privacyStatus": solicitud.privacy_status, "selfDeclaredMadeForKids": False,
                             "containsSyntheticMedia": True}}
        if solicitud.publish_at is not None:
            cuerpo["status"]["publishAt"] = solicitud.publish_at.isoformat().replace("+00:00", "Z")
        media = MediaFileUpload(solicitud.ruta_video, chunksize=self.chunk_size, resumable=True)
        request = self.servicio.videos().insert(part="snippet,status", body=cuerpo, media_body=media)
        respuesta = None
        while respuesta is None:
            try:
                _, respuesta = self._ejecutar("videos.insert", request.next_chunk)
            except Exception as exc:
                if isinstance(exc, HttpError) and self._es_quota(exc):
                    raise CuotaYouTubeAgotada("Cuota de YouTube agotada (quotaExceeded)") from exc
                raise
        youtube_id = respuesta["id"]
        self._registrar_cuota("upload", 1600)
        if solicitud.ruta_miniatura:
            thumb = MediaFileUpload(solicitud.ruta_miniatura, resumable=False)
            self._ejecutar("thumbnails.set", lambda: self.servicio.thumbnails().set(videoId=youtube_id, media_body=thumb).execute())
            self._registrar_cuota("thumbnail", 50)
        return youtube_id

    def verificar(self, youtube_id):
        data = self._ejecutar("videos.list", lambda: self.servicio.videos().list(part="status,processingDetails", id=youtube_id).execute())
        self._registrar_cuota("list", 1)
        items = data.get("items", [])
        if not items:
            return EstadoVideo.DESCONOCIDO
        item = items[0]
        upload = item.get("status", {}).get("uploadStatus")
        processing = item.get("processingDetails", {}).get("processingStatus")
        if upload == "rejected":
            return EstadoVideo.RECHAZADO
        if upload == "processed" and processing in (None, "succeeded"):
            return EstadoVideo.DISPONIBLE
        return EstadoVideo.PROCESANDO

    def borrar(self, video_id):
        self._ejecutar("videos.delete", lambda: self.servicio.videos().delete(id=video_id).execute())
        self._registrar_cuota("delete", 50)


class ClienteFalso:
    """Almacén en memoria que permite ejercitar fallos y recuperación."""

    def __init__(self, fallos_transitorios: int = 0, fallar_despues_de_subir: bool = False) -> None:
        self.videos: dict[str, tuple[SolicitudSubida, EstadoVideo]] = {}
        self.fallos_transitorios = fallos_transitorios
        self.fallar_despues_de_subir = fallar_despues_de_subir
        self.intentos_subida = 0
        self._ids = 0

    def buscar_por_video_key(self, video_key: str) -> str | None:
        for youtube_id, (solicitud, _) in self.videos.items():
            if solicitud.video_key == video_key:
                return youtube_id
        return None

    def subir(self, solicitud: SolicitudSubida) -> str:
        self.intentos_subida += 1
        if self.fallos_transitorios:
            self.fallos_transitorios -= 1
            raise FalloTransitorio("Fallo transitorio de subida")
        self._ids += 1
        youtube_id = f"fake-{self._ids}"
        self.videos[youtube_id] = (solicitud, EstadoVideo.DISPONIBLE)
        if self.fallar_despues_de_subir:
            self.fallar_despues_de_subir = False
            raise FalloTransitorio("Fallo simulado después de subir")
        return youtube_id

    def verificar(self, youtube_id: str) -> EstadoVideo:
        item = self.videos.get(youtube_id)
        return item[1] if item else EstadoVideo.DESCONOCIDO


class ClienteSeguro:
    def __init__(self, cliente: ClienteYouTube, publicacion_publica_habilitada: bool = False) -> None:
        self.cliente = cliente
        self.publicacion_publica_habilitada = publicacion_publica_habilitada

    def buscar_por_video_key(self, video_key: str) -> str | None:
        return self.cliente.buscar_por_video_key(video_key)

    def subir(self, solicitud: SolicitudSubida) -> str:
        if not self.publicacion_publica_habilitada and (
            solicitud.privacy_status != "private" or solicitud.publish_at is not None
        ):
            raise PublicacionBloqueada("La publicación pública o programada está deshabilitada")
        return self.cliente.subir(solicitud)

    def verificar(self, youtube_id: str) -> EstadoVideo:
        return self.cliente.verificar(youtube_id)

    def borrar(self, youtube_id: str) -> None:
        return self.cliente.borrar(youtube_id)

    @property
    def unidades_cuota_consumidas(self) -> int:
        return int(getattr(self.cliente, "unidades_cuota_consumidas", 0))


def crear_cliente_seguro(
    cliente: ClienteYouTube, publicacion_publica_habilitada: bool = False
) -> ClienteSeguro:
    """Envuelve un cliente para aplicar las restricciones de publicación segura."""
    return ClienteSeguro(cliente, publicacion_publica_habilitada)


def subir_idempotente(cliente: ClienteYouTube, store_cola: object, solicitud: SolicitudSubida) -> str:
    """Busca un resultado previo antes de subir y registrar la publicación."""
    existente = cliente.buscar_por_video_key(solicitud.video_key)
    if existente is not None:
        try:
            getattr(store_cola, "registrar_publicacion")(solicitud.video_key, existente)
        except sqlite3.IntegrityError:
            pass
        return existente
    youtube_id = cliente.subir(solicitud)
    getattr(store_cola, "registrar_publicacion")(solicitud.video_key, youtube_id)
    return youtube_id
