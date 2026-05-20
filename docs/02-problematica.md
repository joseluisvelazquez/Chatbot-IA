# Problemática

## Situación Identificada

El proceso de verificación de ventas requiere confirmar con el cliente diversos datos relacionados con su compra, como folio, nombre, domicilio, fecha de venta, producto adquirido, componentes, pago inicial, métodos de pago, planes y beneficios. Cuando este proceso se realiza manualmente, puede implicar mayor carga operativa, seguimiento disperso y dificultad para registrar el avance de cada caso.

El repositorio muestra que el sistema fue diseñado para atender esta necesidad mediante un chatbot de WhatsApp que guía al cliente paso a paso y registra el estado del proceso. También se incorporó un panel administrativo que concentra conversaciones, verificaciones, inconsistencias y métricas.

## Necesidades Operativas

Con base en los módulos del repositorio, las necesidades atendidas por el sistema son:

- Recibir mensajes entrantes desde WhatsApp Cloud API.
- Procesar respuestas de texto, botones interactivos, imágenes y documentos.
- Asociar conversaciones a folios y cuentas.
- Consultar información de venta desde la base local de SIGA o desde SIGA Bridge cuando está habilitado.
- Mantener trazabilidad del avance de verificación.
- Registrar inconsistencias cuando el cliente reporta datos incorrectos.
- Permitir intervención de personal autorizado desde un panel administrativo.
- Mostrar métricas del proceso para monitoreo operativo.
- Notificar cambios en tiempo real mediante WebSocket.

## Riesgos Del Proceso Sin Sistema

El código sugiere que se buscó reducir los siguientes riesgos:

- Pérdida de seguimiento de conversaciones.
- Falta de trazabilidad del estado de cada verificación.
- Dificultad para identificar casos con inconsistencias.
- Retrasos en la atención por falta de visibilidad centralizada.
- Dependencia de revisión manual para consultar folios, cuentas o datos de venta.
- Duplicidad de mensajes entrantes si Meta reenvía eventos, mitigada por `message_id`.

## Problema Técnico A Resolver

El problema técnico consiste en integrar varios componentes en un flujo consistente:

- WhatsApp como canal de entrada y salida.
- Backend FastAPI como núcleo de procesamiento.
- MySQL como persistencia central.
- SIGA como fuente de datos operativos.
- Panel web como herramienta de seguimiento.
- WebSocket como canal de actualización en tiempo real.

## Pendientes De Validar

- No se identificó en el repositorio un documento previo que describa la problemática institucional original; esta sección se basa en la arquitectura y funcionalidades implementadas.
- No se encontraron métricas históricas que cuantifiquen el tiempo manual previo al sistema.
