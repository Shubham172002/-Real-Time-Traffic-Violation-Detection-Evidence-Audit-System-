# 🚦 Real-Time Traffic Violation Detection + Evidence Audit System

A full-stack web application built with **Streamlit + SQLAlchemy + PostgreSQL** for detecting, recording, and managing traffic violations with a tamper-evident evidence audit trail.

---

## Features

| Feature | Details |
|---|---|
| Role-based access | Admin, Officer, Citizen, Reviewer, Auditor |
| Violation recording | Manual entry + rules-based detection engine |
| Evidence management | Upload photo/video, SHA-256 hash integrity |
| Tamper-evident audit log | Every file access is logged, immutable |
| Challan generation | Auto-numbered, configurable fines |
| Payment tracking | Multiple payment methods, reference tracking |
| Appeal workflow | Submit → Review → Decision with full history |
| Analytics dashboard | Hotspot maps, type breakdown, repeat offenders |
| Background jobs | Daily hotspot reports + payment reminders |
| Cloud-ready | Docker, PostgreSQL, S3 support |

---

## Quick Start (Local)

### Prerequisites
- Python 3.10+
- PostgreSQL (or use SQLite for dev)

### 1. Clone and install

```bash
cd "adbms project2"
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, SECRET_KEY, etc.
```

For quick local dev (SQLite, no setup needed):
```
DATABASE_URL=sqlite:///./traffic.db
```

### 3. Seed the database

```bash
python database/seed_data.py
```

### 4. Run the app

```bash
streamlit run main.py
```

Open http://localhost:8501

---

## Docker (Recommended for Demo)

```bash
docker-compose up --build
```

App available at http://localhost:8501 with PostgreSQL automatically configured.

---

## Demo Login Credentials

| Role     | Email                   | Password     |
|----------|-------------------------|--------------|
| Admin    | admin@traffic.gov       | Admin@123    |
| Officer  | officer@traffic.gov     | Officer@123  |
| Citizen  | citizen@example.com     | Citizen@123  |
| Reviewer | reviewer@traffic.gov    | Reviewer@123 |
| Auditor  | auditor@traffic.gov     | Auditor@123  |

---

## Architecture

```
traffic-violation-system/
├── main.py                      # Streamlit entry + login
├── pages/
│   ├── Officer_Portal.py        # Record violations, upload evidence, issue challans
│   ├── Citizen_Portal.py        # View challans, pay, appeal
│   ├── Reviewer_Portal.py       # Review appeals, deliver decisions
│   ├── Admin_Dashboard.py       # Analytics, rules, user management
│   └── Audit_Logs.py            # Tamper-evident audit trail
├── utils/
│   ├── models.py                # SQLAlchemy ORM models
│   ├── database.py              # DB connection + session management
│   ├── auth.py                  # JWT + bcrypt authentication
│   ├── detection.py             # Rules-based violation detection engine
│   ├── storage.py               # S3/local evidence file storage
│   ├── notifications.py         # Email/SMS notifications
│   └── helpers.py               # Utilities (hashing, formatting, etc.)
├── background/
│   └── scheduler.py             # APScheduler background jobs
├── database/
│   ├── schema.sql               # PostgreSQL DDL
│   └── seed_data.py             # Demo data seeder
├── Dockerfile
└── docker-compose.yml
```

---

## Cloud Deployment

### Render / Railway (Recommended for free tier)

1. Push code to GitHub
2. Create a new Web Service on Render
3. Set environment variables (DATABASE_URL, SECRET_KEY, etc.)
4. Use managed PostgreSQL (Supabase / Neon / Railway)
5. For file storage, configure AWS S3 (set STORAGE_BACKEND=s3)

### AWS EC2 + RDS

```bash
# On EC2 instance
git clone <your-repo>
cd traffic-violation-system
cp .env.example .env
# Edit .env with RDS PostgreSQL URL and S3 credentials
docker-compose up -d
```

### Environment Variables for Production

```
DATABASE_URL=postgresql://user:password@your-rds-host:5432/traffic_violations
SECRET_KEY=<strong-random-key>
STORAGE_BACKEND=s3
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
AWS_REGION=ap-south-1
S3_BUCKET_NAME=your-evidence-bucket
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

---

## Detection Logic

The rules-based engine (`utils/detection.py`) evaluates:

| Rule | Condition |
|---|---|
| **Speeding** | `speed_recorded > speed_limit` |
| **Red Light** | `signal_status == "RED"` AND crossing detected |
| **Progressive fines** | +50% fine per 20 km/h over speed limit |
| **Evidence integrity** | SHA-256 hash stored at upload, verified on access |

Output: `violation_status + challan_amount + evidence_hash_verified`

---

## Database Schema

Key tables:
- `users` — all roles
- `vehicles` — plate → owner mapping
- `violations` — core violation record
- `evidence` — file metadata + SHA-256 hash
- `evidence_access_logs` — **immutable** audit trail (DB trigger prevents UPDATE/DELETE)
- `challans` — fine generation + payment tracking
- `appeals` — citizen appeals
- `appeal_decisions` — reviewer decisions with history
- `violation_rules` — configurable fine amounts
- `notifications` — email/SMS delivery log

---

## Demo Walkthrough

1. **Login as Officer** → Create a violation for `MH12AB1234` (speeding) → Upload a photo as evidence → Issue challan
2. **Login as Citizen** → View challan → Pay OR raise an appeal
3. **Login as Reviewer** → Open appeal queue → View evidence → Verify hash → Approve/Reject
4. **Login as Auditor** → Audit Logs → Check every file access event + hash integrity
5. **Login as Admin** → Analytics → Hotspot chart → Repeat offenders → Update fine rules
