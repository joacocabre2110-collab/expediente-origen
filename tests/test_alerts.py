from datetime import datetime, timedelta, timezone

import pytest

from canal.alerts import Alerta, CanalSMTP, Nivel, Notificador


class FakeCanal:
    def __init__(self):
        self.enviados = []

    def enviar(self, destino, asunto, cuerpo):
        self.enviados.append((destino, asunto, cuerpo))


def alerta(nivel, asunto="Aviso", cuerpo="Detalle", key=None, creado=None):
    return Alerta(nivel, asunto, cuerpo, key, creado or datetime.now(timezone.utc))


def test_critico_se_envia_inmediatamente():
    canal = FakeCanal()
    notificador = Notificador(canal, "persona@example.com")
    assert notificador.notificar(alerta(Nivel.CRITICO))
    assert len(canal.enviados) == 1
    assert canal.enviados[0] == ("persona@example.com", "Aviso", "Detalle")


def test_diario_acumula_y_envia_un_digest():
    canal = FakeCanal()
    notificador = Notificador(canal, "persona@example.com")
    notificador.notificar(alerta(Nivel.DIARIO, "Uno", "A"))
    notificador.notificar(alerta(Nivel.DIARIO, "Dos", "B"))
    assert canal.enviados == []
    assert notificador.vaciar_resumen(Nivel.DIARIO)
    assert len(canal.enviados) == 1
    assert "Uno\nA" in canal.enviados[0][2]
    assert "Dos\nB" in canal.enviados[0][2]
    assert notificador.vaciar_resumen(Nivel.DIARIO) is False


def test_destino_vacio_guarda_en_bandeja_sin_enviar():
    canal = FakeCanal()
    notificador = Notificador(canal, "")
    notificador.notificar(alerta(Nivel.CRITICO))
    notificador.notificar(alerta(Nivel.DIARIO, "Diario"))
    assert notificador.vaciar_resumen(Nivel.DIARIO) is False
    assert len(notificador.bandeja) == 2
    assert canal.enviados == []
    assert any("pendiente" in aviso.lower() for aviso in notificador.advertencias)


def test_deduplica_alertas_iguales_dentro_de_ventana():
    canal = FakeCanal()
    inicio = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notificador = Notificador(canal, "persona@example.com", ventana_dedupe=60)
    assert notificador.notificar(alerta(Nivel.CRITICO, creado=inicio))
    assert notificador.notificar(alerta(Nivel.CRITICO, creado=inicio + timedelta(seconds=30))) is False
    assert len(canal.enviados) == 1


def test_smtp_deshabilitado_rechaza_uso():
    canal = CanalSMTP("localhost", 25, "MAIL_USER", "MAIL_PASS")
    with pytest.raises(RuntimeError, match="deshabilitado"):
        canal.enviar("persona@example.com", "Asunto", "cuerpo")


def test_smtp_deshabilitado_no_consulta_credenciales(monkeypatch):
    def no_leer(_nombre):
        raise AssertionError("No se deben leer credenciales cuando está deshabilitado")

    monkeypatch.setattr("canal.alerts.notifier.os.environ.get", no_leer)
    canal = CanalSMTP("localhost", 25, "MAIL_USER", "MAIL_PASS")
    with pytest.raises(RuntimeError, match="deshabilitado"):
        canal.enviar("persona@example.com", "Asunto", "cuerpo")


def test_destino_invalido_lanza_value_error():
    with pytest.raises(ValueError, match="destino inválido"):
        Notificador(FakeCanal(), "no-es-correo")


def test_envio_fallido_no_deduplica_y_reintento_se_envia():
    class CanalIntermitente(FakeCanal):
        fallar = True

        def enviar(self, destino, asunto, cuerpo):
            if self.fallar:
                self.fallar = False
                raise RuntimeError("falló")
            super().enviar(destino, asunto, cuerpo)

    canal = CanalIntermitente()
    notificador = Notificador(canal, "persona@example.com")
    aviso = alerta(Nivel.CRITICO)
    with pytest.raises(RuntimeError, match="falló"):
        notificador.notificar(aviso)
    assert notificador.notificar(aviso)
    assert len(canal.enviados) == 1
    assert notificador.bandeja == []


def test_envio_fallido_conserva_alerta_en_bandeja():
    class CanalFallido(FakeCanal):
        def enviar(self, destino, asunto, cuerpo):
            raise RuntimeError("falló")

    notificador = Notificador(CanalFallido(), "persona@example.com")
    aviso = alerta(Nivel.CRITICO)
    with pytest.raises(RuntimeError):
        notificador.notificar(aviso)
    assert notificador.bandeja == [aviso]


def test_reenviar_bandeja_al_configurar_destino():
    canal = FakeCanal()
    notificador = Notificador(canal)
    aviso = alerta(Nivel.CRITICO)
    notificador.notificar(aviso)
    notificador.configurar_destino("persona@example.com")
    assert notificador.reenviar_bandeja() == 1
    assert canal.enviados == [("persona@example.com", "Aviso", "Detalle")]
    assert notificador.bandeja == []
