from typing import Optional
import datetime
import decimal
import enum
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON

from sqlalchemy import (
    Column,
    DECIMAL,
    Date,
    DateTime,
    Double,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    TIMESTAMP,
    Table,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.mysql import (
    ENUM,
    FLOAT,
    INTEGER,
    LONGTEXT,
    MEDIUMTEXT,
    TEXT,
    TINYINT,
    TINYTEXT,
    VARCHAR,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class SolicitudesCambioUrgencia(str, enum.Enum):
    MUY_URGENTE = "Muy Urgente"
    URGENTE = "Urgente"
    MODERADA = "Moderada"
    NO_URGENTE = "No Urgente"
    POCO_URGENTE = "Poco Urgente"

class AdjuntosColaboradores(Base):
    __tablename__ = "adjuntos_colaboradores"

    id_adj_col: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_ac: Mapped[int] = mapped_column(Integer, nullable=False)
    identificador: Mapped[Optional[str]] = mapped_column(TEXT)
    nombre_archivo: Mapped[Optional[str]] = mapped_column(TEXT)
    archivo: Mapped[Optional[str]] = mapped_column(TEXT)

t_adjuntos_comprobante_salida = Table(
    "adjuntos_comprobante_salida",
    Base.metadata,
    Column("id_comp", Integer, nullable=False),
    Column("id_emp_comp_s", Integer),
    Column("no_serie", VARCHAR(50)),
    Column("comprobante", TEXT),
    Column("fecha", Date),
)

class AdjuntosSucursalMovil(Base):
    __tablename__ = "adjuntos_sucursal_movil"

    id_adjunt_vh: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_adv: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre_vehiculo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    nombre_archivo: Mapped[Optional[str]] = mapped_column(TEXT)
    archivo: Mapped[Optional[str]] = mapped_column(TEXT)

class Inconsistencias(Base):
    __tablename__ = "inconsistencias"
    __table_args__ = (
        Index("idx_folio", "folio"),
        Index("idx_phone", "phone"),
        Index("idx_estatus", "estatus"),
        Index("idx_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    phone: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    folio: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)

    estatus: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default=text("'ABIERTA'"))

    extra_json: Mapped[dict] = mapped_column(MYSQL_JSON, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )

class BitacoraInventario(Base):
    __tablename__ = "bitacora_inventario"

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
    __tablename__ = "bitacora_ventas"

    id_venta_b: Mapped[int] = mapped_column(Integer, primary_key=True)
    devolucion: Mapped[int] = mapped_column(
        TINYINT(1), nullable=False, server_default=text("'0'")
    )
    serie: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    id_emp_bv: Mapped[Optional[int]] = mapped_column(Integer)
    id_suc_bv: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento_bv: Mapped[Optional[str]] = mapped_column(VARCHAR(11))
    id_anticipo_bv: Mapped[Optional[str]] = mapped_column(
        VARCHAR(45), server_default=text("'0'")
    )
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
    precio_unitario_s_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(13, 2)
    )
    total_s_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    total_c_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    importe: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    pago: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    cambio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    metodo_pago: Mapped[Optional[str]] = mapped_column(TEXT)
    p_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(10, 0), server_default=text("'0'")
    )
    t_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(10, 0), server_default=text("'0'")
    )
    apartado: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    contado: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    credito: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    liquidacion: Mapped[Optional[int]] = mapped_column(
        Integer, server_default=text("'0'")
    )
    cancelacion: Mapped[Optional[int]] = mapped_column(
        Integer, server_default=text("'0'")
    )
    fecha_venta: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    usuario: Mapped[Optional[str]] = mapped_column(TEXT)
    corte: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("'0'"))
    fecha_corte: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP)
    folio: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    subsidio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))

    ventas_documentos: Mapped[list["VentasDocumentos"]] = relationship(
        "VentasDocumentos", back_populates="bitacora_ventas"
    )

class Cancelaciones(Base):
    __tablename__ = "cancelaciones"

    id_cancelacion: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_mov_cancelacion: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    tiene_ns: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    no_serie_cancelado: Mapped[Optional[str]] = mapped_column(TEXT)
    sku: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    descripcion: Mapped[Optional[str]] = mapped_column(TEXT)
    motivo_cancelacion: Mapped[Optional[int]] = mapped_column(Integer)

class CarteraCuentasTemp(Base):
    __tablename__ = "cartera_cuentas_temp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp: Mapped[int] = mapped_column(Integer, nullable=False)
    agente_verificador: Mapped[str] = mapped_column(Text, nullable=False)
    atrasos: Mapped[decimal.Decimal] = mapped_column(DECIMAL(13, 2), nullable=False)
    cod_cli: Mapped[str] = mapped_column(String(45), nullable=False)
    cuenta: Mapped[str] = mapped_column(String(200), nullable=False)
    importe_renta: Mapped[decimal.Decimal] = mapped_column(
        DECIMAL(13, 2), nullable=False
    )
    nombre_completo: Mapped[str] = mapped_column(Text, nullable=False)
    total_vencido: Mapped[decimal.Decimal] = mapped_column(
        DECIMAL(13, 2), nullable=False
    )
    fecha_modifica: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    nombre_usuario_modifica: Mapped[Optional[str]] = mapped_column(Text)
    nombre_usuario_gestor: Mapped[Optional[str]] = mapped_column(String(45))
    nombre_resumido: Mapped[Optional[str]] = mapped_column(Text)

class ChatSessions(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("idx_folio", "folio"),
        Index("idx_phone", "phone"),
        Index("uq_chat_phone", "phone", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    state: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    folio: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    previous_state: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    last_message: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    last_message_id: Mapped[Optional[str]] = mapped_column(VARCHAR(100))

class Clientes(Base):
    __tablename__ = "clientes"
    __table_args__ = (Index("id_cliente", "id_cliente"),)

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
    __tablename__ = "clientes_aval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    no_cuenta: Mapped[str] = mapped_column(VARCHAR(11), nullable=False)
    cliente: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    aval: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    referencia_uno: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    referencia_dos: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    referencia_tres: Mapped[Optional[str]] = mapped_column(VARCHAR(255))

class ClientesCreditoDirecto(Base):
    __tablename__ = "clientes_credito_directo"

    id_credito: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_cd: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo_cliente: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    plazo: Mapped[Optional[int]] = mapped_column(Integer)
    maximo: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    moratorio: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    correo: Mapped[Optional[str]] = mapped_column(TEXT)
    autorizo: Mapped[Optional[str]] = mapped_column(TEXT)

class Compra(Base):
    __tablename__ = "compra"

    id_compra: Mapped[int] = mapped_column(Integer, primary_key=True)
    estatus: Mapped[int] = mapped_column(Integer, nullable=False)
    estatus_nc: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
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
    __tablename__ = "compras_comprobantes_fiscales"

    id_comp_fiscal: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_comp_fiscal: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento_comp_fiscal: Mapped[Optional[str]] = mapped_column(VARCHAR(15))
    comprobante_fiscal: Mapped[Optional[str]] = mapped_column(TEXT)
    fecha_registro: Mapped[Optional[datetime.date]] = mapped_column(Date)

class Cuentas(Base):
    __tablename__ = "cuentas"
    __table_args__ = (Index("cuenta", "cuenta"),)

    id_cuenta: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_suc_cuenta: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_act: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    orden_servicio: Mapped[int] = mapped_column(
        TINYINT(1), nullable=False, server_default=text("'0'")
    )
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
    __tablename__ = "cuentas_comprobantes"

    id_comprobante: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_cliente: Mapped[str] = mapped_column(VARCHAR(45), nullable=False)
    comprobante: Mapped[str] = mapped_column(TEXT, nullable=False)
    fecha_registro: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    id_emp_comprobante: Mapped[int] = mapped_column(Integer, nullable=False)

class DomiciliosHorariosEntrega(Base):
    __tablename__ = "domicilios_horarios_entrega"

    id_d_h: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_d_h: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    suc_entrega: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    tipo_de_vialidad: Mapped[Optional[str]] = mapped_column(
        "tipo de vialidad", VARCHAR(60)
    )
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

class Estado(Base):
    __tablename__ = "estado"

    idestado: Mapped[int] = mapped_column(Integer, primary_key=True)
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(45))


class EstadosCuenta(Base):
    __tablename__ = "estados_cuenta"
    __table_args__ = (Index("cuenta", "cuenta_e"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corte: Mapped[int] = mapped_column(
        TINYINT, nullable=False, server_default=text("'0'")
    )
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
    __tablename__ = "estados_cuenta_duplicate"
    __table_args__ = (Index("cuenta", "cuenta_e"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corte: Mapped[int] = mapped_column(
        TINYINT, nullable=False, server_default=text("'0'")
    )
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

class MotivosCancelacion(Base):
    __tablename__ = "motivos_cancelacion"

    id_motivo: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_motivo: Mapped[Optional[int]] = mapped_column(Integer)
    motivo: Mapped[Optional[str]] = mapped_column(TEXT)


class PlanesPago(Base):
    __tablename__ = "planes_pago"
    __table_args__ = (Index("fecha_inicio", "fecha_inicio", unique=True),)

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

class PreciosProductoUnidad(Base):
    __tablename__ = "precios_producto_unidad"

    id_prd_unidad: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_producto: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    tipo_costo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    costo_sin_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    utilidad_deseada: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    utilidad_minima: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    precio_contado_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(13, 2)
    )
    plazo_x_unidad: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    porcentaje_interes_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(13, 2)
    )
    enganche_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_credito_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(13, 2)
    )
    pago_sem_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    inc_sem_x_unidad: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))

class PreciosProductos(Base):
    __tablename__ = "precios_productos"

    id_precio: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo_producto: Mapped[str] = mapped_column(VARCHAR(60), nullable=False)
    tipo_costo: Mapped[Optional[str]] = mapped_column(VARCHAR(45))
    costo_sin_iva: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    utilidad_deseada: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    utilidad_minima: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 3))
    precio_contado: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    plazo: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    porcentaje_interes: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(13, 2)
    )
    enganche: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    precio_credito: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    pago_semanal: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(13, 2))
    incremento_semanal: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(13, 2)
    )

class Productos(Base):
    __tablename__ = "productos"
    __table_args__ = (Index("codigo_prod", "codigo_producto"),)

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

class ReferenciasPersonales(Base):
    __tablename__ = "referencias_personales"

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

class ResumenArrendamientos(Base):
    __tablename__ = "resumen_arrendamientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_resumen: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_venta: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
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

class Saldos(Base):
    __tablename__ = "saldos"

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

class Transacciones(Base):
    __tablename__ = "transacciones"

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

class VerificacionCuenta(Base):
    __tablename__ = "verificacion_cuenta"
    __table_args__ = (
        Index("idx_verificacion_no_cuenta", "no_cuenta"),
        Index("uq_verificacion_no_cuenta", "no_cuenta", unique=True),
    )

    id_verificacion: Mapped[int] = mapped_column(INTEGER, primary_key=True)
    no_cuenta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    json: Mapped[Optional[str]] = mapped_column(LONGTEXT)

class VentasDocumentos(Base):
    __tablename__ = "ventas_documentos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id_venta_b"],
            ["bitacora_ventas.id_venta_b"],
            ondelete="CASCADE",
            name="fk_venta_documento",
        ),
        Index("fk_venta_documento", "id_venta_b"),
    )

    id_documento: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_venta_b: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_archivo: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_subida: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    bitacora_ventas: Mapped["BitacoraVentas"] = relationship(
        "BitacoraVentas", back_populates="ventas_documentos"
    )