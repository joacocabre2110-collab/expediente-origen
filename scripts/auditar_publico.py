#!/usr/bin/env python3
"""Audita los archivos que no quedan excluidos por .gitignore, sin revelar hallazgos."""
from __future__ import annotations

import argparse
import fnmatch
import re
from pathlib import Path

IGNORADOS = ("secrets/", "config.toml", "assets/", "datos_corrida/", "docs_externas/",
             "*.sqlite", "*.sqlite3", "token*.json", "client_secret*.json", ".git/", ".venv/")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
API = re.compile(r"AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._~+/-]{20,}", re.I)
USER_PATH = re.compile(r"/Users/[^/\s]+")


def excluido(rel: str, raiz: Path | None = None) -> bool:
    rel = rel.replace("\\", "/")
    patrones = list(IGNORADOS)
    if raiz is not None and (raiz / ".gitignore").is_file():
        patrones.extend(line.strip() for line in (raiz / ".gitignore").read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.lstrip().startswith("#") and not line.startswith("!"))
    partes = rel.split("/")
    for patron in patrones:
        patron = patron.lstrip("/")
        es_directorio = patron.endswith("/")
        patron = patron.rstrip("/")
        if (es_directorio and (rel == patron or rel.startswith(patron + "/"))) or fnmatch.fnmatch(rel, patron):
            return True
        if "/" not in patron and any(fnmatch.fnmatch(parte, patron) for parte in partes):
            return True
    return False


def auditar(raiz: Path) -> list[tuple[str, str]]:
    hallazgos = []
    for path in raiz.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(raiz).as_posix()
        if excluido(rel, raiz):
            continue
        if rel == "scripts/auditar_publico.py":
            continue
        try:
            if path.stat().st_size > 5 * 1024 * 1024:
                hallazgos.append((rel, "archivo mayor a 5 MB"))
                continue
            raw = path.read_bytes()
            texto = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r'"(?:client_secret|refresh_token|access_token|token)"\s*:\s*"[^"\n]{12,}', texto, re.I):
            hallazgos.append((rel, "referencia a client_secret/token"))
        if API.search(texto):
            hallazgos.append((rel, "posible clave API/token bearer"))
        if USER_PATH.search(texto):
            hallazgos.append((rel, "ruta personal /Users"))
        # Se reportan direcciones reales; dominios reservados de ejemplo no son personales.
        for email in EMAIL.findall(texto):
            if not email.lower().endswith(("@example.com", "@example.test", "@ejemplo.com", "@ejemplo.invalid")):
                hallazgos.append((rel, "email posiblemente personal"))
                break
    return hallazgos


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    hallazgos = auditar(args.raiz)
    if hallazgos:
        print(f"Auditoría pública: {len(hallazgos)} hallazgo(s)")
        for ruta, tipo in hallazgos:
            print(f"- {ruta}: {tipo}")
        return 1
    print("Auditoría pública: sin hallazgos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
