#!/usr/bin/env python3
"""Autoriza YouTube y muestra el canal asociado (solo lectura)."""

from canal.youtube.auth import autorizar


def main() -> None:
    from googleapiclient.discovery import build

    credentials = autorizar()
    resultado = build("youtube", "v3", credentials=credentials).channels().list(mine=True, part="snippet").execute()
    for canal in resultado.get("items", []):
        print(f"{canal.get('snippet', {}).get('title', '')}\t{canal.get('id', '')}")


if __name__ == "__main__":
    main()
