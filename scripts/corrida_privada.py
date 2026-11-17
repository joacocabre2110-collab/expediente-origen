#!/usr/bin/env python3
"""Corrida completa de UN video, siempre PRIVADO (nunca público ni programado).

Uso: PYTHONPATH=src .venv/bin/python scripts/corrida_privada.py --tipo short [--dry-run] [--max-costo-usd 0.25]
"""
import argparse
import sys
import os
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from canal.app import construir_orquestador  # noqa: E402
from canal.pipeline.orquestador import ETAPAS_PRODUCCION  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", choices=("short", "largo"), default="short")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-costo-usd", type=float, default=None)
    ap.add_argument("--reanudar", default=None, help="video_key de una corrida previa a reanudar (no repite lo ya hecho)")
    ap.add_argument("--datos", default=None, help="directorio de datos (por defecto datos_corrida/<modo>)")
    a = ap.parse_args()
    tope = a.max_costo_usd if a.max_costo_usd is not None else (0.25 if a.tipo == "short" else 1.0)
    modo = "dry-run" if a.dry_run else "real"
    datos = Path(a.datos) if a.datos else Path(os.environ.get("CANAL_DATOS_DIR", RAIZ / "datos_corrida" / modo))
    e = construir_orquestador(os.environ.get("CANAL_CONFIG_PATH", RAIZ / "config.toml"), datos, modo)
    for adv in e.advertencias:
        print("AVISO:", adv)
    hoy = date.today().isoformat()
    orq = e.orquestador
    if a.reanudar:
        key = a.reanudar
    else:
        key = f"{a.tipo}-{hoy}-{int(time.time())}"
        estado = orq._leer(key)
        estado.update(tipo=a.tipo, fecha=hoy, video_origen=None)
        orq._guardar(key, estado)
        for etapa in ETAPAS_PRODUCCION:
            e.cola.encolar(key, etapa)
    print(f"Corrida {modo} | {key} | tope de costo {tope} USD | publicación pública: BLOQUEADA")
    vacias = 0
    for _ in range(len(ETAPAS_PRODUCCION) * 4):
        t0 = time.time()
        r = orq.ejecutar_siguiente()
        if r.estado == "sin_tareas":
            vacias += 1
            if vacias > 4:
                break
            time.sleep(3)  # una tarea en reintento puede estar en espera de backoff
            continue
        vacias = 0
        gasto = e.ledger.costo_por_video(key)
        print(f"  {r.etapa or '-':18} {r.estado:12} {time.time()-t0:6.1f}s  costo acumulado {gasto:.4f} USD" + (f"  | {r.detalle}" if r.detalle else ""))
        if gasto > tope:
            print(f"ABORTADO: el costo {gasto:.4f} superó el tope {tope} USD")
            return 2
        if r.estado not in ("ok", "reintento"):
            print("Corrida detenida en el estado:", r.estado)
            return 1
    estado = orq._leer(key)
    print("RESUMEN | costo:", f"{e.ledger.costo_por_video(key):.4f} USD", "| cuota YouTube usada:", e.cliente.unidades_cuota_consumidas, "| youtube_id:", estado.get("youtube_id") or estado.get("subida"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
