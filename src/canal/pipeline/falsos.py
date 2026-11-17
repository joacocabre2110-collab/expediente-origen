"""Implementaciones deterministas para pruebas de las etapas del pipeline."""

from __future__ import annotations

from pathlib import Path

from .etapas import (
    ContextoVideo, Guion, Metadatos, Miniatura, Narracion, Render,
    ResultadoQA, ResultadoVerificacion, Tema,
)

AVISO_IA = "Narración con voz generada por IA. Ilustraciones: recreación artística."
ESTRUCTURAS = (
    "cronologica", "misterio", "causa_consecuencia", "comparacion",
    "investigacion", "giro_final",
)


class FalloTransitorio(RuntimeError):
    """Fallo controlado para probar reintentos."""


class _Falso:
    def __init__(self, fallos_transitorios: int = 0) -> None:
        if fallos_transitorios < 0:
            raise ValueError("fallos_transitorios no puede ser negativo")
        self.fallos_transitorios = fallos_transitorios

    def _fallar_si_corresponde(self) -> None:
        if self.fallos_transitorios:
            self.fallos_transitorios -= 1
            raise FalloTransitorio("Fallo transitorio simulado")


class GeneradorTemaFalso(_Falso):
    _temas = ("observatorio polar", "archivo submarino", "bosque petrificado", "santuario orbital",
              "ciudad enterrada", "faro volcánico", "caverna de cristal", "jardín magnético",
              "meseta luminosa", "laboratorio abisal", "estación errante", "valle resonante",
              "cripta de hielo", "torre de basalto", "isla espectral", "máquina celeste")

    def __init__(self, fallos_transitorios: int = 0) -> None:
        super().__init__(fallos_transitorios)
        self._intentos = 0
        self._largos = 0

    def generar(self, contexto: ContextoVideo) -> Tema:
        self._fallar_si_corresponde()
        indice = sum((i + 1) * ord(c) for i, c in enumerate(contexto.video_key))
        tema = self._temas[self._intentos % len(self._temas)]
        self._intentos += 1
        pilares = ("espacio", "tierra", "sobrenatural")
        pilar = pilares[self._largos % len(pilares)]
        if getattr(contexto, "tipo", "largo") != "short":
            self._largos += 1
        caso_id = f"caso-{contexto.video_key}"
        tipo = f" {getattr(contexto, 'tipo', 'largo')}" if getattr(contexto, 'tipo', 'largo') == "short" else ""
        folio = sum((i + 1) * ord(c) for i, c in enumerate(contexto.video_key))
        sello = f"muestra singular {folio}"
        return Tema(f"{contexto.video_key}{tipo}: {tema}, {sello}", caso_id, pilar,
                    [f"Clave exclusiva {tema} {sello} cuaderno"])


class GeneradorGuionFalso(_Falso):
    _vocabulario = (
        ("brújula", "granito", "silencio", "medición"),
        ("salmuera", "cobre", "eco", "cartografía"),
        ("helecho", "basalto", "resplandor", "muestra"),
        ("órbita", "iridio", "pulso", "bitácora"),
        ("arcilla", "ámbar", "vibración", "archivo"),
        ("ceniza", "obsidiana", "destello", "registro"),
        ("cuarzo", "níquel", "susurro", "experimento"),
        ("imán", "jade", "frecuencia", "cuaderno"),
    )
    def __init__(self, fallos_transitorios: int = 0, guion_duplicado: bool = False) -> None:
        super().__init__(fallos_transitorios)
        self.guion_duplicado = guion_duplicado
        self._indice = 0

    def generar(self, contexto: ContextoVideo, tema: Tema) -> Guion:
        self._fallar_si_corresponde()
        estructura = ESTRUCTURAS[self._indice % len(ESTRUCTURAS)]
        self._indice += 1
        # El identificador de video elige un léxico estable y separado para cada
        # derivado, evitando que largos y shorts reciclen los mismos ganchos.
        indice_lexico = sum((i + 1) * ord(c) for i, c in enumerate(contexto.video_key)) % len(self._vocabulario)
        vocabulario = self._vocabulario[indice_lexico]
        marca = f"{contexto.video_key} {tema.titulo}"
        texto = "Relato repetido para comprobar duplicados." if self.guion_duplicado else (
            f"{marca}: {vocabulario[0]} {vocabulario[1]}; {vocabulario[2]} {vocabulario[3]}. "
            f"{estructura} conecta {vocabulario[1]} con {vocabulario[3]}, mientras {marca} "
            f"documenta {vocabulario[2]} y {vocabulario[0]} en una secuencia singular."
        )
        gancho = f"¿Qué revela {vocabulario[2]} sobre {marca}?"
        intro = f"El registro {vocabulario[3]} encuentra {vocabulario[0]} junto a {vocabulario[1]}: {marca}."
        if self.guion_duplicado:
            gancho, intro = "¿Qué ocurrió en el relato repetido?", "Hoy investigamos el relato repetido."
        return Guion(texto, gancho, intro,
                     estructura, tema.pilar)


class VerificadorFalso(_Falso):
    def verificar(self, contexto: ContextoVideo, tema: Tema, guion: Guion) -> ResultadoVerificacion:
        self._fallar_si_corresponde()
        return ResultadoVerificacion(bool(guion.texto.strip()), [] if guion.texto.strip() else ["guion_vacio"])


class NarradorFalso(_Falso):
    def __init__(self, costo_usd: float = 0.0, fallos_transitorios: int = 0) -> None:
        super().__init__(fallos_transitorios)
        self.costo_usd = costo_usd

    def narrar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
               verificacion: ResultadoVerificacion) -> Narracion:
        self._fallar_si_corresponde()
        ruta = Path(contexto.directorio_trabajo) / "audio.txt"
        _escribir(ruta, guion.texto)
        return Narracion(ruta, self.costo_usd)


class RenderizadorFalso(_Falso):
    def __init__(self, costo_usd: float = 0.0, fallos_transitorios: int = 0) -> None:
        super().__init__(fallos_transitorios)
        self.costo_usd = costo_usd

    def renderizar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                   narracion: Narracion) -> Render:
        self._fallar_si_corresponde()
        ruta = Path(contexto.directorio_trabajo) / "video.txt"
        _escribir(ruta, f"Render falso de {contexto.video_key}: {narracion.ruta_audio.name}")
        return Render(ruta, self.costo_usd)


class ControlCalidadFalso(_Falso):
    def __init__(self, rechazar_video_key: str | None = None, fallos_transitorios: int = 0) -> None:
        super().__init__(fallos_transitorios)
        self.rechazar_video_key = rechazar_video_key

    def controlar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                  narracion: Narracion, render: Render) -> ResultadoQA:
        self._fallar_si_corresponde()
        rechazado = contexto.video_key == self.rechazar_video_key
        return ResultadoQA(not rechazado, ["rechazado_por_clave"] if rechazado else [])


class GeneradorMiniaturaFalso(_Falso):
    def __init__(self, costo_usd: float = 0.0, fallos_transitorios: int = 0) -> None:
        super().__init__(fallos_transitorios)
        self.costo_usd = costo_usd

    def generar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                render: Render, qa: ResultadoQA) -> Miniatura:
        self._fallar_si_corresponde()
        ruta = Path(contexto.directorio_trabajo) / "miniatura.txt"
        _escribir(ruta, f"Miniatura falsa: {tema.titulo}")
        return Miniatura(ruta, self.costo_usd)


class GeneradorMetadatosFalso(_Falso):
    def generar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                render: Render, miniatura: Miniatura) -> Metadatos:
        self._fallar_si_corresponde()
        titulo = tema.titulo + (" #shorts" if contexto.tipo == "short" else "")
        return Metadatos(titulo, f"{guion.texto}\n\n{AVISO_IA}", ["misterio", "caso"])


def _escribir(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
