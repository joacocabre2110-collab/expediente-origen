# Despliegue en servidor Linux

Instrucciones para Ubuntu Server 24.04 LTS (x86_64, 4 núcleos). El servicio reserva como máximo 4 CPU y 8 GiB de memoria; ajuste `mem_limit` en `docker-compose.yml` si la máquina tiene menos RAM. Los datos de ejecución viven en el volumen Docker `canal_data`; `secrets/` se monta como solo lectura.

## 1. Crear el servidor

Crear una instancia Ubuntu Server 24.04 LTS con 4 vCPU, al menos 8 GiB de RAM y disco suficiente para videos y respaldos. Restringir SSH al rango de IP administrativo y habilitar actualizaciones de seguridad del proveedor. Conectarse como el usuario administrador:

```sh
ssh usuario@IP_DEL_SERVIDOR
```

## 2. Instalar Docker

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

## 3. Copiar el proyecto y preparar configuración

Desde el equipo local, desde la raíz del repositorio:

```sh
rsync -a --exclude .git --exclude .venv ./ usuario@IP_DEL_SERVIDOR:/tmp/canal-automatico/
```

En el servidor:

```sh
sudo mkdir -p /opt/canal-automatico
sudo rsync -a /tmp/canal-automatico/ /opt/canal-automatico/
sudo mkdir -p /opt/canal-automatico/deploy/config /opt/canal-automatico/secrets
sudo chown -R "$USER":"$USER" /opt/canal-automatico
```

Copiar los secretos desde el equipo que los custodia. El archivo SMTP contiene únicamente la contraseña SMTP; no la pongas en comandos, repositorios ni logs:

```sh
scp /ruta/segura/smtp_password.txt usuario@IP_DEL_SERVIDOR:/tmp/smtp_password.txt
ssh usuario@IP_DEL_SERVIDOR 'sudo install -o root -g root -m 0600 /tmp/smtp_password.txt /opt/canal-automatico/secrets/smtp_password.txt && rm /tmp/smtp_password.txt'
```

Si el proyecto usa credenciales de Google, copiarlas del mismo modo a `secrets/` y restringirlas a `root:root`, modo `0600`. El directorio completo se monta read-only dentro del contenedor. No se leen ni imprimen sus contenidos.

Crear `/opt/canal-automatico/deploy/config/smtp.ini` solo si se activa el canal SMTP; rellenar host, puerto, usuario y remitente, sin incluir la contraseña:

```ini
[smtp]
host = smtp.ejemplo.com
puerto = 587
usuario = correo@ejemplo.invalid
remitente = Canal Automático <correo@ejemplo.invalid>
```

Protegerlo y asignar los permisos de lectura necesarios al UID 10001 del contenedor:

```sh
sudo chown root:10001 /opt/canal-automatico/deploy/config/smtp.ini
sudo chmod 0640 /opt/canal-automatico/deploy/config/smtp.ini
sudo chown root:10001 /opt/canal-automatico/secrets/smtp_password.txt
sudo chmod 0640 /opt/canal-automatico/secrets/smtp_password.txt
```

El archivo de contraseña debe contener solo la clave. Si se mantienen permisos `0600 root:root`, el usuario sin privilegios del contenedor no podrá leerlo; use propietario root y grupo 10001 con modo `0640`, conservando el directorio `secrets/` restringido en el servidor.

## 4. Primer arranque

Desde el servidor:

```sh
cd /opt/canal-automatico/deploy
sudo docker compose build
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 canal
```

La imagen instala Python 3.12, FFmpeg, dependencias del proyecto, Google Auth, Google API Client y Playwright con Chromium. Se solicitan los paquetes Debian `fonts-inter` y `fonts-gfs-baskerville`. Si no están publicados para la versión elegida, la compilación se detendrá: instale fuentes Inter y GFS Baskerville desde paquetes de fuentes compatibles en una imagen derivada y verifique sus licencias antes de desplegar. La aplicación se ejecuta con UID/GID 10001.

## 5. Ejecución diaria y salud

El archivo `crontab.txt` programa el proceso diario a las 08:00 y una comprobación diaria. Antes de instalarlo, edite `0 8` a la hora local deseada. Asegure que el servidor use la zona horaria deseada (`timedatectl`). Instálelo:

```sh
sudo crontab /opt/canal-automatico/deploy/crontab.txt
sudo crontab -l
```

El chequeo Docker se ejecuta cada 5 minutos; consultar su estado con `sudo docker compose ps`. El cron del servidor registra la ejecución en `/var/log/canal-automatico.log` y escribe fallos de estado en syslog. El proceso diario usa `CANAL_DATA_DIR=/app/data`; revise que `scripts/diario.py` respete esa variable o configure su ruta de datos en el proyecto.

## 6. Logs y actualización

```sh
cd /opt/canal-automatico/deploy
sudo docker compose logs -f --tail=200 canal
sudo tail -n 200 /var/log/canal-automatico.log
```

Para actualizar, copie la nueva versión con `rsync` excluyendo `.git`, `.venv` y `secrets/`; no sobrescriba los secretos. Después:

```sh
cd /opt/canal-automatico/deploy
sudo docker compose build --pull
sudo docker compose up -d --force-recreate
sudo docker compose ps
```

## 7. Backup de datos

Hacer backup con el contenedor detenido para mantener coherencia. El archivo se crea en el directorio actual del host:

```sh
cd /opt/canal-automatico/deploy
sudo docker compose stop
sudo docker run --rm -v deploy_canal_data:/data:ro -v "$PWD":/backup alpine tar -czf /backup/canal-data-$(date +%F).tar.gz -C /data .
sudo docker compose start
```

El nombre del volumen puede variar si Compose asignó otro prefijo; obtenerlo con `sudo docker volume ls`. Guardar una copia cifrada fuera del servidor y probar periódicamente su restauración. Respaldar secretos por separado mediante el sistema seguro de custodia de claves; no incluirlos en el tar de datos.

## 8. Rotación de claves

Rotar la contraseña SMTP en el proveedor y reemplazar `secrets/smtp_password.txt` por SCP usando un archivo temporal fuera del repositorio. Aplicar propietario `root:10001`, modo `0640` y reiniciar el servicio:

```sh
sudo chown root:10001 /opt/canal-automatico/secrets/smtp_password.txt
sudo chmod 0640 /opt/canal-automatico/secrets/smtp_password.txt
cd /opt/canal-automatico/deploy && sudo docker compose restart canal
```

Rotar las credenciales Google desde la consola correspondiente, reemplazar los archivos bajo `secrets/`, validar permisos y reiniciar. Revocar las credenciales anteriores una vez confirmado el funcionamiento. Mantener la copia anterior solo en la custodia cifrada autorizada.
