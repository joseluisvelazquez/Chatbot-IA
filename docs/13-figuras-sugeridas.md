# Figuras Sugeridas

## Figura 1. Arquitectura General Del Sistema

### Qué Debe Mostrar

Debe representar los componentes principales:

- Cliente en WhatsApp.
- WhatsApp Cloud API / Meta.
- Backend FastAPI.
- Base de datos MySQL.
- Panel administrativo.
- WebSocket.
- SIGA local.
- SIGA Bridge externo.

### Sección Recomendada

Capítulo de descripción del proyecto o arquitectura general.

## Figura 2. Flujo De Mensaje Entrante Por WhatsApp

### Qué Debe Mostrar

Debe mostrar la secuencia:

1. Cliente envía mensaje.
2. Meta llama a `/webhook`.
3. Backend valida firma y parsea payload.
4. Se obtiene o crea sesión.
5. Se guarda mensaje.
6. Se ejecuta motor conversacional.
7. Se actualiza base de datos.
8. Se emite WebSocket.
9. Se envía respuesta por WhatsApp.

### Sección Recomendada

Sección de flujo WhatsApp Webhook.

## Figura 3. Diagrama De Estados Del Chatbot

### Qué Debe Mostrar

Debe mostrar los estados definidos en `app/core/states/states.py`, agrupados en:

- Estados de inicio y control.
- Estados de confirmación.
- Estados informativos.
- Estados de componentes.
- Estados de inconsistencia.
- Estados de atención humana.
- Estados de recordatorio.
- Estado finalizado.

### Sección Recomendada

Sección de motor conversacional o flujo de verificación.

## Figura 4. Flujo De Verificación De Folio

### Qué Debe Mostrar

Debe ilustrar cómo el sistema identifica un folio, consulta venta local o Bridge, inicia la verificación, marca pasos y calcula progreso.

### Sección Recomendada

Sección de flujo de verificación o base de datos.

## Figura 5. Modelo Entidad-Relación Simplificado

### Qué Debe Mostrar

Debe incluir las tablas principales del chatbot:

- `chat_sessions`
- `messages`
- `flow_events`
- `verificacion_cuenta`
- `inconsistencias`
- `reminders`
- `panel_sessions`
- `auth_tokens`

También puede mostrar relación con tablas SIGA como:

- `bitacora_ventas`
- `cuentas`
- `domicilios_horarios_entrega`

### Sección Recomendada

Sección de base de datos.

## Figura 6. Autenticación Del Panel

### Qué Debe Mostrar

Debe mostrar:

1. Usuario accede desde SIGA con token.
2. Panel envía token a `/api/auth/exchange`.
3. Backend valida firma, expiración y uso único.
4. Backend crea sesión en `panel_sessions`.
5. Panel usa cookie HTTP-only para futuras peticiones.

### Sección Recomendada

Sección de seguridad, roles y sesiones.

## Figura 7. Comunicación En Tiempo Real

### Qué Debe Mostrar

Debe mostrar cómo el backend emite eventos WebSocket hacia el panel cuando ocurre:

- Nuevo mensaje.
- Actualización de conversación.
- Cambio en dashboard.
- Actualización de verificación.
- Resolución de inconsistencia.

### Sección Recomendada

Sección de panel administrativo o WebSocket.

## Figura 8. Integración SIGA Bridge

### Qué Debe Mostrar

Debe mostrar:

- Backend FastAPI.
- Cliente `SigaBridgeClient`.
- Bridge PHP externo.
- Respuesta JSON con contrato v1.
- Normalización de snapshot.
- Caché en `chat_sessions.extra_json`.
- Uso en panel y webhook.

### Sección Recomendada

Sección de integración SIGA Bridge.

## Figura 9. Dashboard Y Métricas

### Qué Debe Mostrar

Debe presentar visualmente qué datos alimentan cada métrica:

- `chat_sessions` para sesiones.
- `messages` para mensajes entrantes y salientes.
- `inconsistencias` para inconsistencias abiertas.
- `flow_events` para funnel y tiempos entre estados.
- Métricas internas de SIGA Bridge.

### Sección Recomendada

Sección de dashboard y métricas.

## Figura 10. Manejo De Adjuntos

### Qué Debe Mostrar

Debe mostrar el recorrido de un archivo:

- Entrada desde WhatsApp o panel.
- Validación de tipo.
- Almacenamiento en `media/`.
- Registro en `messages`.
- Visualización o envío por WhatsApp.

### Sección Recomendada

Sección de resultados tangibles o manual técnico.
