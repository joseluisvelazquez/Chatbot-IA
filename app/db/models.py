from typing import Optional
import datetime
import decimal
import enum

from sqlalchemy import Column, DECIMAL, Date, DateTime, Double, Enum, ForeignKeyConstraint, Index, Integer, String, TIMESTAMP, Table, Text, Time, text
from sqlalchemy.dialects.mysql import ENUM, FLOAT, INTEGER, LONGTEXT, TEXT, TINYINT, TINYTEXT, VARCHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

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

class DomiciliosHorariosEntrega(Base):
    __tablename__ = 'domicilios_horarios_entrega'

    id_d_h: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_emp_d_h: Mapped[Optional[int]] = mapped_column(Integer)
    id_movimiento: Mapped[Optional[str]] = mapped_column(TEXT)
    suc_entrega: Mapped[Optional[str]] = mapped_column(TEXT)
    tipo_de_vialidad: Mapped[Optional[str]] = mapped_column('tipo de vialidad', VARCHAR(60))
    nombre_vialidad: Mapped[Optional[str]] = mapped_column(TEXT)
    no_ext: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    no_int: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    colonia: Mapped[Optional[str]] = mapped_column(TEXT)
    codigo_postal: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    ciudad: Mapped[Optional[str]] = mapped_column(TEXT)
    estado: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    referencias: Mapped[Optional[str]] = mapped_column(TEXT)
    lat_ubicacion: Mapped[Optional[str]] = mapped_column(TEXT)
    lon_ubicacion: Mapped[Optional[str]] = mapped_column(TEXT)
    nombre_q_recibe: Mapped[Optional[str]] = mapped_column(TEXT)
    tel_entrega: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    tipo_tel_entrega: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    dia_semana: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    hora_inicio: Mapped[Optional[str]] = mapped_column(VARCHAR(40))
    hora_final: Mapped[Optional[str]] = mapped_column(VARCHAR(40))
