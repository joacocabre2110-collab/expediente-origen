"""Ejecución de las etapas de producción del pipeline."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from canal.alerts import Alerta, Nivel
from canal.dedupe import Guion as GuionHistorial, evaluar, tema_repetido
from .etapas import ContextoVideo
from canal.youtube import ClienteSeguro, EstadoVideo, SolicitudSubida, subir_idempotente
from canal.quota import Video, planificar_subidas, dias_de_reserva, necesita_reponer

ETAPAS_PRODUCCION = ("tema", "guion", "verificacion", "narracion", "render", "qa", "miniatura", "subida", "verificacion_post")
_COSTOS = {"narracion": "narracion", "render": "render", "miniatura": "miniatura"}


@dataclass(frozen=True)
class ResultadoPaso:
    estado: str
    video_key: str | None = None
    etapa: str | None = None
    detalle: str | None = None


class Orquestador:
    def __init__(self, cola: Any, ledger: Any, notificador: Any, historial: Any,
                 registro_temas: Any, etapas: Any, directorio_base: str | Path,
                 cliente: ClienteSeguro,
                 reloj: Callable[[], Any] = date.today):
        if not isinstance(cliente, ClienteSeguro):
            raise TypeError("cliente debe ser instancia de ClienteSeguro")
        if cliente.publicacion_publica_habilitada:
            raise ValueError("La publicación pública está prohibida en esta fase; solo se habilita mediante un cambio deliberado posterior a la autorización del usuario.")
        self.cola, self.ledger, self.notificador = cola, ledger, notificador
        self.cliente = cliente
        self.historial, self.registro_temas, self.etapas = historial, registro_temas, etapas
        self.directorio_base = Path(directorio_base)
        self.reloj = reloj

    def _alerta(self, asunto: str, cuerpo: str, video_key: str | None = None) -> None:
        self.notificador.notificar(Alerta(Nivel.CRITICO, asunto, cuerpo, video_key))

    def _estado_path(self, key: str) -> Path:
        return self.directorio_base / key / "estado.json"

    def _leer(self, key: str) -> dict[str, Any]:
        path = self._estado_path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @staticmethod
    def _plain(value: Any) -> Any:
        if is_dataclass(value):
            return {k: Orquestador._plain(v) for k, v in asdict(value).items()}
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: Orquestador._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [Orquestador._plain(v) for v in value]
        return value

    def _guardar(self, key: str, state: dict[str, Any]) -> None:
        path = self._estado_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporal = path.with_name(path.name + ".tmp")
        temporal.write_text(json.dumps(self._plain(state), ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(path)

    def _contexto(self, key: str) -> ContextoVideo:
        state = self._leer(key)
        tipo = state.get("tipo", "largo")
        origen = state.get("video_origen")
        fecha = self.reloj()
        if isinstance(fecha, datetime):
            fecha = fecha.date()
        return ContextoVideo(key, tipo, fecha, self.directorio_base / key, origen)

    def _generador(self, etapa: str) -> Any:
        nombres = {"tema": ("tema", "generador_tema"), "guion": ("guion", "generador_guion"),
                   "verificacion": ("verificacion", "verificador"), "narracion": ("narracion", "narrador"),
                   "render": ("render", "renderizador"), "qa": ("qa", "control_calidad"),
                   "miniatura": ("miniatura", "generador_miniatura"),
                   "subida": ("generador_metadatos", "metadatos"), "verificacion_post": ()}
        for name in nombres[etapa]:
            if hasattr(self.etapas, name):
                return getattr(self.etapas, name)
        raise AttributeError(f"Falta generador para etapa {etapa}")

    def _run(self, etapa: str, ctx: ContextoVideo, s: dict[str, Any], key: str) -> tuple[Any, str | None]:
        gen = self._generador(etapa)
        tema = s.get("tema")
        # Rehidrata los contratos de datos usados como entradas entre procesos.
        from .etapas import Tema, Guion, ResultadoVerificacion, Narracion, Render, ResultadoQA, Miniatura, Metadatos
        def obj(name, cls):
            value = s.get(name)
            if value is None: return None
            value = dict(value)
            if cls is Narracion and value.get("ruta_audio") is not None:
                value["ruta_audio"] = Path(value["ruta_audio"])
            if cls is Render and value.get("ruta_video") is not None:
                value["ruta_video"] = Path(value["ruta_video"])
            if cls is Miniatura and value.get("ruta") is not None:
                value["ruta"] = Path(value["ruta"])
            return cls(**value)
        tema = obj("tema", Tema)
        guion = obj("guion", Guion)
        ver = obj("verificacion", ResultadoVerificacion)
        narr = obj("narracion", Narracion)
        rend = obj("render", Render)
        qa = obj("qa", ResultadoQA)
        miniatura = obj("miniatura", Miniatura)
        if etapa == "tema":
            motivos = []
            for _ in range(3):
                result = gen.generar(ctx)
                check = tema_repetido(result.titulo, result.alias, self.registro_temas,
                    ahora=ctx.fecha_publicacion, caso_id=result.caso_id,
                    video_origen=ctx.video_origen or "", video_key=key)
                if check.aprobado:
                    return result, None
                motivos = check.motivos
            return None, ",".join(motivos) or "tema_repetido"
        if etapa == "guion":
            motivos = []
            for _ in range(3):
                result = gen.generar(ctx, tema)
                tipo = "short" if key.startswith("short-") else "largo"
                origen = ctx.video_origen
                candidato = GuionHistorial(key, result.pilar, result.estructura, result.gancho, result.intro, result.texto)
                # Mantener todo el historial para similitud, pero ejecutar la rotación
                # narrativa sobre largos. Un short derivado ignora su largo de origen.
                historial = []
                for previo in self.historial:
                    previo_key = previo.video_key if hasattr(previo, "video_key") else previo.get("video_key", "")
                    previo_tipo = "short" if previo_key.startswith("short-") else "largo"
                    pilar = previo.pilar if hasattr(previo, "pilar") else previo.get("pilar", "")
                    estructura = previo.estructura if hasattr(previo, "estructura") else previo.get("estructura", "")
                    if tipo == "short":
                        if previo_key == origen:
                            pilar, estructura = "", f"origen-{previo_key}"
                        else:
                            pilar = ""  # los shorts no participan de la rotación de pilares
                    elif previo_tipo == "short":
                        pilar, estructura = "", f"short-{previo_key}"
                    historial.append({"video_key": previo_key, "pilar": pilar, "estructura": estructura,
                                      "gancho": previo.gancho if hasattr(previo, "gancho") else previo.get("gancho", ""),
                                      "intro": previo.intro if hasattr(previo, "intro") else previo.get("intro", ""),
                                      "texto": previo.texto if hasattr(previo, "texto") else previo.get("texto", "")})
                if tipo == "short":
                    candidato.pilar = ""
                    candidato.estructura = f"short-{key}"
                check = evaluar(candidato, historial)
                if check.aprobado:
                    return result, None
                motivos = check.motivos
            return None, ",".join(motivos) or "guion_rechazado"
        if etapa == "verificacion":
            brief = None
            if s.get("brief"):
                from canal.investigacion.brief import Brief, Fragmento
                brief = Brief(s["brief"]["tema"], tuple(Fragmento(**f) for f in s["brief"]["fragmentos"]))
            try:
                result = gen.verificar(ctx, tema, guion, brief) if brief is not None else gen.verificar(ctx, tema, guion)
            except TypeError:
                result = gen.verificar(ctx, tema, guion)
            return (result, None) if result.aprobado else (None, ",".join(result.motivos) or "verificacion_rechazada")
        if etapa == "narracion": return gen.narrar(ctx, tema, guion, ver), None
        if etapa == "render":
            if hasattr(gen, "preparar_imagenes"):
                estado = gen.preparar_imagenes(ctx, tema, s)
                s["imagenes_estado"] = estado
                s["imagenes_disponibles"] = [self._plain(i) for i in (gen.imagenes or [])]
                self._guardar(key, s)
            resultado = gen.renderizar(ctx, tema, guion, narr)
            if hasattr(gen, "imagenes_usadas"):
                s["imagenes_usadas"] = [self._plain(i) for i in gen.imagenes_usadas]
            return resultado, None
        if etapa == "qa":
            result = gen.controlar(ctx, tema, guion, narr, rend)
            return (result, None) if result.aprobado else (None, ",".join(result.motivos) or "qa_rechazado")
        if etapa == "miniatura": return gen.generar(ctx, tema, guion, rend, qa), None
        if etapa == "subida":
            if hasattr(gen, "imagenes"):
                from canal.investigacion.imagenes import ImagenLibre
                gen.imagenes = [ImagenLibre(**i) for i in s.get("imagenes_usadas", [])]
            return gen.generar(ctx, tema, guion, rend, miniatura), None
        raise ValueError(etapa)

    def ejecutar_siguiente(self) -> ResultadoPaso:
        tarea = self.cola.reclamar(etapas=ETAPAS_PRODUCCION)
        if tarea is None:
            return ResultadoPaso("sin_tareas")
        if tarea.etapa in _COSTOS and not self.ledger.puede_producir():
            self.cola.liberar(tarea.id)
            if self.ledger.aviso_pendiente():
                self._alerta("Presupuesto agotado", "La producción se pausó por presupuesto.", tarea.video_key)
            return ResultadoPaso("pausado_presupuesto", tarea.video_key, tarea.etapa)
        try:
            s = self._leer(tarea.video_key)
            ctx = self._contexto(tarea.video_key)
            if tarea.etapa == "subida":
                from .etapas import Render, Miniatura
                metadata, rechazo = self._run("subida", ctx, s, tarea.video_key)
                if rechazo:
                    raise RuntimeError(rechazo)
                render = Render(**{**s["render"], "ruta_video": Path(s["render"]["ruta_video"])})
                mini = Miniatura(**{**s["miniatura"], "ruta": Path(s["miniatura"]["ruta"])})
                solicitud = SolicitudSubida(tarea.video_key, metadata.titulo, metadata.descripcion,
                    metadata.etiquetas, str(render.ruta_video), str(mini.ruta), "private", None,
                    ctx.tipo == "short")
                subir_idempotente(self.cliente, self.cola, solicitud)
                self.cola.completar(tarea.id)
                return ResultadoPaso("ok", tarea.video_key, tarea.etapa)
            if tarea.etapa == "verificacion_post":
                youtube_id = self.cola.publicacion(tarea.video_key)
                if youtube_id is None:
                    raise RuntimeError("No hay publicación registrada para verificar")
                estado = self.cliente.verificar(youtube_id)
                if estado == EstadoVideo.PROCESANDO:
                    ahora = float(self.cola.reloj())
                    inicio = s.setdefault("verificacion_post_inicio", ahora)
                    transcurrido = max(0.0, ahora - float(inicio))
                    if transcurrido >= 3600:
                        motivo = "Video sigue procesando después de 1 hora"
                        final = self.cola.fallo_definitivo(tarea.id, motivo)
                        if final.estado == "fallido":
                            self._alerta("Fallo definitivo de verificación", motivo, tarea.video_key)
                            return ResultadoPaso("fallido", tarea.video_key, tarea.etapa, motivo)
                        return ResultadoPaso("reintento", tarea.video_key, tarea.etapa, motivo)
                    intervalos = (120, 300, 600, 1200)
                    numero = int(s.get("verificacion_post_reintentos", 0))
                    demora = intervalos[min(numero, len(intervalos) - 1)]
                    demora = min(demora, max(1, 3600 - transcurrido))
                    s["verificacion_post_reintentos"] = numero + 1
                    self._guardar(tarea.video_key, s)
                    motivo = f"Video sigue procesando; próximo intento en {int(demora // 60)} min"
                    self.cola.reintentar_programado(tarea.id, motivo, demora)
                    return ResultadoPaso("reintento", tarea.video_key, tarea.etapa, motivo)
                if estado != EstadoVideo.DISPONIBLE:
                    motivo = f"Video no disponible: {estado}"
                    final = self.cola.fallar(tarea.id, motivo)
                    if final.estado == "fallido":
                        self._alerta("Fallo definitivo de verificación", final.ultimo_error or "Video no disponible", tarea.video_key)
                        return ResultadoPaso("fallido", tarea.video_key, tarea.etapa, final.ultimo_error)
                    return ResultadoPaso("reintento", tarea.video_key, tarea.etapa, str(estado))
                s["youtube_id"] = youtube_id
                s["verificacion_post"] = estado.value
                s.pop("verificacion_post_inicio", None)
                s.pop("verificacion_post_reintentos", None)
                self._guardar(tarea.video_key, s)
                self.cola.completar(tarea.id)
                return ResultadoPaso("ok", tarea.video_key, tarea.etapa)
            result, rechazo = self._run(tarea.etapa, ctx, s, tarea.video_key)
            if rechazo:
                self.cola.apartar(tarea.video_key, rechazo)
                asunto = "Tema apartado" if tarea.etapa == "tema" else f"{tarea.etapa} rechazado"
                self._alerta(asunto, rechazo, tarea.video_key)
                return ResultadoPaso("apartado", tarea.video_key, tarea.etapa, rechazo)
            if tarea.etapa == "guion":
                s["guion"] = self._plain(result)
                gen = self._generador("guion")
                brief = getattr(gen, "_brief", None)
                if brief is not None:
                    s["brief"] = self._plain(brief)
                    path = Path(ctx.directorio_trabajo) / "brief.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(s["brief"], ensure_ascii=False, indent=2), encoding="utf-8")
                self.historial.agregar(GuionHistorial(tarea.video_key, result.pilar, result.estructura, result.gancho, result.intro, result.texto))
            elif tarea.etapa == "render":
                s["render"] = self._plain(result)
            else:
                s[tarea.etapa] = self._plain(result)
            if tarea.etapa == "tema":
                tema = self._plain(result)
                self.registro_temas.agregar(tema.get("titulo", ""), tema.get("alias", []), tema.get("pilar", ""),
                    fecha=ctx.fecha_publicacion, video_key=tarea.video_key, video_origen=ctx.video_origen or "", caso_id=tema.get("caso_id", ""))
            self._guardar(tarea.video_key, s)
            if tarea.etapa in _COSTOS:
                self.ledger.registrar_gasto(_COSTOS[tarea.etapa], result.costo_usd, tarea.video_key)
            self.cola.completar(tarea.id)
            return ResultadoPaso("ok", tarea.video_key, tarea.etapa)
        except Exception as exc:
            from canal.llm.gemini import CuotaAgotada, ServicioGeminiNoDisponible
            if isinstance(exc, (ServicioGeminiNoDisponible, CuotaAgotada)):
                ahora = float(self.cola.reloj())
                inicio = float(s.get("gemini_reintento_inicio", ahora))
                transcurrido = max(0.0, ahora - inicio)
                if transcurrido >= 6 * 3600:
                    final = self.cola.fallo_definitivo(tarea.id, str(exc))
                    if final.estado == "fallido":
                        self._alerta("Fallo definitivo de producción", str(exc), tarea.video_key)
                        return ResultadoPaso("fallido", tarea.video_key, tarea.etapa, str(exc))
                else:
                    pausas = (300, 600, 1200, 1800)
                    numero = int(s.get("gemini_reintentos_diferidos", 0))
                    demora = min(pausas[min(numero, len(pausas) - 1)], max(1, 6 * 3600 - transcurrido))
                    s["gemini_reintento_inicio"] = inicio
                    s["gemini_reintentos_diferidos"] = numero + 1
                    self._guardar(tarea.video_key, s)
                    motivo = f"{exc}; reintento diferido en {int(demora // 60)} min"
                    self.cola.reintentar_programado(tarea.id, motivo, demora)
                    return ResultadoPaso("reintento", tarea.video_key, tarea.etapa, motivo)
            final = self.cola.fallar(tarea.id, str(exc))
            if final.estado == "fallido":
                self._alerta("Fallo definitivo de producción", str(exc), tarea.video_key)
                return ResultadoPaso("fallido", tarea.video_key, tarea.etapa, str(exc))
            return ResultadoPaso("reintento", tarea.video_key, tarea.etapa, str(exc))

    def ejecutar_hasta_vaciar(self, max_pasos: int = 1000) -> list[ResultadoPaso]:
        resultados = []
        for _ in range(max_pasos):
            resultado = self.ejecutar_siguiente()
            resultados.append(resultado)
            if resultado.estado in ("sin_tareas", "pausado_presupuesto"):
                break
        return resultados

    def programar_dia(self, fecha: date) -> Any:
        """Encola un largo y tres shorts; quedan privados hasta una autorización futura."""
        videos = [Video(f"largo-{fecha.isoformat()}")] + [
            Video(f"short-{fecha.isoformat()}-{i}", "short") for i in range(1, 4)]
        origen = videos[0].video_key
        for video in videos:
            state = self._leer(video.video_key)
            state.update(tipo=video.tipo, video_origen=origen if video.tipo == "short" else None,
                         fecha=fecha.isoformat())
            # Fecha planificada solo vive en estado.json; no se pasa a SolicitudSubida.
            self._guardar(video.video_key, state)
        ahora = self.reloj()
        if isinstance(ahora, date) and not isinstance(ahora, datetime):
            ahora = datetime.combine(ahora, datetime.min.time()).astimezone()
        plan = planificar_subidas(videos, fecha, ahora=ahora if isinstance(ahora, datetime) else None)
        by_key = {p.video_key: p for p in plan.publicaciones}
        for video in videos:
            state = self._leer(video.video_key)
            state["publicacion_planificada"] = by_key[video.video_key].fecha_publicacion.isoformat() if video.video_key in by_key else None
            self._guardar(video.video_key, state)
            for etapa in ETAPAS_PRODUCCION:
                self.cola.encolar(video.video_key, etapa)
        return plan

    def estado_reserva(self, hoy: date) -> dict[str, Any]:
        publicaciones = []
        for path in self.directorio_base.glob("*/estado.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            valor = state.get("publicacion_planificada")
            if valor:
                dt = datetime.fromisoformat(valor)
                from canal.quota import Publicacion
                publicaciones.append(Publicacion(path.parent.name, dt, dt.date()))
        return {"dias": dias_de_reserva(publicaciones, hoy),
                "necesita_reponer": necesita_reponer(publicaciones, hoy)}
