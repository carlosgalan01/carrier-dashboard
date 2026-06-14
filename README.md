# SpaceY Agent Dashboard

Dockerized FastAPI service for a HappyRobot inbound carrier sales workflow.

The service exposes:

- A protected dashboard at `/`
- A login page at `/login`
- A webhook for completed HappyRobot calls
- Read-only load search backed by a customer PostgreSQL database
- Metrics endpoints used by the dashboard
- Server-Sent Events for live dashboard refreshes
- Static dashboard assets under `/static`

## Architecture

```text
Carrier phone call
  -> SpaceY Agent workflow in HappyRobot
      -> public FMCSA API for carrier verification
      -> FastAPI Docker container
          -> /api/loads/search reads customer loads from LOADS_DATABASE_URL
          -> /webhook/call-completed writes selected call fields to DATABASE_URL
          -> /api/stats, /api/calls, /events power the browser dashboard
          -> / and /static serve dashboard HTML/CSS/JS/assets
      -> browser dashboard
```

HappyRobot runs the voice workflow, telephony, carrier conversation, carrier verification flow, load search calls, negotiation, and completed-call webhook. The FastAPI container handles load lookup tools, webhook ingestion, selected call storage, analytics APIs, dashboard HTML, and `/static` assets. There is no separate frontend service.

HappyRobot never connects directly to PostgreSQL. It calls this API over HTTPS with an API key. The API owns database access and exposes only the load search and dashboard data required by the workflow.

Carrier verification belongs to the HappyRobot workflow. If the workflow verifies carriers through the public FMCSA API, configure the FMCSA API key on the HappyRobot/workflow side. FMCSA verification is not implemented as a FastAPI route in this repository.

## Runtime Configuration

Configure these environment variables in Render, Azure Container Apps, or any other container host:

```text
API_KEY=your-secret-api-key
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=your-dashboard-password
DATABASE_URL=sqlite:///./data/calls.db
LOADS_DATABASE_URL=postgresql://user:password@host:5432/dbname
```

`API_KEY` is required. HappyRobot and scripts use it as:

```text
x-api-key: your-secret-api-key
```

`DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` protect the dashboard login page. If `DASHBOARD_PASSWORD` is not set, it defaults to `API_KEY`.

`DATABASE_URL` stores dashboard/call analytics records. For Docker/local PoC usage, `sqlite:///./data/calls.db` works with the mounted `./data` folder. For production or client handoff, prefer Postgres for durable analytics storage. If SQLite is kept in production, use a persistent disk so call records are not lost on redeploy or restart.

`LOADS_DATABASE_URL` points to the customer's PostgreSQL database containing the `loads` table. The application treats this database as read-only for normal agent workflows.

The container command supports `PORT`, but it does not need to be configured manually for normal deployments. Render injects it automatically, and the Dockerfile falls back to `8000` when `PORT` is not set.

Optional workflow-side variable:

```text
FMCSA_API_KEY=<configured in HappyRobot/workflow environment>
```

Use this only if the HappyRobot workflow performs carrier verification through the public FMCSA API. It is not read by the FastAPI service in this repository.

## Data Storage

### Loads

Loads are stored separately in the customer PostgreSQL database configured by `LOADS_DATABASE_URL`.

`GET /api/loads/search` reads from the `loads` table using origin, destination, equipment type, and limit filters. Normal customer deployments should use a read-only database user for `LOADS_DATABASE_URL`.

### Completed Calls

When a call ends, HappyRobot sends:

```text
POST /webhook/call-completed
x-api-key: <API_KEY>
content-type: application/json
```

FastAPI extracts selected fields from:

- `call_metadata`
- `offer_data`
- `call_outcome`
- `carrier_sentiment`

Those selected fields are stored in the `call_records` table through SQLAlchemy. The database used for `call_records` is `DATABASE_URL`.

The full raw webhook payload is not persisted as-is. The dashboard reads stored call data through `/api/calls` and aggregate metrics through `/api/stats`.

Current persistence behavior:

- `app/database.py` defaults to `sqlite:///./data/calls.db` if `DATABASE_URL` is not set.
- `docker-compose.yml` sets `DATABASE_URL=sqlite:///./data/calls.db`.
- Docker Compose mounts `./data:/app/data`, so local Docker call records persist in the local `data/` folder.
- On Render or similar hosts, SQLite data is not durable unless a persistent disk is configured.
- For production/client handoff, use Postgres for `DATABASE_URL`.

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

If the customer's internal schema differs, expose a database view named `loads` with the schema above.

## API Endpoints

Browser and health routes:

```text
GET  /
GET  /login
POST /login
GET  /logout
GET  /health
```

Protected with `x-api-key`, query `api_key`, or dashboard cookie depending on the route:

```text
POST /webhook/call-completed
GET  /api/calls
GET  /api/stats
GET  /events
GET  /api/loads/search
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

## Dashboard

The dashboard is served by FastAPI:

- `/login` serves the login page.
- `/` serves `dashboard.html` after login.
- `/static` serves dashboard logos and static assets.
- The browser calls `/api/stats`, `/api/calls`, and `/events` after login.

Main metrics shown:

- Total calls
- Booking rate
- Abandonment rate
- Average duration
- Average P70 latency
- Average negotiation rounds
- Outcome distribution
- Carrier sentiment distribution
- Negotiation performance
- Recent calls table and call inspector

## Local Development

Create `.env` from `.env.example`:

```powershell
Copy-Item .env.example .env
```

For Docker/local PoC usage, prefer:

```text
DATABASE_URL=sqlite:///./data/calls.db
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
DASHBOARD_USERNAME=<dashboard-user>
DASHBOARD_PASSWORD=<dashboard-password>
LOADS_DATABASE_URL=<customer-loads-postgres-url>
DATABASE_URL=<analytics-postgres-url-or-sqlite-with-persistent-disk>
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
- HappyRobot webhook and protected API calls use `x-api-key`.
- Dashboard login uses HttpOnly same-origin cookies for dashboard API reads.
- Secrets are injected through environment variables, not committed to Git.
- The customer loads database should be accessed with a read-only user.
- CORS is currently configured as `*` for the PoC. Restrict it for production deployments.
- FMCSA carrier verification, if enabled, should keep the FMCSA API key in the HappyRobot/workflow environment.

## Portability

The same Docker image can run in Render, Azure Container Apps, AWS ECS, Google Cloud Run, or a customer-owned environment.

To point the container at customer infrastructure, change environment variables only:

```text
LOADS_DATABASE_URL
DATABASE_URL
API_KEY
DASHBOARD_USERNAME
DASHBOARD_PASSWORD
```

No code changes are required as long as the customer exposes the expected `loads` table schema.
