# Manual De Usuario

## Descripción General

Este manual describe el uso del panel administrativo del sistema. El panel permite consultar verificaciones, revisar conversaciones, responder mensajes, observar métricas e identificar inconsistencias.

El panel se encuentra disponible desde la ruta `/panel`, servida por el backend FastAPI.

## Acceso Al Panel

El acceso normal se realiza mediante un token firmado proveniente de SIGA. El panel toma el token de la URL, lo intercambia con el backend y crea una sesión segura mediante cookie.

En ambiente local, el panel puede usar un inicio de sesión de desarrollo si el backend está en modo `DEBUG`.

Pendiente de validar: el procedimiento operativo exacto de acceso desde SIGA en producción.

## Navegación Principal

El panel incluye las siguientes secciones:

- Verificaciones.
- Conversaciones.
- Dashboard.
- Cobranza.

La vista de Cobranza aparece como pendiente de integración, de acuerdo con `panel/pages/cobranza.html`.

## Verificaciones

La vista de verificaciones muestra una tabla con:

- Número de cuenta.
- Folio.
- Teléfono.
- Estado.
- Progreso.
- Paso actual.
- Inconsistencias.
- Última actividad.

El usuario puede filtrar por:

- Todas.
- En proceso.
- Inconsistencias.
- Asesor.
- Inactivas.
- Finalizadas.

Al seleccionar una verificación se abre un panel lateral con más detalles. Este panel puede incluir información del cliente, progreso, inconsistencias y datos de SIGA, dependiendo del rol del usuario.

## Gestión De Inconsistencias

Cuando una verificación tiene inconsistencias, el panel muestra el detalle y la severidad cuando está disponible.

El usuario autorizado puede:

- Revisar el campo afectado.
- Consultar el mensaje del cliente.
- Identificar si requiere validación en SIGA.
- Marcar una inconsistencia como resuelta localmente cuando aplique.
- Acceder a SIGA mediante el botón correspondiente si la inconsistencia requiere revisión externa.

## Conversaciones

La vista de conversaciones permite:

- Buscar chats.
- Filtrar por no leídos.
- Abrir una conversación.
- Leer historial de mensajes.
- Enviar respuestas.
- Adjuntar archivos.
- Visualizar imágenes.
- Marcar conversación como leída.

Los mensajes pueden ser:

- Entrantes del cliente.
- Salientes del bot.
- Enviados por agente desde el panel.

## Envío De Mensajes

Para enviar un mensaje:

1. Abrir la vista Conversaciones.
2. Seleccionar una conversación.
3. Escribir el mensaje en el cuadro de texto.
4. Presionar el botón de envío.

El backend registra el mensaje y lo envía por WhatsApp.

## Envío De Archivos

El panel permite adjuntar archivos. Según el backend, los tipos permitidos son:

- Imagen JPEG.
- Imagen PNG.
- Documento PDF.

El tamaño máximo permitido por `app/router/media_router.py` es de 10 MB.

## Dashboard

La vista Dashboard muestra indicadores generales:

- Sesiones.
- Sesiones activas.
- Mensajes entrantes.
- Mensajes salientes.
- Inconsistencias abiertas.
- Funnel de verificación.
- Tiempo entre estados.
- Métricas de SIGA Bridge para roles autorizados.

## Actualización En Tiempo Real

El panel recibe actualizaciones en tiempo real mediante WebSocket. Esto permite observar nuevos mensajes, cambios de verificación, actualizaciones del dashboard e inconsistencias sin recargar manualmente.

## Cierre De Sesión

El panel incluye cierre de sesión mediante `/api/auth/logout`. Al cerrar sesión, el backend revoca la sesión y limpia la cookie.

## Roles Y Permisos

El acceso y visibilidad dependen del rol asignado. Los roles identificados son:

- admin
- ventas
- cobranza
- sistemas
- jefe_operativo
- viewer

Pendiente de validar: reglas operativas finales por puesto y responsabilidades de cada rol.

## Pendientes De Validar

- Procedimiento final de acceso desde SIGA en producción.
- Capacitación específica por rol.
- Flujo operativo del módulo Cobranza, ya que aún aparece como pendiente.
