from typing import Optional
import datetime
import decimal
import enum

from sqlalchemy import Column, DECIMAL, Date, DateTime, Double, Enum, ForeignKeyConstraint, Index, Integer, String, TIMESTAMP, Table, Text, Time, text
from sqlalchemy.dialects.mysql import ENUM, FLOAT, INTEGER, LONGTEXT, MEDIUMTEXT, TEXT, TINYINT, TINYTEXT, VARCHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class SolicitudesCambioUrgencia(str, enum.Enum):
    MUY_URGENTE = 'Muy Urgente'
    URGENTE = 'Urgente'
    MODERADA = 'Moderada'
    NO_URGENTE = 'No Urgente'
    POCO_URGENTE = 'Poco Urgente'


class AdjuntosColaboradores(Base):
    __tablename__ = 'adjuntos_colaboradores'

    id_adj_col: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_ac: Mapped[int] = mapped_column(Integer, nullable=False)
    identificador: Mapped[Optional[str]] = mapped_column(TEXT)
    nombre_archivo: Mapped[Optional[str]] = mapped_column(TEXT)
    archivo: Mapped[Optional[str]] = mapped_column(TEXT)


t_adjuntos_comprobante_salida = Table(
    'adjuntos_comprobante_salida', Base.metadata,
    Column('id_comp', Integer, nullable=False),
    Column('id_emp_comp_s', Integer),
    Column('no_serie', VARCHAR(50)),
    Column('comprobante', TEXT),
    Column('fecha', Date)
)


t_adjuntos_soporte_tecnico = Table(
    'adjuntos_soporte_tecnico', Base.metadata,
    Column('id_adjunto_s', Integer, nullable=False),
    Column('id_emp_adj_s', Integer),
    Column('nombre_archivo', TEXT),
    Column('id_movimiento_adj', VARCHAR(15))
)


class AdjuntosSucursalMovil(Base):
    __tablename__ = 'adjuntos_sucursal_movil'

    id_adjunt_vh: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_adv: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre_vehiculo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_archivo: Mapped[Optional[str]] = mapped_column(TEXT)
    archivo: Mapped[Optional[str]] = mapped_column(TEXT)


class BitacoraActualizacionPreciosUtilidades(Base):
    __tablename__ = 'bitacora_actualizacion_precios_utilidades'

    id_registro: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_compra: Mapped[Optional[int]] = mapped_column(Integer)
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_serie: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    precio_anterior: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    costo_compra: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_nuevo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    usuario: Mapped[Optional[str]] = mapped_column(TEXT)
    id_emp_bit_apu: Mapped[Optional[int]] = mapped_column(Integer)


class BitacoraActualizacionProducto(Base):
    __tablename__ = 'bitacora_actualizacion_producto'

    id_act_prod: Mapped[int] = mapped_column(Integer, primary_key=True)
    estado_proceso: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    mensaje_error: Mapped[Optional[str]] = mapped_column(TEXT)
    sku_producto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    fecha_creacion: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))


class BitacoraActualizacionResguardos(Base):
    __tablename__ = 'bitacora_actualizacion_resguardos'

    id_actualizacion: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(45), nullable=False)
    estatus: Mapped[int] = mapped_column(Integer, nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_actualizacion: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))


class BitacoraInventario(Base):
    __tablename__ = 'bitacora_inventario'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_b_inv: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_b_inv: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    movimiento: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    noserie: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    codigo_barras: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    producto: Mapped[Optional[str]] = mapped_column(TEXT)
    costo_unitario: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    cantidad: Mapped[Optional[int]] = mapped_column(Integer)
    origen: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    destino: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    categoria_d: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    categoria_o: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    concepto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    observaciones: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    usuario: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    fecha_movimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)


class BitacoraVentas(Base):
    __tablename__ = 'bitacora_ventas'

    id_venta_b: Mapped[int] = mapped_column(Integer, primary_key=True)
    devolucion: Mapped[int] = mapped_column(TINYINT(1), nullable=False, server_default=text("'0'"))
    serie: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    id_emp_bv: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_bv: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento_bv: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    id_anticipo_bv: Mapped[Optional[str]] = mapped_column(VARCHAR(45), server_default=text("'0'"))
    tipo_movimiento: Mapped[Optional[int]] = mapped_column(Integer)
    no_cuenta: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    identificador: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    nombre_completo: Mapped[Optional[str]] = mapped_column(TEXT)
    email: Mapped[Optional[str]] = mapped_column(TEXT)
    tel_1: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    tel_2: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    tel_3: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    tiene_ns_bv: Mapped[Optional[str]] = mapped_column(VARCHAR(5))
    no_serie: Mapped[Optional[str]] = mapped_column(TEXT)
    sku_bitacora_v: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    codigo_barras_bv: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    garantia: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    cantidad: Mapped[Optional[str]] = mapped_column(TEXT)
    medida: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    precio_unitario: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_unitario_s_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    total_s_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    total_c_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    importe: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    pago: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    cambio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    metodo_pago: Mapped[Optional[str]] = mapped_column(TEXT)
    p_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 0), server_default=text("'0'"))
    t_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 0), server_default=text("'0'"))
    apartado: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    contado: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    credito: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    liquidacion: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    cancelacion: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    fecha_venta: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    usuario: Mapped[Optional[str]] = mapped_column(TEXT)
    corte: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    fecha_corte: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    folio: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    subsidio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))

    ventas_documentos: Mapped[list['VentasDocumentos']] = relationship('VentasDocumentos', back_populates='bitacora_ventas')


class Cancelaciones(Base):
    __tablename__ = 'cancelaciones'

    id_cancelacion: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_mov_cancelacion: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tiene_ns: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    no_serie_cancelado: Mapped[Optional[str]] = mapped_column(TEXT)
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    motivo_cancelacion: Mapped[Optional[int]] = mapped_column(Integer)


class CarteraCuentasTemp(Base):
    __tablename__ = 'cartera_cuentas_temp'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp: Mapped[int] = mapped_column(Integer, nullable=False)
    agente_verificador: Mapped[str] = mapped_column(Text, nullable=False)
    atrasos: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    cod_cli: Mapped[str] = mapped_column(String(45), nullable=False)
    cuenta: Mapped[str] = mapped_column(String(200), nullable=False)
    importe_renta: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    nombre_completo: Mapped[str] = mapped_column(Text, nullable=False)
    total_vencido: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    fecha_modifica: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    nombre_usuario_modifica: Mapped[Optional[str]] = mapped_column(Text)
    nombre_usuario_gestor: Mapped[Optional[str]] = mapped_column(String(45))
    nombre_resumido: Mapped[Optional[str]] = mapped_column(Text)


class Categorias(Base):
    __tablename__ = 'categorias'

    id_categoria: Mapped[int] = mapped_column(INTEGER, primary_key=True)
    id_emp: Mapped[int] = mapped_column(Integer, nullable=False)
    categoria: Mapped[str] = mapped_column(VARCHAR(60), nullable=False)


class ChatSessions(Base):
    __tablename__ = 'chat_sessions'
    __table_args__ = (
        Index('idx_folio', 'folio'),
        Index('idx_phone', 'phone'),
        Index('uq_chat_phone', 'phone', unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    state: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    folio: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    previous_state: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    last_message: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_message_id: Mapped[Optional[str]] = mapped_column(VARCHAR(100))


class Clientes(Base):
    __tablename__ = 'clientes'
    __table_args__ = (
        Index('id_cliente', 'id_cliente'),
    )

    id_cliente: Mapped[int] = mapped_column(Integer, primary_key=True)
    cod_cliente: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tipo_tel_1: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    id_emp_cli: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_cli: Mapped[Optional[int]] = mapped_column(Integer)
    tipo_cliente: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    password: Mapped[Optional[str]] = mapped_column(TEXT)
    condiciones: Mapped[Optional[str]] = mapped_column(TEXT)
    temp_pass: Mapped[Optional[str]] = mapped_column(TINYTEXT)
    titulo: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    Nombre: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    apellido_p: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_m: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_completo: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    genero: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    curp: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_nac: Mapped[Optional[datetime.date]] = mapped_column(Date)
    estado_civil: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_comercial: Mapped[Optional[str]] = mapped_column(TEXT)
    rfc: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    tipo_calle: Mapped[Optional[str]] = mapped_column(VARCHAR(90))
    calle: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    codigo_postal: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    colonia: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    dir_completa: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    municipio: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    referencias_domicilio: Mapped[Optional[str]] = mapped_column(TEXT)
    latitud: Mapped[Optional[float]] = mapped_column(FLOAT(9, 6))
    longitud: Mapped[Optional[float]] = mapped_column(FLOAT(9, 6))
    tel1: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    tel2: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    tipo_tel_2: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel3: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    tipo_tel_3: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    email: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    facebook: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    instagram: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    twitter: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    empresa: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    puesto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    anos: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    meses: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    calledl: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    noextdl: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    nointdl: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    cpdl: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    coloniadl: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    estadodl: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    poblaciondl: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    telefonodl: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    upd_date: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    create_date: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    es_aval_de: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    es_referencia_de: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class ClientesAval(Base):
    __tablename__ = 'clientes_aval'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no_cuenta: Mapped[str] = mapped_column(VARCHAR(11), nullable=False)
    cliente: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    aval: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    referencia_uno: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    referencia_dos: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    referencia_tres: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class ClientesCreditoDirecto(Base):
    __tablename__ = 'clientes_credito_directo'

    id_credito: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_cd: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo_cliente: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    plazo: Mapped[Optional[int]] = mapped_column(Integer)
    maximo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    moratorio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    correo: Mapped[Optional[str]] = mapped_column(TEXT)
    autorizo: Mapped[Optional[str]] = mapped_column(TEXT)


class Colaboradores(Base):
    __tablename__ = 'colaboradores'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre_resumido: Mapped[str] = mapped_column(TEXT, nullable=False)
    premisas: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    estatus: Mapped[int] = mapped_column(Integer, nullable=False)
    id_emp_col: Mapped[Optional[int]] = mapped_column(Integer)
    id_matriz_col: Mapped[Optional[int]] = mapped_column(Integer)
    fecha_ingreso: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_p: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_m: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_completo: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_nac: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    curp: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    rfc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    grado_estudios: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    profesion: Mapped[Optional[str]] = mapped_column(TEXT)
    domicilio: Mapped[Optional[str]] = mapped_column(TEXT)
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    colonia: Mapped[Optional[str]] = mapped_column(TEXT)
    cp: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    poblacion: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel1: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel2: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel3: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    correo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    puesto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    jefe_directo: Mapped[Optional[str]] = mapped_column(TEXT)
    tipo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tipo_usu: Mapped[Optional[int]] = mapped_column(Integer)
    nombre_usuario: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    contrasena: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    nss: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cuenta_bancaria: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    institucion_bancaria: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    last_login: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    image: Mapped[Optional[str]] = mapped_column(VARCHAR(255), server_default=text("'no_image.jpg'"))


class Compra(Base):
    __tablename__ = 'compra'

    id_compra: Mapped[int] = mapped_column(Integer, primary_key=True)
    estatus: Mapped[int] = mapped_column(Integer, nullable=False)
    estatus_nc: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("'0'"))
    id_movimiento_c: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    sku_compra: Mapped[Optional[str]] = mapped_column(TEXT)
    codigo_b_compra: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    proveedor: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    costo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    utilidad_deseada: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    utilidad_minima: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    costo_venta: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    cantidad_compra: Mapped[Optional[int]] = mapped_column(Integer)
    cantidad: Mapped[Optional[int]] = mapped_column(Integer)
    cantidad_inicial: Mapped[Optional[int]] = mapped_column(Integer)
    medida: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    sub_total: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    iva_total: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    gran_total: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    observaciones: Mapped[Optional[str]] = mapped_column(TEXT)
    folio: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cfid: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    forma_pago: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    metodo_pago: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    fecha_compra: Mapped[Optional[datetime.date]] = mapped_column(Date)
    usuario: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    id_suc_compra: Mapped[Optional[int]] = mapped_column(Integer)
    id_emp_compra: Mapped[Optional[int]] = mapped_column(Integer)


class ComprasComprobantesFiscales(Base):
    __tablename__ = 'compras_comprobantes_fiscales'

    id_comp_fiscal: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_comp_fiscal: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento_comp_fiscal: Mapped[Optional[str]] = mapped_column(VARCHAR(15))
    comprobante_fiscal: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_registro: Mapped[Optional[datetime.date]] = mapped_column(Date)


class ContactosProveedor(Base):
    __tablename__ = 'contactos_proveedor'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_cprov: Mapped[Optional[int]] = mapped_column(Integer)
    proveedor: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    relacion: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    extension: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel_particular: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    email: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class CortesCaja(Base):
    __tablename__ = 'cortes_caja'

    id_corte: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha_inicio: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    fecha_final: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    usuario: Mapped[str] = mapped_column(Text, nullable=False)
    generado_por: Mapped[str] = mapped_column(Text, nullable=False)
    corte_de: Mapped[str] = mapped_column(String(55), nullable=False)
    id_emp_corte: Mapped[Optional[int]] = mapped_column(Integer)
    total: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))


class CortesRelacionCuentas(Base):
    __tablename__ = 'cortes_relacion_cuentas'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gestor: Mapped[str] = mapped_column(TEXT, nullable=False)
    fecha_corte: Mapped[datetime.date] = mapped_column(Date, nullable=False)


class Cotizaciones(Base):
    __tablename__ = 'cotizaciones'

    id_cotiz: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_cotiz: Mapped[Optional[int]] = mapped_column(Integer)
    folio_cotiz: Mapped[Optional[str]] = mapped_column(String(45))
    tipo_cotiz: Mapped[Optional[int]] = mapped_column(Integer)
    almacen: Mapped[Optional[str]] = mapped_column(Text)
    sku: Mapped[Optional[str]] = mapped_column(String(45))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    cantidad: Mapped[Optional[int]] = mapped_column(Integer)
    precio_s_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_c_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    total_s_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    iva_total: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    total_c_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    apartado: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    fecha: Mapped[Optional[str]] = mapped_column(String(40))
    cliente: Mapped[Optional[str]] = mapped_column(Text)
    asesor: Mapped[Optional[str]] = mapped_column(Text)


class Cuentas(Base):
    __tablename__ = 'cuentas'
    __table_args__ = (
        Index('cuenta', 'cuenta'),
    )

    id_cuenta: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_suc_cuenta: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_act: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("'0'"))
    orden_servicio: Mapped[int] = mapped_column(TINYINT(1), nullable=False, server_default=text("'0'"))
    fecha_venta_domicilio: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    id_emp_cuenta: Mapped[Optional[int]] = mapped_column(Integer)
    fecha_venta: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    cuenta: Mapped[Optional[str]] = mapped_column(VARCHAR(200))
    cod_cli: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    producto: Mapped[Optional[str]] = mapped_column(TEXT)
    garantia: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    pago_inicial: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    enganche: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    plazo: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    precio_contado: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    saldo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    pagos_minimos: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    liquida: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    vencido: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    atrasos: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    moratorio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    estatus: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    num: Mapped[Optional[int]] = mapped_column(Integer)
    proceso: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    tipo_cuenta: Mapped[Optional[int]] = mapped_column(Integer)
    ultimo_pago: Mapped[Optional[datetime.date]] = mapped_column(Date)
    asesor: Mapped[Optional[str]] = mapped_column(TEXT)
    agente_verificador: Mapped[Optional[str]] = mapped_column(TEXT)
    observaciones: Mapped[Optional[str]] = mapped_column(TEXT)
    dni: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    comprobante_domicilio: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    vinculo: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    ubi_geografica: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    foto_casa: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    foto_qr: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    verif_venta: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    pago_ini: Mapped[Optional[str]] = mapped_column(VARCHAR(2))
    fecha_documentos: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    precio_a_credito: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 2))


class CuentasComprobantes(Base):
    __tablename__ = 'cuentas_comprobantes'

    id_comprobante: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_cliente: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    comprobante: Mapped[str] = mapped_column(TEXT, nullable=False)
    fecha_registro: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    id_emp_comprobante: Mapped[int] = mapped_column(Integer, nullable=False)


class Departamentos(Base):
    __tablename__ = 'departamentos'

    id_depto: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_depto: Mapped[int] = mapped_column(Integer, nullable=False)
    departamento: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class DescuentosBitacora(Base):
    __tablename__ = 'descuentos_bitacora'

    id_desc: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_descuento: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    descripcion: Mapped[str] = mapped_column(TEXT, nullable=False)
    utilidad_deseada: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 3), nullable=False)
    utilidad_minima: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 3), nullable=False)
    precio_inicial: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    descuento_minimo: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    precio_descuento: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    autorizo: Mapped[str] = mapped_column(TEXT, nullable=False)
    fecha: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    no_serie: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class DomiciliosCobro(Base):
    __tablename__ = 'domicilios_cobro'
    __table_args__ = {'comment': ' `gps`, `referencias`, `gestor`, `asesor`'}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cod: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cuenta: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    parentesco: Mapped[Optional[str]] = mapped_column(VARCHAR(40))
    encargado_n: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    encargado_ap: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    encargado_am: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    dir_completa: Mapped[Optional[str]] = mapped_column(TEXT)
    calle: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    colonia: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    cp: Mapped[Optional[str]] = mapped_column(TEXT)
    estado: Mapped[Optional[str]] = mapped_column(TEXT)
    municipio: Mapped[Optional[str]] = mapped_column(TEXT)
    tel: Mapped[Optional[str]] = mapped_column(VARCHAR(15))
    gps: Mapped[Optional[str]] = mapped_column(TEXT)
    referencia_gc: Mapped[Optional[str]] = mapped_column(TEXT)
    asesor: Mapped[Optional[str]] = mapped_column(TEXT)
    gestor: Mapped[Optional[str]] = mapped_column(TEXT)
    id_emp_dom_cobro: Mapped[Optional[int]] = mapped_column(Integer)


class DomiciliosHorariosEntrega(Base):
    __tablename__ = 'domicilios_horarios_entrega'

    id_d_h: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_d_h: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    suc_entrega: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    tipo_de_vialidad: Mapped[Optional[str]] = mapped_column('tipo de vialidad', VARCHAR(60))
    nombre_vialidad: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    colonia: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    codigo_postal: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    ciudad: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    referencias: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    lat_ubicacion: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    lon_ubicacion: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    nombre_q_recibe: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    tel_entrega: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    tipo_tel_entrega: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    dia_semana: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    hora_inicio: Mapped[Optional[str]] = mapped_column(VARCHAR(40))
    hora_final: Mapped[Optional[str]] = mapped_column(VARCHAR(40))


class Empresas(Base):
    __tablename__ = 'empresas'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre_empresa: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    logotipo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    calle_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_ext_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_int_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    colonia_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cp_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    estado_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    poblacion_dc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    razon_social: Mapped[Optional[str]] = mapped_column(TEXT)
    rfc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    calle_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_ext_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_int_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    colonia_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cp_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    estado_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    poblacion_df: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    giro: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_creacion: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel1: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel2: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tel3: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    pagina_web: Mapped[Optional[str]] = mapped_column(TEXT)


class EntradaCompra(Base):
    __tablename__ = 'entrada_compra'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    id_suc_ec: Mapped[int] = mapped_column(Integer, nullable=False)
    id_movimiento_ec: Mapped[Optional[str]] = mapped_column(VARCHAR(12))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    destino: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    categoria: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    proveedor: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cantidad: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    medida: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    noserie: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    observaciones: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    fecha_recepcion: Mapped[Optional[datetime.date]] = mapped_column(Date)
    id_emp_ec: Mapped[Optional[int]] = mapped_column(Integer)


class Estado(Base):
    __tablename__ = 'estado'

    idestado: Mapped[int] = mapped_column(Integer, primary_key=True)
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class EstadosCuenta(Base):
    __tablename__ = 'estados_cuenta'
    __table_args__ = (
        Index('cuenta', 'cuenta_e'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corte: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default=text("'0'"))
    cuenta_e: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    id_item: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    producto_s: Mapped[Optional[str]] = mapped_column(TEXT)
    concepto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    metodo_pago: Mapped[Optional[int]] = mapped_column(Integer)
    cantidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    p_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    t_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    fecha_pago: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    saldo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    id_emp_estado_cuenta: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_estado_cuenta: Mapped[Optional[int]] = mapped_column(Integer)
    usuario: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_corte: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)


class EstadosCuentaDuplicate(Base):
    __tablename__ = 'estados_cuenta_duplicate'
    __table_args__ = (
        Index('cuenta', 'cuenta_e'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corte: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default=text("'0'"))
    cuenta_e: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    id_item: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    producto_s: Mapped[Optional[str]] = mapped_column(TEXT)
    concepto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    metodo_pago: Mapped[Optional[int]] = mapped_column(Integer)
    cantidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    p_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    t_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    fecha_pago: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    saldo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    id_emp_estado_cuenta: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_estado_cuenta: Mapped[Optional[int]] = mapped_column(Integer)
    usuario: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_corte: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)


class EstudioSocioeconomico(Base):
    __tablename__ = 'estudio_socioeconomico'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_empresa: Mapped[int] = mapped_column(Integer, nullable=False)
    cliente: Mapped[str] = mapped_column(Text, nullable=False)
    grado_estudios: Mapped[str] = mapped_column(String(50), nullable=False)
    banos_regadera: Mapped[int] = mapped_column(Integer, nullable=False)
    vehiculos: Mapped[int] = mapped_column(Integer, nullable=False)
    internet: Mapped[int] = mapped_column(TINYINT(1), nullable=False)
    trabajaron_mes: Mapped[int] = mapped_column(Integer, nullable=False)
    cuartos_dormir: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo_casa: Mapped[str] = mapped_column(String(30), nullable=False)
    ingreso_mensual: Mapped[str] = mapped_column(String(50), nullable=False)
    dependientes: Mapped[int] = mapped_column(Integer, nullable=False)
    deudas: Mapped[int] = mapped_column(TINYINT(1), nullable=False)
    gastos_mensuales: Mapped[str] = mapped_column(String(40), nullable=False)
    sillones: Mapped[int] = mapped_column(Integer, nullable=False)
    pantallas: Mapped[int] = mapped_column(Integer, nullable=False)
    comedores: Mapped[int] = mapped_column(Integer, nullable=False)
    computadoras: Mapped[int] = mapped_column(Integer, nullable=False)
    lavadoras: Mapped[int] = mapped_column(Integer, nullable=False)
    consolas_video: Mapped[int] = mapped_column(Integer, nullable=False)
    microondas: Mapped[int] = mapped_column(Integer, nullable=False)
    estereo: Mapped[int] = mapped_column(Integer, nullable=False)
    empleo: Mapped[str] = mapped_column(String(50), nullable=False)
    detalles_empleo: Mapped[str] = mapped_column(Text, nullable=False)
    tipo_vialidad_empleo: Mapped[Optional[str]] = mapped_column(Text)
    nombre_vialidad_empleo: Mapped[Optional[str]] = mapped_column(Text)
    no_ext_empleo: Mapped[Optional[str]] = mapped_column(Text)
    no_int_empleo: Mapped[Optional[str]] = mapped_column(Text)
    colonia_empleo: Mapped[Optional[str]] = mapped_column(Text)
    codigo_postal_empleo: Mapped[Optional[str]] = mapped_column(Text)
    estado_empleo: Mapped[Optional[str]] = mapped_column(Text)
    ciudad_municipio_empleo: Mapped[Optional[str]] = mapped_column(Text)
    referencias_dom_empleo: Mapped[Optional[str]] = mapped_column(Text)
    ubicacion_lat_empleo: Mapped[Optional[str]] = mapped_column(Text)
    ubicacion_lon_empleo: Mapped[Optional[str]] = mapped_column(Text)
    puntaje_estudio_socioeconomico: Mapped[Optional[str]] = mapped_column(Text)
    nivel_estudio_socioeconomico: Mapped[Optional[str]] = mapped_column(Text)
    capacidad_de_pago: Mapped[Optional[str]] = mapped_column(Text)
    preevaluacion_resultado: Mapped[Optional[str]] = mapped_column(Text)


class Inventario(Base):
    __tablename__ = 'inventario'
    __table_args__ = (
        Index('serie', 'noserie'),
        Index('sku', 'sku')
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_inv: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_inv: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento_inv: Mapped[Optional[str]] = mapped_column(VARCHAR(12))
    fecha_entrada: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    movimiento: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tiene_ns: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    noserie: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    codigo_barras: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    producto: Mapped[Optional[str]] = mapped_column(TEXT)
    costo_unitario: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    cantidad: Mapped[Optional[int]] = mapped_column(Integer)
    medida: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    origen: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    destino: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    categoria_d: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    categoria_o: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    concepto: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    observaciones: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    usuario: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class Marca(Base):
    __tablename__ = 'marca'

    id_marca: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp: Mapped[int] = mapped_column(Integer, nullable=False)
    marca: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)


class Matrices(Base):
    __tablename__ = 'matrices'

    id_matriz: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_empresa: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    matriz: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    calle: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    no_int: Mapped[str] = mapped_column(VARCHAR(11), nullable=False)
    no_ext: Mapped[str] = mapped_column(VARCHAR(11), nullable=False)
    cp: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    colonia: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    estado: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    municipio: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tel1: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tel2: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tel3: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    observaciones: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)


class Menu(Base):
    __tablename__ = 'menu'

    id_menu: Mapped[int] = mapped_column(Integer, primary_key=True)
    menu: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class MetodosPago(Base):
    __tablename__ = 'metodos_pago'

    id_metodo: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_mp: Mapped[int] = mapped_column(Integer, nullable=False)
    prefijo: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    metodo_pago: Mapped[str] = mapped_column(TEXT, nullable=False)
    comprobante: Mapped[int] = mapped_column(Integer, nullable=False)


class MotivosCancelacion(Base):
    __tablename__ = 'motivos_cancelacion'

    id_motivo: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_motivo: Mapped[Optional[int]] = mapped_column(Integer)
    motivo: Mapped[Optional[str]] = mapped_column(TEXT)


class NotaCredito(Base):
    __tablename__ = 'nota_credito'

    id_nota_c: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_nota: Mapped[Optional[int]] = mapped_column(Integer)
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    unidades: Mapped[Optional[int]] = mapped_column(Integer)
    cantidad: Mapped[Optional[int]] = mapped_column(Integer)
    almacen: Mapped[Optional[str]] = mapped_column(TEXT)
    adjunto: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_registro: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    usuario: Mapped[Optional[str]] = mapped_column(TEXT)


class Permisos(Base):
    __tablename__ = 'permisos'

    id_p: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_per: Mapped[int] = mapped_column(Integer, nullable=False)
    id_modulo: Mapped[int] = mapped_column(Integer, nullable=False)
    id_sub_modulo: Mapped[int] = mapped_column(Integer, nullable=False)
    permiso: Mapped[int] = mapped_column(Integer, nullable=False)
    identificador: Mapped[Optional[int]] = mapped_column(Integer)
    seleccionar: Mapped[Optional[int]] = mapped_column(Integer)
    editar: Mapped[Optional[int]] = mapped_column(Integer)
    eliminar: Mapped[Optional[int]] = mapped_column(Integer)
    puesto: Mapped[Optional[str]] = mapped_column(TEXT)


class PlanesPago(Base):
    __tablename__ = 'planes_pago'
    __table_args__ = (
        Index('fecha_inicio', 'fecha_inicio', unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha_inicio: Mapped[Optional[datetime.date]] = mapped_column(Date)
    fecha_terminado: Mapped[Optional[datetime.date]] = mapped_column(Date)
    enganche: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(20, 2))
    pago_minimo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(20, 2))
    plan_3: Mapped[Optional[int]] = mapped_column(Integer)
    plan_6: Mapped[Optional[int]] = mapped_column(Integer)
    plan_9: Mapped[Optional[int]] = mapped_column(Integer)
    plan_12: Mapped[Optional[int]] = mapped_column(Integer)
    plan_15: Mapped[Optional[int]] = mapped_column(Integer)
    plan_18: Mapped[Optional[int]] = mapped_column(Integer)
    id_item: Mapped[Optional[int]] = mapped_column(Integer)


class Poblacion(Base):
    __tablename__ = 'poblacion'

    idPoblacion: Mapped[int] = mapped_column(Integer, primary_key=True)
    poblacion: Mapped[Optional[str]] = mapped_column(VARCHAR(95))
    idestado: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class PreciosProductoUnidad(Base):
    __tablename__ = 'precios_producto_unidad'

    id_prd_unidad: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_producto: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    tipo_costo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    costo_sin_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    utilidad_deseada: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    utilidad_minima: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    precio_contado_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    plazo_x_unidad: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    porcentaje_interes_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    enganche_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_credito_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    pago_sem_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    inc_sem_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))


class PreciosProductos(Base):
    __tablename__ = 'precios_productos'

    id_precio: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_producto: Mapped[str] = mapped_column(VARCHAR(60), nullable=False)
    tipo_costo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    costo_sin_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    utilidad_deseada: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    utilidad_minima: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    precio_contado: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    plazo: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    porcentaje_interes: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    enganche: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_credito: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    pago_semanal: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    incremento_semanal: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))


class Productos(Base):
    __tablename__ = 'productos'
    __table_args__ = (
        Index('codigo_prod', 'codigo_producto'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_p: Mapped[Optional[int]] = mapped_column(Integer)
    codigo_producto: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    sku_proveedor: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    sku_fabricante: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    codigo_barras: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    descripcion: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    link: Mapped[Optional[str]] = mapped_column(TEXT)
    garantia: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    categoria: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    marca: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cantidadxcomp: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    unidad_medida: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tipo_producto: Mapped[Optional[int]] = mapped_column(Integer)
    imagen: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    ficha_tecnica: Mapped[Optional[str]] = mapped_column(TEXT)


class ProductosKit(Base):
    __tablename__ = 'productos_kit'

    id_kit: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    sku_componente: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    codigo_barras_componente: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    cantidad_producto: Mapped[Optional[int]] = mapped_column(Integer)


class ProductosKits(Base):
    __tablename__ = 'productos_kits'
    __table_args__ = (
        Index('serie_kit', 'noserie_kit', mysql_length={'noserie_kit': 30}),
    )

    id_kit: Mapped[int] = mapped_column(Integer, primary_key=True)
    noserie_kit: Mapped[Optional[str]] = mapped_column(TEXT)
    noserie_producto: Mapped[Optional[str]] = mapped_column(TEXT)
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)


class Proveedor(Base):
    __tablename__ = 'proveedor'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_suc_prov: Mapped[int] = mapped_column(Integer, nullable=False)
    telefono_2: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    telefono_3: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    id_emp_prov: Mapped[Optional[int]] = mapped_column(Integer)
    nombre_comercial: Mapped[Optional[str]] = mapped_column(TEXT)
    razon_social: Mapped[Optional[str]] = mapped_column(TEXT)
    giro_comercial: Mapped[Optional[str]] = mapped_column(TEXT)
    rfc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    calle: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    codigo_postal: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    colonia: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    municipio: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    telefono: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    pagina_web: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    observaciones: Mapped[Optional[str]] = mapped_column(VARCHAR(100))


class Puestos(Base):
    __tablename__ = 'puestos'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_puesto: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    puesto: Mapped[str] = mapped_column(TEXT, nullable=False)
    departamento: Mapped[Optional[str]] = mapped_column(TEXT)
    jefe_directo: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    tipo_e: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    sueldo: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    porcentaje: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    texto_porcentaje: Mapped[Optional[str]] = mapped_column(TEXT)


class ReferenciasPersonales(Base):
    __tablename__ = 'referencias_personales'

    id_ref: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_ref: Mapped[int] = mapped_column(Integer, nullable=False)
    identificador: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    nombre: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_p: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_m: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    parentesco: Mapped[Optional[str]] = mapped_column(VARCHAR(15))
    calle: Mapped[Optional[str]] = mapped_column(TEXT)
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cp: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    colonia: Mapped[Optional[str]] = mapped_column(TEXT)
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    poblacion: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    telefono: Mapped[Optional[str]] = mapped_column(VARCHAR(25))


class Remisiones(Base):
    __tablename__ = 'remisiones'

    id_rem: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_movimiento: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    sku: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    descripcion: Mapped[str] = mapped_column(TEXT, nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    almacen: Mapped[int] = mapped_column(Integer, nullable=False)
    moneda: Mapped[str] = mapped_column(VARCHAR(10), nullable=False)
    remision: Mapped[str] = mapped_column(TEXT, nullable=False)
    almacen_recepcion: Mapped[str] = mapped_column(TEXT, nullable=False)
    id_emp_rem: Mapped[Optional[int]] = mapped_column(Integer)
    estatus: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    entregado: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))


class ResumenArrendamientos(Base):
    __tablename__ = 'resumen_arrendamientos'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_resumen: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_venta: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    id_movimiento: Mapped[str] = mapped_column(VARCHAR(40), nullable=False)
    cuenta: Mapped[str] = mapped_column(TEXT, nullable=False)
    cod_cliente: Mapped[str] = mapped_column(VARCHAR(40), nullable=False)
    sku: Mapped[str] = mapped_column(TEXT, nullable=False)
    descripcion: Mapped[str] = mapped_column(TEXT, nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    garantia: Mapped[int] = mapped_column(Integer, nullable=False)
    series: Mapped[str] = mapped_column(TEXT, nullable=False)
    renta: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    semanas: Mapped[int] = mapped_column(Integer, nullable=False)


class ResumenRentasArrendamientos(Base):
    __tablename__ = 'resumen_rentas_arrendamientos'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_movimiento: Mapped[str] = mapped_column(TEXT, nullable=False)
    no_cuenta: Mapped[str] = mapped_column(VARCHAR(40), nullable=False)
    semanas: Mapped[int] = mapped_column(Integer, nullable=False)
    pago_minimo: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)


class Saldos(Base):
    __tablename__ = 'saldos'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_s: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_s: Mapped[Optional[int]] = mapped_column(Integer)
    cod_cli: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    cuenta: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    item: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    pago_min: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    liquida: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    saldo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    vencido: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    atrasos: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    moratorios: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    estatus: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class SolicitudesCambio(Base):
    __tablename__ = 'solicitudes_cambio'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    razon: Mapped[str] = mapped_column(TEXT, nullable=False)
    modulo: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    urgencia: Mapped[SolicitudesCambioUrgencia] = mapped_column(Enum(SolicitudesCambioUrgencia, values_callable=lambda cls: [member.value for member in cls]), nullable=False)
    descripcion: Mapped[str] = mapped_column(TEXT, nullable=False)
    fecha: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    estado: Mapped[int] = mapped_column(TINYINT(1), nullable=False, server_default=text("'0'"))
    submodulo: Mapped[Optional[str]] = mapped_column(VARCHAR(100))


class SolicitudesProductos(Base):
    __tablename__ = 'solicitudes_productos'

    id_solicitud: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_mov_solicitud: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    codigo: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    descripcion: Mapped[str] = mapped_column(TEXT, nullable=False)
    costo: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    link: Mapped[str] = mapped_column(TEXT, nullable=False)
    imagen: Mapped[str] = mapped_column(TEXT, nullable=False)
    ruta: Mapped[str] = mapped_column(TEXT, nullable=False)
    ficha_tecnica: Mapped[str] = mapped_column(TEXT, nullable=False)
    detalles: Mapped[str] = mapped_column(TEXT, nullable=False)
    usuario: Mapped[str] = mapped_column(TEXT, nullable=False)


class SoporteTecnico(Base):
    __tablename__ = 'soporte_tecnico'

    id_soporte: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_soporte: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento_soporte: Mapped[Optional[str]] = mapped_column(VARCHAR(15))
    tipo_servicio: Mapped[Optional[int]] = mapped_column(Integer)
    tipo_contribuyente: Mapped[Optional[int]] = mapped_column(Integer)
    cod_cliente: Mapped[Optional[str]] = mapped_column(VARCHAR(15))
    nombre: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    apellido_p: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    apellido_m: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    nombre_comercial: Mapped[Optional[str]] = mapped_column(TEXT)
    rfc: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_completo: Mapped[Optional[str]] = mapped_column(TEXT)
    email: Mapped[Optional[str]] = mapped_column(TEXT)
    tel_1: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    tel_2: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    tel_3: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    equipo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tipo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    marca: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    modelo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    color: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    no_serie: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    servicios: Mapped[Optional[str]] = mapped_column(TEXT)
    desc_falla: Mapped[Optional[str]] = mapped_column(TEXT)
    estatus_encendido: Mapped[Optional[str]] = mapped_column(VARCHAR(5))
    condiciones: Mapped[Optional[str]] = mapped_column(TEXT)
    componentes: Mapped[Optional[str]] = mapped_column(TEXT)
    estatus_terminacion: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    fecha_solicitud: Mapped[Optional[datetime.date]] = mapped_column(Date)
    fecha_terminacion: Mapped[Optional[datetime.date]] = mapped_column(Date)
    tecnico: Mapped[Optional[str]] = mapped_column(TEXT)


class SubAlmacen(Base):
    __tablename__ = 'sub_almacen'

    id_sub_almacen: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub_almacen: Mapped[str] = mapped_column(Text, nullable=False)
    prefijo: Mapped[Optional[str]] = mapped_column(String(10))


class SubAlmacenXAlmacen(Base):
    __tablename__ = 'sub_almacen_x_almacen'

    id_sub_almacen: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_sb: Mapped[int] = mapped_column(Integer, nullable=False)
    identificador: Mapped[str] = mapped_column(Text, nullable=False)
    sub_almacen: Mapped[str] = mapped_column(Text, nullable=False)


class SubMenu(Base):
    __tablename__ = 'sub_menu'

    id_sub_menu: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub_menu: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    id_menu: Mapped[Optional[int]] = mapped_column(Integer)


class SucursalFija(Base):
    __tablename__ = 'sucursal_fija'

    id_suc_f: Mapped[str] = mapped_column(TEXT, primary_key=True)
    id_emp_sf: Mapped[int] = mapped_column(Integer, nullable=False)
    id_matriz_sf: Mapped[int] = mapped_column(Integer, nullable=False)
    sucursal: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    calle: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    no_int: Mapped[str] = mapped_column(VARCHAR(11), nullable=False)
    no_ext: Mapped[str] = mapped_column(VARCHAR(11), nullable=False)
    cp: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    colonia: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    estado: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    municipio: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tel1: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tel2: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    tel3: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    observaciones: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    tipo_suc_f: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    titular: Mapped[Optional[str]] = mapped_column(TEXT)


class SucursalMovil(Base):
    __tablename__ = 'sucursal_movil'

    id_suc_m: Mapped[int] = mapped_column(Integer, primary_key=True)
    estatus: Mapped[int] = mapped_column(Integer, nullable=False)
    id_emp_sm: Mapped[Optional[int]] = mapped_column(Integer)
    id_matriz_sm: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tipo_suc_m: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    sucursal: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    marca: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tipo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    ano: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    color: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    matricula: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    niv: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    ubicacion: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    titular: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    observaciones: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class TicketsSoporteWeb(Base):
    __tablename__ = 'tickets_soporte_web'

    id_ticket: Mapped[int] = mapped_column(Integer, primary_key=True)
    reg_ticket: Mapped[int] = mapped_column(Integer, nullable=False)
    usuario: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    cod_colab: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    modulo: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    descripcion: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    fecha_abierto: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    adjuntos: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    responsable: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    prioridad: Mapped[Optional[int]] = mapped_column(Integer)
    estado: Mapped[Optional[int]] = mapped_column(Integer)
    fecha_cerrado: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    usuario_confirmacion: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class TiposCambio(Base):
    __tablename__ = 'tipos_cambio'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hora: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    tipo_cambio: Mapped[decimal.Decimal] = mapped_column(Double(asdecimal=True), nullable=False)
    moneda: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)


class Transacciones(Base):
    __tablename__ = 'transacciones'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp: Mapped[int] = mapped_column(Integer, nullable=False)
    folio_comprobante: Mapped[Optional[str]] = mapped_column(String(50))
    comentario: Mapped[Optional[str]] = mapped_column(String(250))
    cuenta_destino: Mapped[Optional[str]] = mapped_column(String(50))
    fecha: Mapped[Optional[datetime.date]] = mapped_column(Date)
    concepto: Mapped[Optional[str]] = mapped_column(String(255))
    banco: Mapped[Optional[str]] = mapped_column(String(50))
    tarjeta_debito: Mapped[Optional[str]] = mapped_column(String(50))
    importe: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 2))
    validado: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    documentacion: Mapped[Optional[str]] = mapped_column(String(255))
    numero_cuenta_cliente: Mapped[Optional[str]] = mapped_column(String(255))
    hora: Mapped[Optional[datetime.time]] = mapped_column(Time)
    hora_resivo: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    conciliado: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    operacion: Mapped[Optional[str]] = mapped_column(String(50))
    identificador: Mapped[Optional[str]] = mapped_column(String(30))


class UsuariosMaster(Base):
    __tablename__ = 'usuarios_master'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_p: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    apellido_m: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_completo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    correo: Mapped[Optional[str]] = mapped_column(TEXT)
    nombre_usuario: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    password: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    activos: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tipo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    last_login: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    image: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class UsuariosXEmpresa(Base):
    __tablename__ = 'usuarios_x_empresa'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre_empresa: Mapped[Optional[str]] = mapped_column(TEXT)
    cod_usu_m: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_completo: Mapped[Optional[str]] = mapped_column(TEXT)


class VerificacionCuenta(Base):
    __tablename__ = 'verificacion_cuenta'
    __table_args__ = (
        Index('idx_verificacion_no_cuenta', 'no_cuenta'),
        Index('uq_verificacion_no_cuenta', 'no_cuenta', unique=True)
    )

    id_verificacion: Mapped[int] = mapped_column(INTEGER, primary_key=True)
    no_cuenta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    json: Mapped[Optional[str]] = mapped_column(LONGTEXT)


class VentasDocumentos(Base):
    __tablename__ = 'ventas_documentos'
    __table_args__ = (
        ForeignKeyConstraint(['id_venta_b'], ['bitacora_ventas.id_venta_b'], ondelete='CASCADE', name='fk_venta_documento'),
        Index('fk_venta_documento', 'id_venta_b')
    )

    id_documento: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_venta_b: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_archivo: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_subida: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))

    bitacora_ventas: Mapped['BitacoraVentas'] = relationship('BitacoraVentas', back_populates='ventas_documentos')
