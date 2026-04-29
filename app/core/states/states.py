from enum import Enum


class ChatState(str, Enum):
    # -------------------------
    # Sistema / control
    # -------------------------
    ESPERA = "ESPERA"
    INICIO = "INICIO"
    INICIO2 = "INICIO2"
    SELECCIONAR_FOLIO = "SELECCIONAR_FOLIO"
    ESPERANDO_REGISTRO = "ESPERANDO_REGISTRO"
    RETO_SEGURIDAD = "RETO_SEGURIDAD"

    RECORDATORIO_1H = "RECORDATORIO_1H"
    RECORDATORIO_2H = "RECORDATORIO_2H"
    RECORDATORIO = "RECORDATORIO"

    FINALIZADO = "FINALIZADO"

    # -------------------------
    # Navegación
    # -------------------------
    CAMBIAR_FOLIO = "CAMBIAR_FOLIO"
    CAMBIAR_FOLIO_DEVOLUCION = "CAMBIAR_FOLIO_DEVOLUCION"
    CONFIRMAR_FOLIO_DEVOLUCION = "CONFIRMAR_FOLIO_DEVOLUCION"
    CAMBIAR_FOLIO_DESCUENTO = "CAMBIAR_FOLIO_DESCUENTO"
    CONFIRMAR_FOLIO_DESCUENTO = "CONFIRMAR_FOLIO_DESCUENTO"
    MENU_AYUDA = "MENU_AYUDA"
    MENU_DUDA = "MENU_DUDA"

    # -------------------------
    # Confirmaciones
    # -------------------------
    CONFIRMAR_NOMBRE = "CONFIRMAR_NOMBRE"
    CONFIRMAR_DOMICILIO = "CONFIRMAR_DOMICILIO"
    CONFIRMAR_FECHA = "CONFIRMAR_FECHA"
    CONFIRMAR_PRODUCTO = "CONFIRMAR_PRODUCTO"
    CONFIRMAR_ESTADO_PRODUCTO = "CONFIRMAR_ESTADO_PRODUCTO"
    CONFIRMAR_COMPONENTES = "CONFIRMAR_COMPONENTES"
    CONFIRMAR_PAGO_INICIAL = "CONFIRMAR_PAGO_INICIAL"

    # -------------------------
    # Componentes
    # -------------------------
    COMPONENTES_FALTANTES = "COMPONENTES_FALTANTES"
    VERIFICAR_FOTO_COMPONENTE = "VERIFICAR_FOTO_COMPONENTE"
    COMPONENTES_CONFIRMAR_FALTANTES = "COMPONENTES_CONFIRMAR_FALTANTES"

    # -------------------------
    # Información
    # -------------------------
    INFO_PAGOS = "INFO_PAGOS"
    INFO_METODOS_PAGO = "INFO_METODOS_PAGO"
    INFO_PLAN_3_MESES = "INFO_PLAN_3_MESES"
    INFO_OTROS_PLANES = "INFO_OTROS_PLANES"
    INFO_BENEFICIOS = "INFO_BENEFICIOS"
    INFO_BENEFICIOS2 = "INFO_BENEFICIOS2"

    # -------------------------
    # Estados inteligentes
    # -------------------------
    FUERA_DE_FLUJO = "FUERA_DE_FLUJO"   
    DUDA = "DUDA"                       # duda en preguntas de informacion
    INCONSISTENCIA = "INCONSISTENCIA"   # dato incorrecto en preguntas confirmacion

    # -------------------------
    # Escalamiento
    # -------------------------
    ACLARACION = "ACLARACION"           # cuando se escala con humano
    LLAMADA = "LLAMADA"                 # cuando se solicita una llamada 

    # -------------------------
    # Devoluciones
    # -------------------------
    DEVOLUCION_CONFIRMAR = "DEVOLUCION_CONFIRMAR"
    DEVOLUCION_MOTIVO = "DEVOLUCION_MOTIVO"
    DEVOLUCION_FINALIZADA = "DEVOLUCION_FINALIZADA"