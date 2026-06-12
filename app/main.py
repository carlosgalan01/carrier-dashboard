import os
import json
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from pathlib import Path

from app.database import init_db, get_db
from app.models import CallRecord

load_dotenv()

app = FastAPI(
    title="Carrier Sales Dashboard API",
    description="API for receiving and serving carrier call data from HappyRobot",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY", "dev-key-change-me")
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

def verify_api_key(request: Request):
    key = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def dashboard():
    return FileResponse(TEMPLATES_DIR / "index.html")

# Webhook endpoint: receives data from HappyRobot.

@app.post("/webhook/call-completed")
async def receive_call_data(request: Request, db: Session = Depends(get_db)):
    """Receive call data from HappyRobot workflow webhook."""
    key = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()

    call_meta = body.get("call_metadata", {})
    offer = body.get("offer_data", {})
    outcome = body.get("call_outcome", {})
    sentiment = body.get("carrier_sentiment", {})

    # Parse negotiation_rounds safely
    neg_rounds = offer.get("negotiation_rounds")
    try:
        neg_rounds = int(neg_rounds) if neg_rounds else None
    except (ValueError, TypeError):
        neg_rounds = None

    record = CallRecord(
        run_id=body.get("run_id", ""),
        duration=_safe_int(call_meta.get("duration")),
        status=call_meta.get("status"),
        call_end_event=call_meta.get("call_end_event"),
        call_end_initiator=call_meta.get("call_end_initiator"),
        num_tool_calls=_safe_int(call_meta.get("num_tool_calls")),
        num_user_turns=_safe_int(call_meta.get("num_user_turns")),
        num_total_turns=_safe_int(call_meta.get("num_total_turns")),
        p70_latency_ms=_safe_float(call_meta.get("p70_latency_ms")),
        p90_latency_ms=_safe_float(call_meta.get("p90_latency_ms")),
        transcript=json.dumps(call_meta.get("transcript", ""), ensure_ascii=False),
        mc_number=offer.get("mc_number"),
        carrier_name=offer.get("carrier_name"),
        load_id=offer.get("load_id"),
        origin=offer.get("origin"),
        destination=offer.get("destination"),
        initial_rate_offered=offer.get("initial_rate_offered"),
        carrier_counter_offer=offer.get("carrier_counter_offer"),
        final_agreed_rate=offer.get("final_agreed_rate"),
        equipment_type=offer.get("equipment_type"),
        negotiation_rounds=neg_rounds,
        call_outcome=outcome.get("outcome"),
        outcome_notes=outcome.get("notes"),
        carrier_sentiment=sentiment.get("sentiment"),
        sentiment_notes=sentiment.get("notes"),
    )

    db.add(record)
    db.commit()
    return {"status": "ok", "run_id": body.get("run_id")}

# API endpoints: serve data to the dashboard.

@app.get("/api/calls")
def get_calls(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key)
):
    """Get all call records, newest first."""
    calls = (
        db.query(CallRecord)
        .order_by(CallRecord.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "count": db.query(CallRecord).count(),
        "calls": [_serialize(c) for c in calls]
    }

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db), _: None = Depends(verify_api_key)):
    """Get aggregate statistics."""
    from sqlalchemy import func

    total = db.query(CallRecord).count()
    if total == 0:
        return {"total_calls": 0, "message": "No calls recorded yet"}

    outcomes = (
        db.query(CallRecord.call_outcome, func.count(CallRecord.id))
        .group_by(CallRecord.call_outcome)
        .all()
    )
    sentiments = (
        db.query(CallRecord.carrier_sentiment, func.count(CallRecord.id))
        .group_by(CallRecord.carrier_sentiment)
        .all()
    )
    avg_duration = db.query(func.avg(CallRecord.duration)).scalar()
    avg_latency = db.query(func.avg(CallRecord.p70_latency_ms)).scalar()
    avg_rounds = db.query(func.avg(CallRecord.negotiation_rounds)).scalar()

    return {
        "total_calls": total,
        "avg_duration_seconds": round(avg_duration or 0, 1),
        "avg_latency_p70_ms": round(avg_latency or 0, 1),
        "avg_negotiation_rounds": round(avg_rounds or 0, 1),
        "outcomes": {o: c for o, c in outcomes if o},
        "sentiments": {s: c for s, c in sentiments if s},
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

# Helpers.

def _safe_int(val):
    try:
        return int(val) if val else None
    except (ValueError, TypeError):
        return None

def _safe_float(val):
    try:
        return float(val) if val else None
    except (ValueError, TypeError):
        return None

def _serialize(record: CallRecord) -> dict:
    return {
        "id": record.id,
        "run_id": record.run_id,
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "duration": record.duration,
        "status": record.status,
        "call_end_event": record.call_end_event,
        "call_end_initiator": record.call_end_initiator,
        "num_tool_calls": record.num_tool_calls,
        "num_user_turns": record.num_user_turns,
        "num_total_turns": record.num_total_turns,
        "p70_latency_ms": record.p70_latency_ms,
        "p90_latency_ms": record.p90_latency_ms,
        "mc_number": record.mc_number,
        "carrier_name": record.carrier_name,
        "load_id": record.load_id,
        "origin": record.origin,
        "destination": record.destination,
        "initial_rate_offered": record.initial_rate_offered,
        "carrier_counter_offer": record.carrier_counter_offer,
        "final_agreed_rate": record.final_agreed_rate,
        "equipment_type": record.equipment_type,
        "negotiation_rounds": record.negotiation_rounds,
        "call_outcome": record.call_outcome,
        "outcome_notes": record.outcome_notes,
        "carrier_sentiment": record.carrier_sentiment,
        "sentiment_notes": record.sentiment_notes,
    }


