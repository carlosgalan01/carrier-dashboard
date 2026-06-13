from sqlalchemy import Column, String, Float, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class CallRecord(Base):
    __tablename__ = "call_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Call metadata
    duration = Column(Integer, nullable=True)  # seconds
    status = Column(String, nullable=True)
    call_end_event = Column(String, nullable=True)
    call_end_initiator = Column(String, nullable=True)
    num_tool_calls = Column(Integer, nullable=True)
    num_user_turns = Column(Integer, nullable=True)
    num_total_turns = Column(Integer, nullable=True)
    p70_latency_ms = Column(Float, nullable=True)
    p90_latency_ms = Column(Float, nullable=True)
    transcript = Column(Text, nullable=True)

    # Offer data
    mc_number = Column(String, nullable=True)
    carrier_name = Column(String, nullable=True)
    load_id = Column(String, nullable=True)
    origin = Column(String, nullable=True)
    destination = Column(String, nullable=True)
    loadboard_rate = Column(String, nullable=True)
    initial_rate_offered = Column(String, nullable=True)
    carrier_counter_offer = Column(String, nullable=True)
    final_agreed_rate = Column(String, nullable=True)
    equipment_type = Column(String, nullable=True)
    negotiation_rounds = Column(Integer, nullable=True)

    # Outcome
    call_outcome = Column(String, nullable=True)
    outcome_notes = Column(Text, nullable=True)

    # Sentiment
    carrier_sentiment = Column(String, nullable=True)
    sentiment_notes = Column(Text, nullable=True)
