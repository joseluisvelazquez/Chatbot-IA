# Alcance Del Proyecto

## Alcance Funcional Confirmado

El sistema cubre las siguientes funcionalidades confirmadas en el código:

- Recepción y validación de webhooks de WhatsApp.
- Parseo de mensajes de texto, botones interactivos, imágenes, documentos y eventos de estado.
- Envío de respuestas por WhatsApp Cloud API.
- Flujo conversacional por estados para verificación de venta.
- Identificación de folios desde texto libre.
- Consulta de ventas por folio en la base local mediante `app/siga/siga_repository.py`.
- Integración opcional con SIGA Bridge cuando `SIGA_BRIDGE_ENABLED` está activo.
- Registro de sesiones de chat, mensajes, eventos de flujo, verificaciones e inconsistencias.
- Panel administrativo con vistas de dashboard, conversaciones y verificaciones.
- Envío de mensajes y archivos desde el panel.
- Carga de archivos permitidos mediante `/api/panel/upload`.
- Comunicación en tiempo real mediante WebSocket.
- Autenticación del panel mediante token firmado y cookie HTTP-only.
- Restricción de acceso por empresa y rol.
- Recordatorios de inactividad mediante APScheduler.

## Alcance Técnico Confirmado

El backend se ejecuta como una aplicación FastAPI definida en `app/main.py`. La configuración se obtiene desde variables de entorno mediante `app/config/settings.py`. La conexión a MySQL se realiza con SQLAlchemy y PyMySQL en `app/db/session.py`.

El panel es una aplicación web estática servida desde `/panel`. No se identificó un proceso de compilación frontend; el panel utiliza JavaScript modular, Tailwind CSS desde CDN, Lucide Icons y Chart.js.

## Límites Del Proyecto

El proyecto no incluye, dentro del repositorio analizado, el código fuente del sistema SIGA ni el código PHP del Bridge. El backend FastAPI actúa como consumidor de la información disponible en la base local y del Bridge externo.

El módulo de Cobranza aparece en el panel, pero su propia vista indica que está pendiente de integración. Por tanto, no debe considerarse una funcionalidad operativa final.

## Fuera Del Alcance Confirmado

Con base en los archivos revisados, no se puede afirmar que el sistema incluya:

- Administración completa de usuarios desde el panel.
- Módulo operativo completo de Cobranza.
- Escrituras directas hacia SIGA Bridge.
- Migraciones automáticas completas con una herramienta como Alembic.
- Código PHP del Bridge.
- Despliegue productivo completo documentado paso a paso.

## Pendientes De Validar

- Validar en ambiente real qué endpoints del Bridge están disponibles y qué acciones exactas implementa el PHP Bridge.
- Validar la configuración definitiva de producción para CORS, cookies seguras y dominio público.
- Validar si `app/api/panel_send.py` y `app/media/main.py` permanecen por compatibilidad o deben considerarse código legacy.
