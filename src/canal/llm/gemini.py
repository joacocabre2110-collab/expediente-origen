"""Cliente Gemini REST, basado exclusivamente en urllib."""

from __future__ import annotations

import json as json_lib
import random
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Mapping


class ErrorGemini(RuntimeError):
    """Error de petición o respuesta de Gemini sin datos sensibles."""


class CuotaAgotada(ErrorGemini):
    """Todos los modelos configurados están fuera de cuota hasta el reinicio."""


class ServicioGeminiNoDisponible(ErrorGemini):
    """Todos los modelos están temporalmente degradados o fuera de servicio."""


class ClienteGemini:
    def __init__(self, clave_path: str | Path, modelos: Mapping[str, str],
                 pausa_min_s: float = 7, reintentos: int = 5,
                 sleep: Callable[[float], None] = time.sleep,
                 abrir: Callable = urllib.request.urlopen,
                 registrar_uso: Callable[[str, int, int], None] | None = None,
                 reloj: Callable[[], float] = time.monotonic,
                 jitter: Callable[[float], float] | None = None,
                 ruta_estado: str | Path | None = None,
                 reloj_fecha: Callable[[], datetime] | None = None) -> None:
        if pausa_min_s < 0 or reintentos < 0:
            raise ValueError("pausa_min_s y reintentos deben ser no negativos")
        self.clave_path, self.modelos = Path(clave_path), dict(modelos)
        self.pausa_min_s, self.reintentos = pausa_min_s, reintentos
        self.sleep, self.abrir, self.registrar_uso = sleep, abrir, registrar_uso
        self.reloj, self.jitter = reloj, jitter or (lambda techo: random.uniform(0, techo))
        self.ruta_estado = Path(ruta_estado) if ruta_estado else None
        self.reloj_fecha = reloj_fecha or (lambda: datetime.now(timezone.utc))
        self._ultima_llamada: float | None = None

    def generar(self, modelo_rol: str, prompt: str, sistema: str | None = None,
                max_tokens: int = 2048, temperatura: float = 0.7,
                json: bool = False, razonamiento: int = 1024) -> str:
        valor = self.modelos.get(modelo_rol, self.modelos.get("guion") if modelo_rol == "tema" else modelo_rol)
        modelos = [valor] if isinstance(valor, str) else list(valor or [])
        if not modelos:
            raise ErrorGemini(f"No hay modelo configurado para el rol {modelo_rol!r}")
        try:
            clave = self.clave_path.read_text(encoding="utf-8").strip()
        except OSError:
            raise ErrorGemini("No se pudo leer la clave de Gemini") from None
        if not clave:
            raise ErrorGemini("El archivo de clave de Gemini está vacío")
        body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"maxOutputTokens": max_tokens + max(0, razonamiento), "temperature": temperatura,
                                           "thinkingConfig": {"thinkingBudget": max(0, razonamiento)}}}
        if sistema:
            body["systemInstruction"] = {"parts": [{"text": sistema}]}
        if json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        data = json_lib.dumps(body).encode("utf-8")
        estado = self._leer_estado()
        disponibles = [m for m in modelos if not self._agotado(estado, m) and not self._no_disponible(estado, m) and not self._degradado(estado, m)]
        if not disponibles:
            if any(self._agotado(estado, m) for m in modelos):
                hasta = min((self._fecha_estado(estado, "agotados", m) for m in modelos if self._agotado(estado, m)), default=self._reinicio())
                raise CuotaAgotada(f"Cuota de Gemini agotada para {modelo_rol}; reinicio estimado {hasta.isoformat()}")
            reintento = min((self._fecha_estado(estado, grupo, m) for grupo in ("no_disponibles", "degradados") for m in modelos if self._fecha_estado(estado, grupo, m)), default=self.reloj_fecha() + timedelta(minutes=10))
            raise ServicioGeminiNoDisponible(f"Servicio de Gemini no disponible para {modelo_rol}; reintento estimado {reintento.isoformat()}")
        ultimo_error = None
        for modelo in disponibles:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
            cambiar_modelo = False
            for intento in range(self.reintentos + 1):
                if self._ultima_llamada is not None:
                    espera = self.pausa_min_s - (self.reloj() - self._ultima_llamada)
                    if espera > 0:
                        self.sleep(espera)
                self._ultima_llamada = self.reloj()
                self._contar(estado, modelo)
                req = urllib.request.Request(url, data=data, headers={
                    "Content-Type": "application/json", "x-goog-api-key": clave,
                }, method="POST")
                try:
                    with self.abrir(req, timeout=60) as response:
                        raw = response.read()
                    payload = json_lib.loads(raw.decode("utf-8"))
                    self._registrar(modelo, payload)
                    candidatos = payload.get("candidates") or []
                    if not candidatos:
                        razon = payload.get("promptFeedback", {}).get("blockReason", "sin candidatos")
                        raise ErrorGemini(f"Gemini no devolvió contenido: {razon}")
                    candidate = candidatos[0]
                    partes = candidate.get("content", {}).get("parts") or []
                    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
                    if candidate.get("finishReason") == "MAX_TOKENS":
                        raise ErrorGemini("Gemini cortó la respuesta por límite de tokens (MAX_TOKENS)")
                    if not texto.strip():
                        razon = candidate.get("finishReason", "respuesta vacía")
                        raise ErrorGemini(f"Gemini devolvió contenido vacío o bloqueado ({razon})")
                    return texto.strip()
                except urllib.error.HTTPError as exc:
                    codigo = exc.code
                    try: detalle = exc.read().decode("utf-8", "ignore").lower()
                    except Exception: detalle = ""
                    diario = codigo == 429 and ("quota" in detalle or "resource_exhausted" in detalle or "per day" in detalle or "daily" in detalle)
                    if diario or codigo == 404:
                        if diario: self._marcar_agotado(estado, modelo)
                        else: self._marcar_no_disponible(estado, modelo)
                        ultimo_error = ErrorGemini(f"Modelo Gemini no disponible ({codigo})")
                        cambiar_modelo = True
                        break
                    if codigo in (500, 502, 503, 504):
                        if intento < min(self.reintentos, 2):
                            self.sleep(2 ** intento + self.jitter(1.0))
                            continue
                        self._marcar_degradado(estado, modelo)
                        ultimo_error = ErrorGemini(f"Servicio de Gemini temporalmente degradado ({codigo})")
                        cambiar_modelo = True
                        break
                    if codigo != 429 or intento >= self.reintentos:
                        raise ErrorGemini(f"Error HTTP de Gemini ({codigo})") from None
                    self.sleep(2 ** intento + self.jitter(1.0))
                except (TimeoutError, urllib.error.URLError) as exc:
                    if isinstance(exc, urllib.error.URLError) and not isinstance(exc.reason, TimeoutError):
                        raise ErrorGemini("No se pudo conectar con Gemini") from None
                    if intento >= self.reintentos:
                        raise ErrorGemini("Gemini agotó los reintentos por timeout") from None
                    self.sleep(2 ** intento + self.jitter(1.0))
                except ErrorGemini:
                    raise
                except (ValueError, UnicodeError, KeyError, TypeError):
                    raise ErrorGemini("Respuesta JSON inválida de Gemini") from None
            if not cambiar_modelo:
                raise ultimo_error or ErrorGemini("Gemini agotó los reintentos")
        final = self._leer_estado()
        if all(self._agotado(final, m) or self._no_disponible(final, m) or self._degradado(final, m) for m in modelos):
            if any(self._agotado(final, m) for m in modelos):
                raise CuotaAgotada(f"Sin modelos disponibles para {modelo_rol}; reinicio estimado {self._reinicio().isoformat()}")
            raise ServicioGeminiNoDisponible(f"Servicio de Gemini no disponible para {modelo_rol}; reintento estimado {self._proximo_reintento(final, modelos).isoformat()}")
        raise ultimo_error or ErrorGemini("Gemini agotó los reintentos")

    def _reinicio(self) -> datetime:
        now = self.reloj_fecha().astimezone(ZoneInfo("America/Los_Angeles"))
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    def _leer_estado(self) -> dict:
        if not self.ruta_estado: return {"agotados": {}, "no_disponibles": {}, "degradados": {}, "requests": {}}
        try: return json_lib.loads(self.ruta_estado.read_text(encoding="utf-8"))
        except (OSError, ValueError): return {"agotados": {}, "no_disponibles": {}, "degradados": {}, "requests": {}}

    def _fecha_estado(self, estado: dict, grupo: str, modelo: str) -> datetime | None:
        hasta = estado.get(grupo, {}).get(modelo)
        return datetime.fromisoformat(hasta) if hasta else None

    def _proximo_reintento(self, estado: dict, modelos: list[str]) -> datetime:
        fechas = [self._fecha_estado(estado, grupo, modelo) for grupo in ("agotados", "no_disponibles", "degradados") for modelo in modelos]
        return min((f for f in fechas if f is not None), default=self.reloj_fecha() + timedelta(minutes=10))

    def _guardar_estado(self, estado: dict) -> None:
        if self.ruta_estado:
            self.ruta_estado.parent.mkdir(parents=True, exist_ok=True)
            self.ruta_estado.write_text(json_lib.dumps(estado, indent=2), encoding="utf-8")

    def _agotado(self, estado: dict, modelo: str) -> bool:
        hasta = estado.get("agotados", {}).get(modelo)
        if not hasta: return False
        if self.reloj_fecha().astimezone(ZoneInfo("America/Los_Angeles")) < datetime.fromisoformat(hasta): return True
        estado["agotados"].pop(modelo, None); self._guardar_estado(estado)
        return False

    def _marcar_agotado(self, estado: dict, modelo: str) -> None:
        estado.setdefault("agotados", {})[modelo] = self._reinicio().isoformat()
        self._guardar_estado(estado)

    def _no_disponible(self, estado: dict, modelo: str) -> bool:
        hasta = estado.get("no_disponibles", {}).get(modelo)
        if not hasta: return False
        if self.reloj_fecha().astimezone(ZoneInfo("America/Los_Angeles")) < datetime.fromisoformat(hasta): return True
        estado["no_disponibles"].pop(modelo, None); self._guardar_estado(estado)
        return False

    def _marcar_no_disponible(self, estado: dict, modelo: str) -> None:
        estado.setdefault("no_disponibles", {})[modelo] = self._reinicio().isoformat()
        self._guardar_estado(estado)

    def _degradado(self, estado: dict, modelo: str) -> bool:
        hasta = estado.get("degradados", {}).get(modelo)
        if not hasta: return False
        if self.reloj_fecha() < datetime.fromisoformat(hasta): return True
        estado["degradados"].pop(modelo, None); self._guardar_estado(estado)
        return False

    def _marcar_degradado(self, estado: dict, modelo: str) -> None:
        estado.setdefault("degradados", {})[modelo] = (self.reloj_fecha() + timedelta(minutes=10)).isoformat()
        self._guardar_estado(estado)

    def _contar(self, estado: dict, modelo: str) -> None:
        dia = self.reloj_fecha().astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
        requests = estado.setdefault("requests", {}).setdefault(dia, {})
        requests[modelo] = requests.get(modelo, 0) + 1
        self._guardar_estado(estado)

    def _registrar(self, modelo: str, payload: dict) -> None:
        if self.registrar_uso is None:
            return
        uso = payload.get("usageMetadata") or {}
        self.registrar_uso(modelo, int(uso.get("promptTokenCount", 0)),
                           int(uso.get("candidatesTokenCount", 0)))
