"""
FastAPI backend — deployed as Vercel Serverless Functions.
The Streamlit frontend (on Render / Streamlit Cloud) calls this API.

Endpoints are grouped by role:
  /api/auth        — login, register
  /api/violations  — CRUD for violations
  /api/evidence    — upload / verify evidence
  /api/challans    — challans + payment
  /api/appeals     — submit / review appeals
  /api/analytics   — hotspots, stats (admin)
  /api/audit       — evidence access logs (auditor)
"""

import os
import sys

# Make project root importable from api/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

load_dotenv()

from utils.database import init_db, SessionLocal
from utils.models import (
    User, Vehicle, Violation, Evidence, EvidenceAccessLog,
    Challan, Appeal, AppealDecision, ViolationRule, Notification
)
from utils.auth import (
    authenticate_user, hash_password, create_token,
    decode_token, get_user_by_id
)
from utils.helpers import (
    generate_challan_number, compute_file_hash,
    violation_type_label, format_currency
)
from utils.storage import upload_evidence, get_file_category, validate_file_size
from utils.detection import evaluate_violation, load_fine_rules

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Traffic Violation Detection API",
    description="Backend API for Real-Time Traffic Violation + Evidence Audit System",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict to your Streamlit domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# ── DB dependency ─────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Auth dependency ───────────────────────────────────────────────────────────
def get_current_user(authorization: str = Header(None), db=Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token   = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token expired or invalid")
    user = get_user_by_id(db, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_roles(*roles):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {roles}")
        return current_user
    return checker


# ═════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    password: str

@app.post("/api/auth/login")
def login(req: LoginRequest, db=Depends(get_db)):
    user = authenticate_user(db, req.email.strip().lower(), req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.email, user.role)
    return {
        "token": token,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
    }

@app.post("/api/auth/register")
def register(req: RegisterRequest, db=Depends(get_db)):
    if db.query(User).filter_by(email=req.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name=req.name, email=req.email.lower(), phone=req.phone,
        password_hash=hash_password(req.password), role="citizen"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Registered successfully", "user_id": user.id}

@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id, "name": current_user.name,
        "email": current_user.email, "role": current_user.role,
        "phone": current_user.phone,
    }


# ═════════════════════════════════════════════════════════════════════════════
# VIOLATIONS
# ═════════════════════════════════════════════════════════════════════════════

class ViolationCreate(BaseModel):
    plate_number: str
    violation_type: str
    location: str
    speed_recorded: Optional[float] = None
    speed_limit: Optional[float] = None
    signal_status: Optional[str] = None
    crossing_detected: bool = False
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    detection_method: str = "manual"

@app.post("/api/violations")
def create_violation(
    req: ViolationCreate,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("officer", "admin"))
):
    vehicle = db.query(Vehicle).filter_by(plate_number=req.plate_number.upper()).first()
    if not vehicle:
        vehicle = Vehicle(plate_number=req.plate_number.upper(), model="Unknown")
        db.add(vehicle)
        db.flush()

    fine_rules = load_fine_rules(db)
    result = evaluate_violation(
        req.violation_type, req.speed_recorded, req.speed_limit,
        req.signal_status, req.crossing_detected, fine_rules, None, None
    )

    v = Violation(
        vehicle_id=vehicle.id, officer_id=current_user.id,
        violation_type=req.violation_type, location=req.location,
        latitude=req.latitude, longitude=req.longitude,
        speed_recorded=req.speed_recorded, speed_limit=req.speed_limit,
        signal_status=req.signal_status,
        description=req.description or result.notes,
        status="pending", detection_method=req.detection_method,
    )
    db.add(v)
    db.commit()
    return {
        "violation_id": v.id,
        "detection": {
            "status": result.violation_status,
            "challan_amount": result.challan_amount,
            "notes": result.notes,
        }
    }

@app.get("/api/violations")
def list_violations(
    status: Optional[str] = None,
    plate: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Violation)
    if current_user.role == "officer":
        query = query.filter_by(officer_id=current_user.id)
    elif current_user.role == "citizen":
        vehicle_ids = [v.id for v in db.query(Vehicle).filter_by(owner_id=current_user.id).all()]
        query = query.filter(Violation.vehicle_id.in_(vehicle_ids))
    if status:
        query = query.filter_by(status=status)
    if plate:
        query = query.join(Vehicle).filter(Vehicle.plate_number.ilike(f"%{plate}%"))
    violations = query.order_by(Violation.created_at.desc()).limit(limit).all()
    return [
        {
            "id": v.id,
            "plate": v.vehicle.plate_number if v.vehicle else None,
            "type": v.violation_type,
            "type_label": violation_type_label(v.violation_type),
            "location": v.location,
            "status": v.status,
            "evidence_count": len(v.evidence),
            "challan_number": v.challan.challan_number if v.challan else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in violations
    ]

@app.get("/api/violations/{violation_id}")
def get_violation(
    violation_id: int,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    v = db.query(Violation).get(violation_id)
    if not v:
        raise HTTPException(status_code=404, detail="Violation not found")
    return {
        "id": v.id, "plate": v.vehicle.plate_number if v.vehicle else None,
        "type": v.violation_type, "location": v.location,
        "speed_recorded": v.speed_recorded, "speed_limit": v.speed_limit,
        "signal_status": v.signal_status, "status": v.status,
        "description": v.description,
        "evidence": [
            {"id": e.id, "file_type": e.file_type, "file_hash": e.file_hash,
             "file_size_kb": e.file_size_kb, "created_at": e.created_at.isoformat()}
            for e in v.evidence if not e.is_deleted
        ],
        "challan": {
            "number": v.challan.challan_number, "amount": v.challan.amount,
            "status": v.challan.status,
            "due_date": v.challan.due_date.isoformat() if v.challan.due_date else None,
        } if v.challan else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# EVIDENCE
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/evidence/upload")
async def upload_evidence_file(
    violation_id: int = Form(...),
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user: User = Depends(require_roles("officer", "admin"))
):
    violation = db.query(Violation).get(violation_id)
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")

    file_bytes = await file.read()
    size_err   = validate_file_size(file_bytes, file.filename)
    if size_err:
        raise HTTPException(status_code=400, detail=size_err)

    file_hash = compute_file_hash(file_bytes)
    cat       = get_file_category(file.filename)

    try:
        file_url, unique_name = upload_evidence(file_bytes, file.filename, violation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage error: {e}")

    ev = Evidence(
        violation_id=violation_id, file_name=unique_name,
        file_url=file_url, file_hash=file_hash, file_type=cat,
        file_size_kb=round(len(file_bytes) / 1024, 2),
        uploaded_by=current_user.id,
    )
    db.add(ev)
    db.flush()

    log = EvidenceAccessLog(
        evidence_id=ev.id, accessed_by=current_user.id,
        action="upload", ip_address="api",
        hash_at_access=file_hash, hash_verified=True,
        notes=f"Uploaded via API by {current_user.role} #{current_user.id}",
    )
    db.add(log)
    db.commit()

    return {
        "evidence_id": ev.id,
        "file_name": unique_name,
        "file_hash": file_hash,
        "file_type": cat,
        "file_size_kb": ev.file_size_kb,
        "message": f"{cat.title()} evidence uploaded and hash stored.",
    }

@app.get("/api/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: int,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ev = db.query(Evidence).get(evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")

    from utils.storage import get_evidence_bytes
    from utils.helpers import verify_file_hash

    file_bytes = get_evidence_bytes(ev.file_url)
    if not file_bytes:
        return {"evidence_id": evidence_id, "verified": None, "reason": "File not accessible in storage"}

    verified = verify_file_hash(file_bytes, ev.file_hash)
    log = EvidenceAccessLog(
        evidence_id=ev.id, accessed_by=current_user.id,
        action="verify", ip_address="api",
        hash_at_access=ev.file_hash, hash_verified=verified,
    )
    db.add(log)
    db.commit()

    return {
        "evidence_id": evidence_id,
        "stored_hash": ev.file_hash,
        "verified": verified,
        "tampered": not verified,
    }


# ═════════════════════════════════════════════════════════════════════════════
# CHALLANS
# ═════════════════════════════════════════════════════════════════════════════

class ChallanCreate(BaseModel):
    violation_id: int
    amount: float
    due_days: int = 30

@app.post("/api/challans")
def issue_challan(
    req: ChallanCreate,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("officer", "admin"))
):
    violation = db.query(Violation).get(req.violation_id)
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")
    if violation.challan:
        raise HTTPException(status_code=400, detail="Challan already issued for this violation")

    challan = Challan(
        violation_id=req.violation_id,
        challan_number=generate_challan_number(),
        amount=req.amount,
        status="unpaid",
        due_date=datetime.utcnow() + timedelta(days=req.due_days),
    )
    db.add(challan)
    violation.status = "challan_issued"
    db.commit()
    return {"challan_id": challan.id, "challan_number": challan.challan_number, "amount": challan.amount}

class PaymentRequest(BaseModel):
    payment_method: str
    payment_reference: str

@app.post("/api/challans/{challan_id}/pay")
def pay_challan(
    challan_id: int,
    req: PaymentRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    challan = db.query(Challan).get(challan_id)
    if not challan:
        raise HTTPException(status_code=404, detail="Challan not found")
    if challan.status != "unpaid":
        raise HTTPException(status_code=400, detail=f"Challan is {challan.status}, cannot pay")
    challan.status            = "paid"
    challan.payment_date      = datetime.utcnow()
    challan.payment_method    = req.payment_method
    challan.payment_reference = req.payment_reference
    challan.violation.status  = "paid"
    db.commit()
    return {"message": "Payment recorded", "challan_number": challan.challan_number}


# ═════════════════════════════════════════════════════════════════════════════
# APPEALS
# ═════════════════════════════════════════════════════════════════════════════

class AppealCreate(BaseModel):
    challan_id: int
    reason: str

@app.post("/api/appeals")
def submit_appeal(
    req: AppealCreate,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("citizen", "admin"))
):
    challan = db.query(Challan).get(req.challan_id)
    if not challan:
        raise HTTPException(status_code=404, detail="Challan not found")
    if challan.status not in ("unpaid", "under_appeal"):
        raise HTTPException(status_code=400, detail="Challan not eligible for appeal")

    appeal = Appeal(
        challan_id=req.challan_id, citizen_id=current_user.id,
        reason=req.reason, status="pending",
    )
    db.add(appeal)
    challan.status = "under_appeal"
    challan.violation.status = "appealed"
    db.commit()
    return {"appeal_id": appeal.id, "status": "pending"}

class DecisionCreate(BaseModel):
    appeal_id: int
    decision: str   # approved / rejected / more_info_needed
    notes: str

@app.post("/api/appeals/decide")
def decide_appeal(
    req: DecisionCreate,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("reviewer", "admin"))
):
    appeal = db.query(Appeal).get(req.appeal_id)
    if not appeal:
        raise HTTPException(status_code=404, detail="Appeal not found")
    if req.decision not in ("approved", "rejected", "more_info_needed"):
        raise HTTPException(status_code=400, detail="Invalid decision")

    dec = AppealDecision(
        appeal_id=req.appeal_id, reviewer_id=current_user.id,
        decision=req.decision, notes=req.notes,
    )
    db.add(dec)

    if req.decision == "approved":
        appeal.status              = "approved"
        appeal.challan.status      = "waived"
        appeal.challan.violation.status = "appeal_approved"
    elif req.decision == "rejected":
        appeal.status              = "rejected"
        appeal.challan.status      = "unpaid"
        appeal.challan.violation.status = "appeal_rejected"
    else:
        appeal.status = "more_info_needed"

    db.commit()
    return {"message": f"Appeal {req.decision}", "appeal_id": req.appeal_id}


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS (Admin)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/analytics/summary")
def analytics_summary(
    days: int = 30,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("admin", "auditor"))
):
    from sqlalchemy import func
    since = datetime.utcnow() - timedelta(days=days)

    total_v  = db.query(func.count(Violation.id)).filter(Violation.created_at >= since).scalar()
    total_c  = db.query(func.count(Challan.id)).filter(Challan.created_at >= since).scalar()
    paid     = db.query(func.sum(Challan.amount)).filter(Challan.status == "paid", Challan.created_at >= since).scalar() or 0
    pending  = db.query(func.sum(Challan.amount)).filter(Challan.status == "unpaid", Challan.created_at >= since).scalar() or 0

    hotspots = (
        db.query(Violation.location, func.count(Violation.id).label("count"))
        .filter(Violation.created_at >= since, Violation.location.isnot(None))
        .group_by(Violation.location)
        .order_by(func.count(Violation.id).desc())
        .limit(10).all()
    )
    top_types = (
        db.query(Violation.violation_type, func.count(Violation.id).label("count"))
        .filter(Violation.created_at >= since)
        .group_by(Violation.violation_type)
        .order_by(func.count(Violation.id).desc())
        .all()
    )

    return {
        "period_days": days,
        "violations": total_v,
        "challans_issued": total_c,
        "revenue_collected": round(paid, 2),
        "pending_collections": round(pending, 2),
        "hotspots": [{"location": r[0], "count": r[1]} for r in hotspots],
        "top_violation_types": [{"type": r[0], "count": r[1]} for r in top_types],
    }

@app.get("/api/analytics/repeat-offenders")
def repeat_offenders(
    min_violations: int = 3,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("admin", "auditor"))
):
    from sqlalchemy import func
    results = (
        db.query(Vehicle.plate_number, func.count(Violation.id).label("count"))
        .join(Violation, Vehicle.id == Violation.vehicle_id)
        .group_by(Vehicle.plate_number)
        .having(func.count(Violation.id) >= min_violations)
        .order_by(func.count(Violation.id).desc())
        .all()
    )
    return [{"plate": r[0], "violation_count": r[1]} for r in results]


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT LOGS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/audit/evidence-logs")
def evidence_audit_logs(
    limit: int = 100,
    action: Optional[str] = None,
    db=Depends(get_db),
    current_user: User = Depends(require_roles("admin", "auditor", "reviewer"))
):
    query = db.query(EvidenceAccessLog).order_by(EvidenceAccessLog.created_at.desc())
    if action:
        query = query.filter_by(action=action)
    logs = query.limit(limit).all()
    return [
        {
            "id": log.id,
            "evidence_id": log.evidence_id,
            "accessed_by": log.accessed_by,
            "action": log.action,
            "hash_verified": log.hash_verified,
            "ip_address": log.ip_address,
            "notes": log.notes,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    from utils.database import check_db_connection
    return {
        "status": "ok",
        "db": "connected" if check_db_connection() else "error",
        "timestamp": datetime.utcnow().isoformat(),
    }

from sqlalchemy import text

@app.get("/api/testing")
def db_test(db=Depends(get_db)):
    try:
        result = db.execute(text("SELECT 1")).fetchone()
        return {"status": "connected", "result": str(result)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
# ── Vercel handler ────────────────────────────────────────────────────────────
# Vercel invokes this as a serverless function
handler = app
