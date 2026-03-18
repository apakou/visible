from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Owner(Base):
    __tablename__ = "owners"
    id = Column(Integer, primary_key=True)
    phone_number = Column(Text, unique=True, nullable=False)
    name = Column(Text)
    shop_name = Column(Text)
    location = Column(Text)
    language_pref = Column(Text, default="en")
    onboarded_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    inventory_logs = relationship("InventoryLog", back_populates="owner")
    policies = relationship("Policy", back_populates="owner")


class InventoryLog(Base):
    __tablename__ = "inventory_log"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    entry_type = Column(Text, nullable=False)
    product_name = Column(Text)
    product_category = Column(Text)
    quantity = Column(Integer)
    unit_cost_pesewas = Column(Integer)
    unit_price_pesewas = Column(Integer)
    stock_value_pesewas = Column(Integer)
    raw_message = Column(Text)
    parse_confidence = Column(Float)
    logged_at = Column(DateTime, default=func.now())
    owner = relationship("Owner", back_populates="inventory_logs")


class InventoryDeclaration(Base):
    __tablename__ = "inventory_declarations"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    declaration_month = Column(Date, nullable=False)
    total_stock_value_ghs = Column(Numeric(12, 2))
    item_breakdown_json = Column(Text)
    days_logged = Column(Integer)
    consistency_score = Column(Float)
    declaration_text_en = Column(Text)
    declaration_text_tw = Column(Text)
    submitted_to_insurer = Column(Boolean, default=False)
    submitted_at = Column(DateTime)
    generated_at = Column(DateTime, default=func.now())


class SusuGroup(Base):
    __tablename__ = "susu_groups"
    id = Column(Integer, primary_key=True)
    group_name = Column(Text, nullable=False)
    leader_phone = Column(Text, ForeignKey("owners.phone_number"), nullable=False)
    market_location = Column(Text)
    member_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    members = relationship("SusuMember", back_populates="group")


class SusuMember(Base):
    __tablename__ = "susu_members"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("susu_groups.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    joined_at = Column(DateTime, default=func.now())
    status = Column(Text, default="active")
    group = relationship("SusuGroup", back_populates="members")


class Policy(Base):
    __tablename__ = "policies"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    susu_group_id = Column(Integer, ForeignKey("susu_groups.id"))
    policy_number = Column(Text, unique=True, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    premium_pesewas = Column(Integer, nullable=False)
    payout_cap_pesewas = Column(Integer, nullable=False)
    cover_start_date = Column(Date)
    cover_end_date = Column(Date)
    insurer_partner = Column(Text)
    last_premium_paid_at = Column(DateTime)
    declarations_submitted = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    owner = relationship("Owner", back_populates="policies")
    claims = relationship("Claim", back_populates="policy")


class Claim(Base):
    __tablename__ = "claims"
    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    claim_reference = Column(Text, unique=True, nullable=False)
    event_type = Column(Text, nullable=False)
    event_date = Column(Date, nullable=False)
    declared_loss_pesewas = Column(Integer)
    verified_loss_pesewas = Column(Integer)
    payout_pesewas = Column(Integer)
    status = Column(Text, default="initiated")
    supporting_declaration_id = Column(Integer, ForeignKey("inventory_declarations.id"))
    initiated_at = Column(DateTime, default=func.now())
    resolved_at = Column(DateTime)
    notes = Column(Text)
    policy = relationship("Policy", back_populates="claims")


class FinancialProfile(Base):
    __tablename__ = "financial_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    total_revenue_pesewas = Column(Integer)
    total_expenses_pesewas = Column(Integer)
    gross_profit_pesewas = Column(Integer)
    transaction_count = Column(Integer)
    days_logged = Column(Integer)
    consistency_score = Column(Float)
    credit_readiness_score = Column(Float)
    summary_text_en = Column(Text)
    summary_text_tw = Column(Text)
    lender_profile_json = Column(Text)
    generated_at = Column(TIMESTAMP, default=func.now())
