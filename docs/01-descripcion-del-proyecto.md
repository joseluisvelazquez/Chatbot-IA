# Descripción Del Proyecto

## Nombre Del Proyecto

Chatbot de WhatsApp con backend FastAPI, panel administrativo web e integración con SIGA mediante Bridge.

## Descripción General

El proyecto consiste en una plataforma que automatiza y centraliza el proceso de verificación de ventas mediante WhatsApp. La aplicación recibe mensajes desde WhatsApp Cloud API, interpreta la intención del usuario, consulta información de ventas y cuentas, mantiene un estado de conversación, registra mensajes e inconsistencias, y ofrece un panel administrativo para dar seguimiento a cada caso.

El backend está desarrollado en Python con FastAPI. El archivo principal `app/main.py` configura la aplicación, registra routers y monta los recursos estáticos del panel y archivos multimedia. La capa de persistencia usa SQLAlchemy y MySQL, con modelos definidos en `app/db/models.py`.

## Contexto Del Sistema

El sistema opera alrededor de un proceso de verificación asociado a un folio de venta. A partir de ese folio, el chatbot guía al cliente para confirmar datos relacionados con su compra. El sistema conserva el avance de la conversación en la tabla `chat_sessions`, registra mensajes en `messages`, almacena eventos de flujo en `flow_events`, guarda avance estructurado en `verificacion_cuenta` y documenta inconsistencias en `inconsistencias`.

El panel administrativo permite a personal autorizado consultar conversaciones, responder mensajes, revisar verificaciones, observar inconsistencias y monitorear métricas operativas. Este panel se encuentra en la carpeta `panel/`, y se comunica con el backend mediante endpoints bajo `/api/panel`.

## Tecnologías Identificadas

- Python y FastAPI para el backend.
- SQLAlchemy y PyMySQL para acceso a MySQL.
- WhatsApp Cloud API mediante HTTP.
- WebSocket para eventos en tiempo real.
- JavaScript modular para el panel web.
- Tailwind CSS mediante CDN para la interfaz.
- Chart.js para gráficas del dashboard.
- APScheduler para recordatorios de inactividad.
- Google Gemini para apoyo de IA en respuestas y análisis de inconsistencias.
- Docker y Docker Compose para despliegue local o contenedorizado.

## Módulos Del Proyecto

Los módulos principales se distribuyen de la siguiente manera:

- `app/api/`: endpoints de webhook, panel send legacy y triggers externos.
- `app/router/`: routers de panel, autenticación, media y SIGA Bridge.
- `app/core/`: motor de flujo, estados, intenciones y verificación.
- `app/services/`: servicios de negocio, integración SIGA, IA, mensajes, media, sesiones e inconsistencias.
- `app/db/`: conexión y modelos de base de datos.
- `app/security/`: autenticación, sesiones, roles y restricciones.
- `app/websockets/`: administración de conexiones WebSocket.
- `panel/`: interfaz administrativa.

## Pendientes De Validar

- No se identificó dentro del repositorio el código PHP del Bridge de SIGA.
- No se confirmó un sistema formal de migraciones automatizadas como Alembic; existe un archivo manual `app/db/migrations/20260416_panel_consistency.md`.
