from sqlalchemy import TIMESTAMP, Column, Date, Float, ForeignKey, Integer, Text, func

from app.database import Base


class Owner(Base):
    __tablename__ = "owners"
    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(Text, unique=True, nullable=False)
    name = Column(Text)
    shop_name = Column(Text)
    shop_category = Column(Text)
    location = Column(Text)
    language_pref = Column(Text, default="en")
    onboarded_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("owners.id"), nullable=False)
    type = Column(Text, nullable=False)
    amount_pesewas = Column(Integer)
    description = Column(Text)
    raw_message = Column(Text)
    category = Column(Text)
    units_sold = Column(Integer)
    logged_at = Column(TIMESTAMP, default=func.now())
    parse_confidence = Column(Float)


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
