#!/usr/bin/env python3
"""Ejecuta el ciclo diario privado del canal."""
import argparse
import sys
import os
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from canal.app import construir_orquestador  # noqa: E402
from canal.scheduler import ejecutar_ciclo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    ap.add_argument("--datos", default=None)
    ap.add_argument("--max-pasos", type=int, default=1000)
    ap.add_argument("--presupuesto-dia-usd", type=float, default=10.0)
    args = ap.parse_args()
    modo = "dry-run" if args.dry_run else "real"
    datos = Path(args.datos) if args.datos else Path(os.environ.get("CANAL_DATOS_DIR", RAIZ / "datos_corrida" / modo))
    ensamblado = construir_orquestador(os.environ.get("CANAL_CONFIG_PATH", RAIZ / "config.toml"), datos, modo)
    for aviso in ensamblado.advertencias:
        print("AVISO:", aviso)
    resultado = ejecutar_ciclo(ensamblado, args.fecha, args.max_pasos, args.presupuesto_dia_usd)
    print(f"Ciclo {modo} | {args.fecha} | producidos {resultado['producidos']} | apartados {resultado['apartados']} | "
          f"costo ${resultado['costo_diario_usd']:.4f} | reserva {resultado['reserva_dias']} días")
    return 2 if resultado["presupuesto_excedido"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
