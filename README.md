# Carrier Sales Dashboard

Dockerized FastAPI service for a HappyRobot inbound carrier sales workflow.

The service exposes:

- A live dashboard at `/`
- A webhook for completed HappyRobot calls
- Read-only load lookup endpoints backed by a customer PostgreSQL database
- Metrics endpoints used by the dashboard
- Server-Sent Events for live dashboard refreshes

## Architecture

```text
HappyRobot workflow
  -> FastAPI service
      -> customer loads Postgres via LOADS_DATABASE_URL
      -> dashboard/call metrics DB via DATABASE_URL
  -> browser dashboard
```

HappyRobot never connects directly to PostgreSQL. It calls this API over HTTPS with an API key. The API owns database access and exposes only the read-only load data required by the agent.

## Runtime Configuration

Configure these environment variables in Render, Azure Container Apps, or any other container host:

```text
API_KEY=your-secret-api-key
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=your-dashboard-password
DATABASE_URL=sqlite:///./data/calls.db
LOADS_DATABASE_URL=postgresql://user:password@host:5432/dbname
PORT=8000
```

`API_KEY` is required. HappyRobot and scripts use it as:

```text
x-api-key: your-secret-api-key
```

`DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` protect the dashboard login page. If `DASHBOARD_PASSWORD` is not set, it defaults to `API_KEY`.

`DATABASE_URL` stores dashboard/call records. For the PoC this can be SQLite. In production it can point to Postgres.

`LOADS_DATABASE_URL` points to the customer's PostgreSQL database containing the `loads` table. The application treats this database as read-only for normal agent workflows.

`PORT` is usually injected by the hosting provider. Render provides it automatically.

## Expected Loads Schema

The customer database must expose a `loads` table with this shape:

```sql
CREATE TABLE loads (
    load_id             VARCHAR PRIMARY KEY,
    origin              VARCHAR NOT NULL,
    destination         VARCHAR NOT NULL,
    pickup_datetime     TIMESTAMP NOT NULL,
    delivery_datetime   TIMESTAMP NOT NULL,
    equipment_type      VARCHAR NOT NULL,
    loadboard_rate      NUMERIC NOT NULL,
    notes               TEXT,
    weight              INT NOT NULL,
    commodity_type      VARCHAR NOT NULL,
    num_of_pieces       INT,
    miles               INT NOT NULL,
    dimensions          VARCHAR
);
```

For real customer deployments, use a read-only database user for `LOADS_DATABASE_URL`. If the customer's internal schema differs, expose a database view named `loads` with the schema above.

## API Endpoints

Public:

```text
GET /
GET /health
```

Protected with `x-api-key`:

```text
POST /webhook/call-completed
GET  /api/calls
GET  /api/stats
GET  /events?api_key=...
GET  /api/loads/search
GET  /api/loads/{load_id}
POST /admin/seed-loads
```

`/admin/seed-loads` is a temporary PoC helper. It creates and seeds the demo `loads` table in the database configured by `LOADS_DATABASE_URL`.

## HappyRobot Tools

### Search Loads

```text
Method: GET
URL: https://<service-url>/api/loads/search
Headers:
  x-api-key: <API_KEY>
Query params:
  origin
  destination
  equipment_type
  limit
```

Example:

```text
/api/loads/search?origin=Dallas&destination=Atlanta&equipment_type=dry_van
```

### Get Load Details

```text
Method: GET
URL: https://<service-url>/api/loads/{load_id}
Headers:
  x-api-key: <API_KEY>
```

### Send Completed Call Data

```text
Method: POST
URL: https://<service-url>/webhook/call-completed
Headers:
  x-api-key: <API_KEY>
  content-type: application/json
```

Example body:

```json
{
  "run_id": "run-123",
  "call_metadata": {
    "duration": "180",
    "status": "completed",
    "num_tool_calls": "4",
    "num_user_turns": "6",
    "num_total_turns": "14",
    "p70_latency_ms": "650",
    "p90_latency_ms": "900",
    "transcript": "Carrier asked about a Dallas to Atlanta dry van load."
  },
  "offer_data": {
    "mc_number": "123456",
    "carrier_name": "Demo Carrier",
    "load_id": "LOAD-001",
    "origin": "Dallas, TX",
    "destination": "Atlanta, GA",
    "loadboard_rate": "2850",
    "initial_rate_offered": "2600",
    "carrier_counter_offer": "3000",
    "final_agreed_rate": "2750",
    "equipment_type": "dry_van",
    "negotiation_rounds": "2"
  },
  "call_outcome": {
    "outcome": "load_accepted",
    "notes": "Carrier accepted the load."
  },
  "carrier_sentiment": {
    "sentiment": "positive",
    "notes": "Carrier was cooperative."
  }
}
```

## Local Development

Create `.env` from `.env.example`:

```powershell
Copy-Item .env.example .env
```

Run with Docker Compose:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

## Render Deployment

Create a Render Web Service from this repository.

Recommended settings:

```text
Environment: Docker
Docker Build Context Directory: .
Dockerfile Path: ./Dockerfile
Health Check Path: /health
Docker Command: leave empty
```

Environment variables:

```text
API_KEY=<long-random-secret>
LOADS_DATABASE_URL=<internal Render Postgres URL for demo loads>
DATABASE_URL=sqlite:///./data/calls.db
```

Render provides HTTPS and injects `PORT` automatically.

To seed demo loads after deploy:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "https://<service-url>/admin/seed-loads" `
  -Headers @{ "x-api-key" = "<API_KEY>" }
```

Expected response:

```json
{
  "status": "ok",
  "loads_count": 15
}
```

## Security Notes

- All deployed traffic should use HTTPS. Render provides HTTPS by default.
- API endpoints require `x-api-key`.
- The dashboard route requires sign-in at `/login` and then uses same-origin HttpOnly cookies for dashboard API reads.
- Secrets are injected through environment variables, not committed to Git.
- The customer loads database should be accessed with a read-only user.

## Portability

The same Docker image can run in Render, Azure Container Apps, AWS ECS, Google Cloud Run, or a customer-owned environment. To point the container at a customer database, change only environment variables, primarily:

```text
LOADS_DATABASE_URL
```

No code changes are required as long as the customer exposes the expected `loads` table schema.
