"""SQLAlchemy 2.0 declarative models for the Autonomous AI Supply Chain War Room."""

from __future__ import annotations

import datetime
from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


class Supplier(Base):
    """Supplier entity representing parts and component vendors."""

    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    is_key_supplier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    supplier_skus: Mapped[list[SupplierSKU]] = relationship(
        "SupplierSKU", back_populates="supplier", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Supplier(supplier_id={self.supplier_id!r}, name={self.name!r}, "
            f"country={self.country!r}, key={self.is_key_supplier})>"
        )


class SKU(Base):
    """Stock Keeping Unit (SKU) entity for parts, raw materials, and assemblies."""

    __tablename__ = "skus"

    sku_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    supplier_skus: Mapped[list[SupplierSKU]] = relationship(
        "SupplierSKU", back_populates="sku", cascade="all, delete-orphan"
    )
    inventory_items: Mapped[list[Inventory]] = relationship(
        "Inventory", back_populates="sku", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="sku", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<SKU(sku_id={self.sku_id!r}, name={self.name!r}, "
            f"category={self.category!r}, unit_cost={self.unit_cost})>"
        )


class SupplierSKU(Base):
    """Mapping between suppliers and SKUs with cost, lead time, and monthly capacity."""

    __tablename__ = "supplier_skus"

    supplier_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("suppliers.supplier_id", ondelete="CASCADE"), primary_key=True
    )
    sku_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("skus.sku_id", ondelete="CASCADE"), primary_key=True
    )
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="supplier_skus")
    sku: Mapped[SKU] = relationship("SKU", back_populates="supplier_skus")

    def __repr__(self) -> str:
        return (
            f"<SupplierSKU(supplier_id={self.supplier_id!r}, sku_id={self.sku_id!r}, "
            f"is_primary={self.is_primary}, unit_price={self.unit_price})>"
        )


class Warehouse(Base):
    """Warehouse / distribution center entity."""

    __tablename__ = "warehouses"

    warehouse_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    inventory_items: Mapped[list[Inventory]] = relationship(
        "Inventory", back_populates="warehouse", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Warehouse(warehouse_id={self.warehouse_id!r}, name={self.name!r}, "
            f"city={self.city!r}, country={self.country!r})>"
        )


class Inventory(Base):
    """Inventory tracking per warehouse and SKU pair."""

    __tablename__ = "inventory"

    warehouse_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("warehouses.warehouse_id", ondelete="CASCADE"), primary_key=True
    )
    sku_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("skus.sku_id", ondelete="CASCADE"), primary_key=True
    )
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    warehouse: Mapped[Warehouse] = relationship("Warehouse", back_populates="inventory_items")
    sku: Mapped[SKU] = relationship("SKU", back_populates="inventory_items")

    def __repr__(self) -> str:
        return (
            f"<Inventory(warehouse_id={self.warehouse_id!r}, sku_id={self.sku_id!r}, "
            f"on_hand={self.on_hand}, safety_stock={self.safety_stock}, "
            f"reorder_point={self.reorder_point})>"
        )


class Carrier(Base):
    """Logistics carrier entity."""

    __tablename__ = "carriers"

    carrier_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)  # "air", "sea", "road"
    cost_per_kg: Mapped[float] = mapped_column(Float, nullable=False)
    speed_days: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<Carrier(carrier_id={self.carrier_id!r}, name={self.name!r}, "
            f"mode={self.mode!r}, speed_days={self.speed_days})>"
        )


class Customer(Base):
    """Customer entity."""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(50), nullable=False)  # "gold", "silver", "bronze"
    region: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="customer", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Customer(customer_id={self.customer_id!r}, name={self.name!r}, "
            f"tier={self.tier!r}, region={self.region!r})>"
        )


class Order(Base):
    """Customer sales/purchase order entity."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("customers.customer_id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("skus.sku_id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    due_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-3
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)

    # Relationships
    customer: Mapped[Customer] = relationship("Customer", back_populates="orders")
    sku: Mapped[SKU] = relationship("SKU", back_populates="orders")

    def __repr__(self) -> str:
        return (
            f"<Order(order_id={self.order_id!r}, customer_id={self.customer_id!r}, "
            f"sku_id={self.sku_id!r}, quantity={self.quantity}, "
            f"order_date={self.order_date}, due_date={self.due_date}, "
            f"priority={self.priority}, status={self.status!r})>"
        )
