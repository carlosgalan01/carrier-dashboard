import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import CallRecord


load_dotenv()

app = FastAPI(
    title="Carrier Sales Dashboard API",
    description="API for receiving and serving carrier call data from HappyRobot",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY", "dev-key-change-me")
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
event_subscribers: set[asyncio.Queue[str]] = set()
LOADS_SEED_SQL = """
CREATE TABLE IF NOT EXISTS loads (
    load_id VARCHAR PRIMARY KEY,
    origin VARCHAR NOT NULL,
    destination VARCHAR NOT NULL,
    pickup_datetime TIMESTAMP NOT NULL,
    delivery_datetime TIMESTAMP NOT NULL,
    equipment_type VARCHAR NOT NULL,
    loadboard_rate NUMERIC NOT NULL,
    notes TEXT,
    weight INT NOT NULL,
    commodity_type VARCHAR NOT NULL,
    num_of_pieces INT,
    miles INT NOT NULL,
    dimensions VARCHAR
);

INSERT INTO loads (
    load_id, origin, destination, pickup_datetime, delivery_datetime,
    equipment_type, loadboard_rate, notes, weight, commodity_type,
    num_of_pieces, miles, dimensions
) VALUES
('LOAD-001', 'Dallas, TX', 'Atlanta, GA', '2026-06-13 08:00:00', '2026-06-14 16:00:00', 'dry_van', 2850.00, 'No-touch freight. Dock-to-dock.', 42000, 'Consumer Electronics', 24, 781, '48x40x48 pallets'),
('LOAD-002', 'Dallas, TX', 'Memphis, TN', '2026-06-13 06:00:00', '2026-06-13 18:00:00', 'dry_van', 1200.00, 'Same-day delivery preferred.', 38000, 'Paper Products', 30, 452, '48x40x60 pallets'),
('LOAD-003', 'Houston, TX', 'Chicago, IL', '2026-06-14 10:00:00', '2026-06-16 08:00:00', 'reefer', 4200.00, 'Temperature must stay between 34-38F.', 44000, 'Fresh Produce', 18, 1092, '48x40x48 pallets'),
('LOAD-004', 'Houston, TX', 'Miami, FL', '2026-06-13 14:00:00', '2026-06-15 10:00:00', 'reefer', 3600.00, 'Frozen goods. Keep at 0F.', 40000, 'Frozen Seafood', 22, 1187, '48x40x48 pallets'),
('LOAD-005', 'San Antonio, TX', 'Phoenix, AZ', '2026-06-14 07:00:00', '2026-06-15 14:00:00', 'flatbed', 2100.00, 'Oversized. Tarps required.', 48000, 'Steel Beams', 8, 880, '40ft lengths'),
('LOAD-006', 'Fort Worth, TX', 'Nashville, TN', '2026-06-13 09:00:00', '2026-06-14 12:00:00', 'dry_van', 1800.00, 'Appointment required at delivery.', 36000, 'Auto Parts', 40, 660, '48x40x42 pallets'),
('LOAD-007', 'Austin, TX', 'Denver, CO', '2026-06-15 06:00:00', '2026-06-16 18:00:00', 'dry_van', 2400.00, 'Light freight but full trailer.', 22000, 'Furniture', 12, 935, '48x40x72 pallets'),
('LOAD-008', 'El Paso, TX', 'Los Angeles, CA', '2026-06-13 12:00:00', '2026-06-14 20:00:00', 'flatbed', 1950.00, 'Must have chains and straps.', 45000, 'Construction Materials', 6, 800, 'Various oversized'),
('LOAD-009', 'Laredo, TX', 'Dallas, TX', '2026-06-14 05:00:00', '2026-06-14 14:00:00', 'reefer', 1100.00, 'Cross-border freight. Customs cleared.', 35000, 'Fresh Avocados', 28, 438, '48x40x48 pallets'),
('LOAD-010', 'Oklahoma City, OK', 'Houston, TX', '2026-06-13 11:00:00', '2026-06-14 08:00:00', 'dry_van', 1500.00, 'Driver assist unload.', 41000, 'Beverages', 32, 478, '48x40x48 pallets'),
('LOAD-011', 'Little Rock, AR', 'San Antonio, TX', '2026-06-15 08:00:00', '2026-06-16 10:00:00', 'dry_van', 1650.00, 'No hazmat. Straightforward run.', 39000, 'Retail Goods', 26, 588, '48x40x54 pallets'),
('LOAD-012', 'Jackson, MS', 'Fort Worth, TX', '2026-06-14 09:00:00', '2026-06-15 06:00:00', 'flatbed', 1750.00, 'Pipe load. Securement per DOT regs.', 46000, 'PVC Pipe', 1, 562, '20ft bundles'),
('LOAD-013', 'New Orleans, LA', 'Atlanta, GA', '2026-06-13 07:00:00', '2026-06-14 09:00:00', 'reefer', 2200.00, 'Seafood. Temp at 32F.', 38000, 'Fresh Shrimp', 20, 470, '48x40x48 pallets'),
('LOAD-014', 'Tulsa, OK', 'Kansas City, MO', '2026-06-14 06:00:00', '2026-06-14 14:00:00', 'dry_van', 850.00, 'Short haul. Quick turnaround.', 34000, 'Packaged Foods', 36, 248, '48x40x48 pallets'),
('LOAD-015', 'Shreveport, LA', 'Memphis, TN', '2026-06-15 10:00:00', '2026-06-15 20:00:00', 'dry_van', 950.00, 'Drop and hook available.', 40000, 'Plastics', 28, 315, '48x40x48 pallets')
ON CONFLICT (load_id) DO NOTHING;
"""


def verify_api_key(request: Request):
    key = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def broadcast_event(message: str) -> None:
    for subscriber in list(event_subscribers):
        subscriber.put_nowait(message)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def dashboard():
    return FileResponse(TEMPLATES_DIR / "index.html")


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
    broadcast_event("call_created")
    return {"status": "ok", "run_id": body.get("run_id")}


@app.get("/api/calls")
def get_calls(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    """Get all call records, newest first."""
    calls = (
        db.query(CallRecord)
        .order_by(CallRecord.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"count": db.query(CallRecord).count(), "calls": [_serialize(c) for c in calls]}


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


@app.post("/admin/seed-loads")
def seed_loads(_: None = Depends(verify_api_key)):
    loads_database_url = os.getenv("LOADS_DATABASE_URL")
    if not loads_database_url:
        raise HTTPException(status_code=500, detail="LOADS_DATABASE_URL is not configured")

    engine = create_engine(_normalize_database_url(loads_database_url))
    with engine.begin() as connection:
        connection.execute(text(LOADS_SEED_SQL))
        count = connection.execute(text("SELECT COUNT(*) FROM loads")).scalar_one()

    return {"status": "ok", "loads_count": count}


@app.get("/api/loads/search")
def search_loads(
    origin: str | None = None,
    destination: str | None = None,
    equipment_type: str | None = None,
    limit: int = 5,
    _: None = Depends(verify_api_key),
):
    origin = _blank_to_none(origin)
    destination = _blank_to_none(destination)
    equipment_type = _blank_to_none(equipment_type)

    query = """
        SELECT
            load_id, origin, destination, pickup_datetime, delivery_datetime,
            equipment_type, loadboard_rate, notes, weight, commodity_type,
            num_of_pieces, miles, dimensions
        FROM loads
        WHERE (:origin IS NULL OR origin ILIKE :origin_pattern)
          AND (:destination IS NULL OR destination ILIKE :destination_pattern)
          AND (:equipment_type IS NULL OR equipment_type ILIKE :equipment_pattern)
        ORDER BY pickup_datetime ASC
        LIMIT :limit
    """
    params = {
        "origin": origin,
        "origin_pattern": f"%{origin}%" if origin else None,
        "destination": destination,
        "destination_pattern": f"%{destination}%" if destination else None,
        "equipment_type": equipment_type,
        "equipment_pattern": f"%{equipment_type}%" if equipment_type else None,
        "limit": min(max(limit, 1), 25),
    }

    rows = _query_loads_database(query, params)
    return {"count": len(rows), "loads": rows}


@app.get("/events")
async def events(request: Request, _: None = Depends(verify_api_key)):
    queue: asyncio.Queue[str] = asyncio.Queue()
    event_subscribers.add(queue)

    async def stream():
        try:
            yield "event: connected\ndata: ok\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"event: dashboard_update\ndata: {message}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: keepalive\n\n"
        finally:
            event_subscribers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"status": "healthy"}


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


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _loads_engine():
    loads_database_url = os.getenv("LOADS_DATABASE_URL")
    if not loads_database_url:
        raise HTTPException(status_code=500, detail="LOADS_DATABASE_URL is not configured")
    return create_engine(_normalize_database_url(loads_database_url))


def _query_loads_database(query: str, params: dict) -> list[dict]:
    engine = _loads_engine()
    with engine.connect() as connection:
        result = connection.execute(text(query), params)
        return [_serialize_load_row(row._mapping) for row in result]


def _serialize_load_row(row) -> dict:
    return {
        "load_id": row["load_id"],
        "origin": row["origin"],
        "destination": row["destination"],
        "pickup_datetime": row["pickup_datetime"].isoformat() if row["pickup_datetime"] else None,
        "delivery_datetime": row["delivery_datetime"].isoformat() if row["delivery_datetime"] else None,
        "equipment_type": row["equipment_type"],
        "loadboard_rate": float(row["loadboard_rate"]) if row["loadboard_rate"] is not None else None,
        "notes": row["notes"],
        "weight": row["weight"],
        "commodity_type": row["commodity_type"],
        "num_of_pieces": row["num_of_pieces"],
        "miles": row["miles"],
        "dimensions": row["dimensions"],
    }


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
