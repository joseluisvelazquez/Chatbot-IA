# Manual Técnico

## Requisitos Identificados

El archivo `requirements.txt` indica dependencias principales:

- fastapi
- uvicorn
- pydantic
- sqlalchemy
- pymysql
- pydantic_settings
- apscheduler
- httpx
- requests
- google-genai
- python-multipart
- pytest

## Configuración

La configuración se centraliza en `app/config/settings.py` y se carga desde `.env`.

Variables relevantes:

- `VERIFY_TOKEN`
- `WHATSAPP_TOKEN`
- `PHONE_NUMBER_ID`
- `META_API_VERSION`
- `MEDIA_BASE_URL`
- `GEMINI_API_KEY`
- `DB_HOST`
- `DB_PORT`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `PANEL_SHARED_SECRET`
- `EXTERNAL_TRIGGER_TOKEN`
- `SIGA_BRIDGE_ENABLED`
- `SIGA_BRIDGE_BASE_URL`
- `SIGA_BRIDGE_TOKEN`

No deben documentarse valores reales de secretos.

## Ejecución Del Backend

El `Dockerfile` ejecuta:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Para ejecución local, el comando equivalente sería:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Estructura Técnica

### Entrada Principal

`app/main.py`:

- Crea la instancia FastAPI.
- Registra routers.
- Monta `/panel`.
- Monta `/media`.
- Configura CORS.
- Inicia scheduler de recordatorios.

### Base De Datos

`app/db/session.py`:

- Crea el engine SQLAlchemy.
- Define `SessionLocal`.
- Expone `get_db`.

`app/db/models.py`:

- Contiene los modelos ORM.

### Webhook

`app/api/webhook.py`:

- Valida webhook de Meta.
- Procesa mensajes entrantes.
- Deduplica eventos.
- Guarda mensajes.
- Ejecuta el motor de flujo.
- Emite eventos WebSocket.
- Envía respuestas por WhatsApp.

### Panel

`app/router/panel_router.py`:

- Expone endpoints para dashboard, verificaciones, conversaciones, mensajes, WebSocket y resolución de inconsistencias.

### Media

`app/router/media_router.py`:

- Permite subir archivos desde el panel.
- Acepta JPEG, PNG y PDF.
- Limita tamaño a 10 MB.

### Autenticación

`app/router/auth_router.py`:

- Intercambia tokens.
- Crea sesión.
- Valida sesión.
- Cierra sesión.

### SIGA Bridge

`app/services/siga_bridge.py`:

- Implementa cliente HTTP.
- Valida contrato.
- Maneja errores.
- Mantiene métricas y caché.

## Pruebas

Las pruebas se encuentran en `app/tests/`.

Áreas cubiertas:

- Alcance por empresa.
- Intenciones.
- Flujo conversacional.
- SIGA Bridge.
- Normalización de datos del Bridge.
- Correcciones de flujo.
- Webhook.

Pendiente de validar: ejecutar la suite completa y actualizar pruebas que no coincidan con las firmas actuales.

## Despliegue Con Docker

El repositorio contiene:

- `Dockerfile`
- `docker-compose.yml`

El compose define servicios para:

- `api`
- `db` con MySQL 8.0

Pendiente de validar: el archivo `docker-compose.yml` aparece en `.gitignore`, pero existe en el workspace. Debe confirmarse si forma parte del entregable final.

## Consideraciones Técnicas

- No almacenar secretos en documentación.
- Validar cookies seguras en producción.
- Confirmar esquema real de base de datos antes de aplicar migraciones manuales.
- Validar disponibilidad de SIGA Bridge antes de habilitarlo.
- Revisar archivos legacy no montados antes de mantenimiento futuro.

## Pendientes De Validar

- Procedimiento exacto de despliegue productivo.
- Configuración definitiva de dominios CORS.
- Estado actualizado de pruebas automatizadas.
- Versionado formal de migraciones de base de datos.
