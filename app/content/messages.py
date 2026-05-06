# app/content/messages.py

ESPERA = (
    "Hola, soy Alonso 👋🏻\n\n"
    "Estoy aquí para apoyarte con la activación de tus beneficios. 🤳🏻\n"
    "En breve te contactaré nuevamente para brindarte más información."
)

MENU_AYUDA = (
    "Estoy aquí para apoyarte. ¿Qué te gustaría hacer a continuación?"
)

INICIO = (
    "¡Ya volví!\n\n"
    "Vamos a confirmar algunos datos de tu compra.\n"
    "El proceso toma menos de ⌚ 5 minutos y es necesario para activar tus beneficios 🎁\n\n"
    "Continuaremos tu verificación en base al folio: *{folio}*.\n\n"
    "¿Podemos comenzar?"
)

INICIO2 = (
    "Hola, soy Alonso 👋🏻\n\n"
    "Vamos a confirmar algunos datos de tu compra.\n"
    "El proceso toma menos de ⌚ 5 minutos y es necesario para activar tus beneficios 🎁\n\n"
    "Realizaremos tu verificación en base al folio: *{folio}*.\n\n"
    "¿Podemos comenzar?"
)

CONFIRMAR_NOMBRE = "📝 ¿Tu nombre completo es *{nombre_completo}*?"
CONFIRMAR_DOMICILIO = "🏠 ¿Tu domicilio es *{domicilio_completo}*?"
CONFIRMAR_FECHA = "📆 ¿El día en que suscribiste tu contrato fue el *{fecha_venta}*?"
CONFIRMAR_PRODUCTO = "🖥️🖨️ ¿El producto que adquiriste es {articulo} *{nombre_producto}*?"
CONFIRMAR_ESTADO_PRODUCTO = "📦 ¿Recibiste en buen estado tu *{nombre_producto}*?"

CONFIRMAR_COMPONENTES = (
    "📋 Corroboremos que hayas recibido todo completo:\n\n"
    "• 🔴 Un CPU de color rojo\n"
    "• 🖥️ Un Monitor o pantalla\n"
    "• ⌨️ Un Teclado\n"
    "• 🖱️ Un Mouse\n"
    "• 🔊 Un Par de bocinas\n"
    "• 🔌 Un Regulador de voltaje\n"
    "• 📶 Una Antena WiFi tipo USB\n\n"
    "¿Recibiste los 7 componentes?"
)

CONFIRMAR_PAGO = "💲 ¿Tu pago inicial fue por *${importe_pago_inicial}*?"

INFO_PAGOS = (
    "⏳ Realiza tu primer pago a más tardar el *{fecha_limite}*.\n\n"
    "🪙 El importe mínimo semanal es por *{pago_minimo}*.\n\n"
    "Puedes realizar tus pagos:\n"
    "• 📆 Quincenalmente por *${importe_quincenal}*\n"
    "• 📆 Mensualmente por *${importe_mensual}*\n"
    "(siempre y cuando lo hagas por adelantado)\n\n"
    "¿Está claro o tienes alguna duda respecto a los pagos?"
)

INFO_METODOS_PAGO = (
    "🏦 Aquí te dejo las opciones para realizar tus pagos.\n\n"
    "💳 No olvides incluir este número *A{numero_cuenta}* como concepto o referencia.\n\n"
    "Cada que hagas uno, deberás enviame tu comprobante por aquí 👇🏻 tan pronto como puedas para que lo aplique a tu estado de cuenta.\n\n"
    "¿Está claro o tienes alguna duda respecto a los métodos de pago?"
)

INFO_PLAN_3_MESES_DESCUENTO = (
    "🎓 Tu estudiante ha sido acreedor a un descuento de *${subsidio}* por su buen desempeño académico.\n\n"
)

INFO_PLAN_3_MESES = (
    "💲 El saldo de tu cuenta es de *${saldo_3_meses}*.\n\n"
    "⏳ Si deseas liquidar en 3 meses, tienes hasta *{fecha_limite_3_meses}* para cubrirlo con 13 pagos semanales (sugeridos) por *${importe_semanal_3m}*.\n\n"
    "¿Tienes alguna duda respecto al plan de 3 meses?"
)

INFO_OTROS_PLANES = (
    "📜 Recuerda que si excedes la fecha límite del plan de 3 meses automáticamente entrará en vigor el plan de 6 meses.\n\n"
    "¿Tienes alguna duda sobre los precios y planes de: 6, 9 , 12 , 15 y 18 meses estipulados en tu contrato (copia verde)?"
)

INFO_BENEFICIOS = (
    "🎉 ¡Felicidades! a partir de ahora puedes disfrutar de tu PC-MAXICA y de: :\n\n"
    "• 🛠️ Asesoría y Soporte Técnico\n"
    "• 🛡️ Garantía de 3 años sobre defectos de fabricación\n"
    "• 🎓 Programas y aplicaciones gratuitos\n"
    "• 🖨️ Impresora multifuncional de obsequio\n\n"
    "Recibirás tu multifuncional en un plazo máximo de 3 meses.\n"
    "Es importante que mantengas tu cuenta al corriente para no perder tus beneficios.\n\n"
    "¿Tienes alguna duda sobre tu contrato, póliza de garantía, o sobre el uso y funcionamiento de tu PC-MAXICA?"
)

INFO_BENEFICIOS2 = (
    "🎉 ¡Felicidades! a partir de ahora puedes disfrutar de tu *{producto}* y de :\n\n"
    "• 🛠️ Asesoría y Soporte Técnico\n"
    "• 🛡️ Garantía de 1 año sobre defectos de fabricación\n"
    "Es importante que mantengas tu cuenta al corriente para no perder tus beneficios.\n\n"
    "¿Tienes alguna duda sobre tu contrato o tu *{producto}*?"
)

FINALIZADO = (
    "✅ Verificación completada. Gracias por tu tiempo.\n\n"
    "¿Hay algo más en lo que te pueda ayudar?"
)

INCONSISTENCIA = "Entiendo. Por favor, indícame qué parte de la información está incorrecta."
INCONSISTENCIA_NOMBRE = "Entiendo. ¿Me podrías escribir cómo es tu nombre correcto, por favor?"
INCONSISTENCIA_DOMICILIO = "Entiendo. Para tenerlo registrado, ¿me podrías indicar brevemente qué dato falta o está equivocado en tu domicilio?"
INCONSISTENCIA_FECHA = "Entiendo. ¿Me podrías indicar cuál es la fecha correcta de tu compra?"
INCONSISTENCIA_PRODUCTO = "Entiendo. ¿Me podrías confirmar cómo se llama o qué marca es el producto que recibiste?"
INCONSISTENCIA_ESTADO_PRODUCTO = "Lamento escuchar eso. ¿Me podrías describir brevemente cuál es el detalle o falla que presenta tu producto?"
INCONSISTENCIA_PAGO_INICIAL = "Entiendo. ¿Cuál fue el importe exacto que diste de pago inicial?"

FUERA_DE_FLUJO = (
    "💬 Gracias por tu mensaje.\n\n"
    "Fuera de flujo, un asesor te contactará para atender tu caso."
)

ACLARACION = "Entendido. Voy a transferir tu caso con un asesor para que te brinde atención personalizada lo más pronto posible."

RECORDATORIO_1H = (
    "👋🏼 Solo paso a recordarte que podemos continuar con tu verificación cuando gustes.\n\n"
    "El proceso tarda menos de 5 minutos."
)

RECORDATORIO_2H = (
    "⏰ Último recordatorio por ahora.\n\n"
    "Cuando estés listo podemos continuar con tu verificación."
)

RECORDATORIO_24H = (
    "🌞 ¡Buen día! Seguimos pendientes de tu verificación para activar tus beneficios.\n\n"
    "Solo te tomará un par de minutos terminar."
)

RECORDATORIO_CONFIRMACION = "Entendido. Pondré la verificación en pausa. Te enviaré un recordatorio más tarde para que podamos continuar."

PREGUNTA_DUDA = "¡Claro que sí! Platícame, ¿qué duda tienes? Estoy aquí para apoyarte."
PEDIR_FOLIO = "✏️ Por favor, envíame tu número de folio."
PEDIR_FOLIO_INICIO = "✏️ Por favor indícame tu número de folio para comenzar."
PEDIR_FOLIO_DEVOLUCION = "Para poder iniciar tu proceso de devolución, primero indícame tu número de folio, por favor."
PEDIR_FOLIO_DESCUENTO = "Para poder darte mas detalles de tu cuenta, primero indícame tu número de folio, por favor."
CONFIRMAR_FOLIO_DETECTADO = "🔎 Detecté tu folio: *{folio}*. ¿Es correcto?"
FOLIO_NO_DETECTADO = "Lo siento, ese folio no parece estar registrado. Por favor intentalo de nuevo."
FOLIO_NO_EXISTE = "🔍 ¡Ups! No logré localizar ese número de folio en mi sistema."
CONTINUAR_VERIFICACION = "🔁 Continuemos con la verificación:"
CONTINUAR_VERIFICACION_MENU = "🔁 Continuemos con la verificación."
CORRECCION_REGISTRADA = "✅ Entendido, ya registré la corrección.\n\nContinuemos con la verificación."
AYUDA_ALGO_MAS = "Entendido. ¿Te puedo ayudar con algo más?"
EN_QUE_MAS_AYUDAR = "¿Hay algo más en lo que te pueda ayudar?"

ESCALAMIENTO_CRITICO = "⚠️ Detectamos un detalle en la información.\n\nUn asesor revisará tu caso para ayudarte mejor."
ESCALAMIENTO_MULTIPLES = "⚠️ Detectamos varias inconsistencias en la información.\n\nUn asesor revisará tu caso para ayudarte mejor."
NO_ENTENDIDO = "No entendí completamente tu respuesta."
ERROR_IA = "🤖 No pude procesar tu duda en este momento."
VERIFICAR_FOTO_COMPONENTE = "Te envío una foto de referencia de: *{componente}*.\n\nPor favor revisa bien tu paquete, ¿estás absolutamente seguro de que NO lo recibiste?"
CONFIRMAR_COMPONENTE_FALTANTE = "✅ Registrado. Confirmamos que te falta: *{componente}*\n\n¿Deseas reportar que faltó algún otro componente diferente?"
FOTO_YA_LO_VI = "✅ ¡Qué bueno que lo encontraste!\n\n¿Deseas reportar que faltó algún otro componente diferente?"
PEDIR_MOTIVO_DEVOLUCION = "Por favor indícanos el motivo de la devolución."
DEVOLUCION_FINALIZADA = "Gracias por la información.\n\nUn asesor se pondrá en contacto contigo para continuar con el proceso de devolución."

# Security Challenge
RETO_SEGURIDAD_SOLICITUD = (
    "Para proteger tu privacidad, por favor escribe únicamente el *primer nombre* de la persona a la que quedó registrada esta compra."
)
RETO_SEGURIDAD_EXITO = "🚀 Muy bien, ¡comencemos!"
RETO_SEGURIDAD_FALLO = (
    "El nombre no coincide con nuestros registros. "
    "Por favor, intenta de nuevo escribiendo únicamente el *primer nombre* del titular.\n\n"
    "*(Te quedan {intentos_restantes} intentos)*"
)
RETO_SEGURIDAD_BLOQUEO = (
    "Hemos agotado los intentos permitidos.\n\n"
    "Por motivos de seguridad, la consulta de este folio ha sido bloqueada temporalmente en este chat. "
    "Un asesor humano se comunicará a este número más tarde para continuar tu proceso de forma segura."
)

SALA_ESPERA = (
    f"{ESPERA}\n\n"
    "✅ He detectado tu folio: *{folio}*.\n\n"
    "Si tu folio es correcto, no necesitas hacer nada, solo espera a que te contacte. Si te equivocaste al ingresarlo, por favor cámbialo tocando el botón de abajo 👇🏻"
)

MULTIPLES_FOLIOS_PENDIENTES = "¡Hola! Veo que tienes {cantidad} compras pendientes por verificar con nosotros. Por favor, selecciona el folio con el que deseas continuar:"
