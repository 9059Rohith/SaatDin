# SaatDin Setup Guide

This guide helps you run the SaatDin project locally with both the Flutter app and the FastAPI backend.

## 1. Prerequisites

Install the following tools:
- Flutter SDK (stable)
- Dart SDK (comes with Flutter)
- Python 3.11+
- Android Studio or VS Code + Android SDK
- Git

Verify installation:

```powershell
flutter --version
dart --version
python --version
```

## 2. Project Structure (Important Paths)

- Flutter app source: lib/
- Flutter assets: assets/
- Zone risk data: assets/data/zone_risk_runtime.json
- Backend source: backend/app/main.py
- Backend dependencies: backend/requirements.txt

## 3. Flutter App Setup

From project root, install dependencies:

```powershell
flutter pub get
```

Run the app:

```powershell
flutter run
```

## 4. Backend Setup (FastAPI)

From project root, install backend dependencies:

```powershell
python -m pip install -r backend/requirements.txt
```

Create environment config for Supabase (required):

```powershell
copy backend/.env.example .env
```

Edit `.env` and set:

```env
SUPABASE_DB_URL=postgresql://postgres:<password>@<host>:5432/postgres
FRAUD_SCORING_ENABLED=true
FRAUD_MODEL_PATH=backend/models/fraud/fraud_iforest_latest.joblib
FRAUD_ANOMALY_THRESHOLD=-0.05
FRAUD_FAIL_OPEN=true
```

Optional: migrate existing local SQLite data into Supabase once:

```powershell
python backend/scripts/migrate_sqlite_to_supabase.py --sqlite backend/backend_data.db --supabase-db-url "postgresql://postgres:<password>@<host>:5432/postgres"
```

Train/version fraud anomaly model artifact:

```powershell
python backend/scripts/train_isolation_forest.py --output-dir backend/models/fraud --version v1
```

Start backend server:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Backend base URL expected by app:
- http://localhost:8000/api/v1

## 5. Verify Backend Is Running

Health check:

```powershell
curl http://127.0.0.1:8000/api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

## 6. Current Implemented API Endpoints

- GET /api/v1/health
- POST /api/v1/auth/send-otp
- POST /api/v1/auth/verify-otp
- GET /api/v1/platforms
- GET /api/v1/zones
- GET /api/v1/zones/{pincode}
- GET /api/v1/plans?zone={zone}&platform={platform}
- POST /api/v1/register
- GET /api/v1/triggers/active?zone={zone}

## 7. Run App + Backend Together

1. Terminal A (backend):

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

2. Terminal B (flutter):

```powershell
flutter run
```

The app will use backend endpoints where available and fallback behavior where needed.

## 8. Troubleshooting

### Android SDK location error
If you see SDK location not found, set Android SDK path in android/local.properties:

```properties
sdk.dir=C:\\Users\\<your-username>\\AppData\\Local\\Android\\Sdk
```

Or set ANDROID_HOME environment variable.

### Backend import/runtime errors
Reinstall backend dependencies:

```powershell
python -m pip install -r backend/requirements.txt --upgrade
```

### App cannot reach backend
- Ensure backend is running on 127.0.0.1:8000
- Verify ApiService baseUrl is http://localhost:8000/api/v1
- On emulator/device, localhost mapping may differ

## 9. Useful Dev Commands

```powershell
flutter analyze
flutter test
python -m compileall backend/app/main.py
python backend/scripts/train_isolation_forest.py --output-dir backend/models/fraud --version v1
```

## 10. Notes

- Zone and risk data are currently loaded from assets/data/zone_risk_runtime.json.
- Dynamic onboarding zone selection and plan pricing are integrated.
- Additional Phase 2 modules (persistent DB, scheduled triggers, claims payout flow) can be built on top of this setup.

## 11. Co-Claim Cluster Risk Scoring (Ops)

SaatDin includes a scheduled co-claim graph pipeline for coordinated-timing fraud analysis.

- **Pipeline cadence:** configurable via `CO_CLAIM_GRAPH_SCHEDULE_HOURS` (default 24).
- **Lookback window:** `CO_CLAIM_GRAPH_LOOKBACK_DAYS` (default 30).
- **Co-claim event bucket:** claims in the same zone + trigger type + `CO_CLAIM_GRAPH_TIME_BUCKET_MINUTES` are linked.
- **Edge support gate:** only user pairs with at least `CO_CLAIM_GRAPH_MIN_EDGE_SUPPORT` co-claim events are kept.

### Edge and cluster scoring

1. **Edge frequency score** = `min(1.0, co_claim_count / (2 * min_edge_support))`
2. **Edge recency score** = exponential half-life decay using `CO_CLAIM_GRAPH_RECENCY_HALF_LIFE_DAYS`
3. **Edge weight** = `0.65 * frequency + 0.35 * recency`
4. **Cluster risk score** = `0.45 * frequency + 0.25 * recency + 0.20 * density + 0.10 * activity`

Risk levels:
- **high**: `score >= CO_CLAIM_GRAPH_HIGH_RISK_THRESHOLD`
- **medium**: `score >= CO_CLAIM_GRAPH_MEDIUM_RISK_THRESHOLD`
- **low**: below medium threshold

> Cluster score is advisory for ops review only. It does **not** auto-deny claims.

### Ops API

- `GET /api/v1/fraud/runs` — recent cluster generation runs
- `GET /api/v1/fraud/clusters` — flagged or filtered cluster list
- `GET /api/v1/fraud/clusters/{cluster_id}` — cluster members, edges, and metadata
- `POST /api/v1/fraud/clusters/run` — manual generation trigger

## 12. Cell-Tower Cross-Check Signal (GPS Anti-Spoofing)

SaatDin accepts app-observable tower metadata and evaluates it against the worker's claimed zone.

### Mobile telemetry contract

- Endpoint: `POST /api/v1/workers/location-signal`
- Payload fields:
  - `latitude`, `longitude`, `accuracyMeters`, `capturedAt` (optional GPS snapshot)
  - `towerMetadata.servingCell` and optional `towerMetadata.neighborCells[]`
  - each cell can include: `cellId`, `radioType`, `mcc`, `mnc`, `tac`, `signalDbm`, `signalLevel`, and optional `approxLatitude`/`approxLongitude`
  - `towerMetadata.networkZoneHintPincode` (optional network-side zone hint)

### Validation behavior

- Fresh signal required: older than `TOWER_SIGNAL_FRESHNESS_MINUTES` is treated as `stale`.
- When tower coordinates are present, backend computes distance from claimed zone center:
  - near zone -> `match`, higher confidence
  - far from zone -> `mismatch`, lower confidence
- If coordinates are missing, backend can use `networkZoneHintPincode` as a weaker hint (`match_hint` / `mismatch_hint`).
- If no usable tower signal exists, status is `missing` or `insufficient`.

### Fraud scoring contribution + fallback

- Tower signal contribution is additive and bounded:
  - weight: `TOWER_VALIDATION_SCORE_WEIGHT`
  - cap: `TOWER_VALIDATION_ADJUSTMENT_CAP`
- Missing/stale/insufficient tower data stays neutral (no score adjustment).
- Tower signal is advisory only and does **not** auto-deny claims on its own.

## 13. Motion Signal Features (Static-Spoof Separation)

SaatDin supports privacy-safe motion aggregates to distinguish genuine movement from static spoof behavior.

### Contract and collection windows

- Endpoint: `POST /api/v1/workers/location-signal`
- Additional payload object: `motionMetadata`
  - `windowSeconds`
  - `sampleCount`
  - optional aggregate metrics: `movingSeconds`, `stationarySeconds`, `distanceMeters`, `avgSpeedMps`, `maxSpeedMps`, `headingChangeRate`
- Quality gates are configurable:
  - `MOTION_MIN_WINDOW_SECONDS`
  - `MOTION_MIN_SAMPLE_COUNT`
  - `MOTION_SIGNAL_FRESHNESS_MINUTES`

### Motion scoring + false-positive guardrails

- Rule-based evaluator emits `match/static/mismatch/missing/stale/insufficient` with confidence.
- Fraud contribution is bounded:
  - `MOTION_VALIDATION_SCORE_WEIGHT`
  - `MOTION_VALIDATION_ADJUSTMENT_CAP`
- Missing/stale/insufficient motion data remains neutral.
- False-positive guardrail: negative motion penalty is reduced unless corroborating risk exists (e.g. poor zone affinity or tower mismatch).
- Motion score is advisory and does **not** auto-deny claims by itself.

### Privacy retention and access policy

- Only aggregate motion metrics are accepted; raw sensor traces are not stored.
- Latest signal snapshots are retained with bounded lifecycle using `MOTION_SIGNAL_RETENTION_DAYS` cleanup.
- Access is restricted to fraud-evaluation path and claim review metadata; no full motion analytics dashboard is part of this scope.
