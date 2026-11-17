# Ejecutar el canal en GitHub Actions

El repositorio público contiene solo código. Los recursos creativos y los datos persistentes viven en un repositorio privado de estado. El workflow conserva `publish_public_enabled = false`; `ClienteSeguro` además bloquea la publicación pública aunque la configuración se modifique accidentalmente.

## 1. Crear los repositorios

1. Cree un repositorio **público** con el código del proyecto y la rama `main`.
2. Cree un repositorio **privado** para estado. En su raíz, suba `assets/original/canal_youtube/` con `CANAL_YOUTUBE.md`, `audio/`, `imagenes/` y `plantillas_html/`. No agregue los assets al repositorio público.
3. En el repo privado, cree `datos_corrida/real/` (puede quedar vacío inicialmente) y haga un commit inicial. El workflow guarda allí SQLite y JSON/TXT de estado. No guarde videos renderizados en el repo.

## 2. Token de acceso al repo privado

Se usa una **clave de despliegue (deploy key)** SSH con permiso de escritura, registrada solo en el repo privado de estado y guardada como el secreto `STATE_DEPLOY_KEY`. No hace falta un token personal.

## 3. Secrets requeridos

Agregue estos Actions Secrets al repositorio público:

| Nombre | Contenido esperado |
| --- | --- |
| `STATE_REPO` | `propietario/nombre-repo-privado` |
| `STATE_DEPLOY_KEY` | Clave privada SSH de la deploy key del repo de estado |
| `CONFIG_TOML` | Configuración TOML completa; incluya `publish_public_enabled = false` y los parámetros habituales de producción |
| `CLIENT_SECRET_JSON` | Contenido íntegro del OAuth `client_secret.json` de YouTube |
| `TOKEN_JSON` | Contenido íntegro del `token.json` autorizado para el canal |
| `GEMINI_API_KEY` | Clave API de Gemini, sin comillas ni saltos de línea |
| `SPEKO_API_KEY` | Clave API de Speko/ElevenLabs, sin comillas ni saltos de línea |
| `GMAIL_ADDRESS` | Cuenta Gmail usada como remitente SMTP |
| `GMAIL_APP_PASSWORD` | Contraseña de aplicación de Google (no la contraseña habitual de la cuenta) |
| `ALERT_EMAIL` | Dirección que recibe alertas de fallos |

El secreto `CONFIG_TOML` debe conservar la opción `publish_public_enabled = false`. Las opciones `email_alertas` y demás campos se configuran allí como en la ejecución local. En el primer run se puede usar la entrada `dry_run` del despacho manual para comprobar el scheduler sin invocar proveedores externos.

## 4. Primer run de prueba

Abra **Actions → Ciclo diario del canal → Run workflow**, elija la rama `main` y deje `dry_run` activado. El modo de prueba usa generadores locales y no sube videos. Revise el resumen del job y que `datos_corrida/real/` del repositorio privado reciba el estado necesario. Luego puede lanzar manualmente con `dry_run` desactivado; los schedules ejecutan el modo real cada dos horas.

El workflow instala Python 3.11 (requisito del proyecto), FFmpeg, Chromium para Playwright y los paquetes Ubuntu `fonts-inter` y `fonts-gfs-baskerville`. Los assets se montan desde `estado/assets/original/canal_youtube`; el estado se monta desde `estado/datos_corrida/real`.
