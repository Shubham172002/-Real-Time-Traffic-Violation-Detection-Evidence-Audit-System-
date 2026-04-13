"""
Seed the database with default roles, violation rules, and demo users.
Run once: python database/seed_data.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta
from utils.database import init_db, SessionLocal
from utils.models import User, Vehicle, ViolationRule, Violation, Challan, Appeal
from utils.auth import hash_password
from utils.helpers import generate_challan_number


def seed():
    init_db()
    db = SessionLocal()

    # ── Violation Rules ───────────────────────────────────────────────────────
    rules = [
        ("speeding",         1000.0, "Exceeding speed limit"),
        ("red_light",        1500.0, "Jumping red signal"),
        ("wrong_lane",        500.0, "Driving in wrong lane"),
        ("no_helmet",         500.0, "Riding without helmet"),
        ("no_seatbelt",      1000.0, "Driving without seatbelt"),
        ("illegal_parking",   500.0, "Parking in no-parking zone"),
        ("other",             200.0, "Other traffic violation"),
    ]
    for vtype, amount, desc in rules:
        if not db.query(ViolationRule).filter_by(violation_type=vtype).first():
            db.add(ViolationRule(violation_type=vtype, fine_amount=amount, description=desc))
    db.commit()
    print("[OK] Violation rules seeded.")

    # ── Demo Users ────────────────────────────────────────────────────────────
    users_data = [
        ("Admin User",     "admin@traffic.gov",    "Admin@123",    "9900000001", "admin"),
        ("Officer Raju",   "officer@traffic.gov",  "Officer@123",  "9900000002", "officer"),
        ("Officer Priya",  "officer2@traffic.gov", "Officer@123",  "9900000003", "officer"),
        ("Rahul Citizen",  "citizen@example.com",  "Citizen@123",  "9900000004", "citizen"),
        ("Meena Citizen",  "citizen2@example.com", "Citizen@123",  "9900000005", "citizen"),
        ("Reviewer Kumar", "reviewer@traffic.gov", "Reviewer@123", "9900000006", "reviewer"),
        ("Auditor Singh",  "auditor@traffic.gov",  "Auditor@123",  "9900000007", "auditor"),
    ]
    user_objs = {}
    for name, email, pwd, phone, role in users_data:
        u = db.query(User).filter_by(email=email).first()
        if not u:
            u = User(name=name, email=email, phone=phone,
                     password_hash=hash_password(pwd), role=role)
            db.add(u)
            db.flush()
        user_objs[email] = u
    db.commit()
    print("[OK] Demo users seeded.")

    # ── Demo Vehicles ─────────────────────────────────────────────────────────
    vehicles_data = [
        ("MH12AB1234", user_objs["citizen@example.com"].id,  "Honda City",   "White",  "car"),
        ("DL01CD5678", user_objs["citizen2@example.com"].id, "Bajaj Pulsar", "Black",  "bike"),
        ("KA03EF9012", None,                                  "Maruti Swift", "Silver", "car"),
        ("TN07GH3456", user_objs["citizen@example.com"].id,  "Toyota Innova","Blue",   "car"),
    ]
    veh_objs = {}
    for plate, owner_id, model, color, vtype in vehicles_data:
        v = db.query(Vehicle).filter_by(plate_number=plate).first()
        if not v:
            v = Vehicle(plate_number=plate, owner_id=owner_id,
                        model=model, color=color, vehicle_type=vtype)
            db.add(v)
            db.flush()
        veh_objs[plate] = v
    db.commit()
    print("[OK] Demo vehicles seeded.")

    # ── Demo Violations + Challans ────────────────────────────────────────────
    officer = user_objs["officer@traffic.gov"]
    sample_violations = [
        {
            "vehicle": veh_objs["MH12AB1234"],
            "type": "speeding",
            "location": "NH-48, Pune Bypass Km 12",
            "lat": 18.5204, "lon": 73.8567,
            "speed_recorded": 95.0, "speed_limit": 60.0,
            "status": "challan_issued",
            "amount": 1500.0,
        },
        {
            "vehicle": veh_objs["DL01CD5678"],
            "type": "no_helmet",
            "location": "MG Road, Bengaluru",
            "lat": 12.9716, "lon": 77.5946,
            "speed_recorded": None, "speed_limit": None,
            "status": "paid",
            "amount": 500.0,
        },
        {
            "vehicle": veh_objs["KA03EF9012"],
            "type": "red_light",
            "location": "Silk Board Junction, Bengaluru",
            "lat": 12.9170, "lon": 77.6231,
            "speed_recorded": None, "speed_limit": None,
            "signal_status": "RED",
            "status": "appealed",
            "amount": 1500.0,
        },
        {
            "vehicle": veh_objs["TN07GH3456"],
            "type": "illegal_parking",
            "location": "Brigade Road, Bengaluru",
            "lat": 12.9750, "lon": 77.6070,
            "speed_recorded": None, "speed_limit": None,
            "status": "challan_issued",
            "amount": 500.0,
        },
        {
            "vehicle": veh_objs["MH12AB1234"],
            "type": "wrong_lane",
            "location": "Baner Road, Pune",
            "lat": 18.5601, "lon": 73.7894,
            "speed_recorded": None, "speed_limit": None,
            "status": "challan_issued",
            "amount": 500.0,
        },
    ]

    for idx, vd in enumerate(sample_violations):
        existing = db.query(Violation).filter_by(
            vehicle_id=vd["vehicle"].id, violation_type=vd["type"],
            location=vd["location"]
        ).first()
        if existing:
            continue

        days_ago = idx * 5 + 2
        created = datetime.utcnow() - timedelta(days=days_ago)

        viol = Violation(
            vehicle_id=vd["vehicle"].id,
            officer_id=officer.id,
            violation_type=vd["type"],
            location=vd["location"],
            latitude=vd.get("lat"),
            longitude=vd.get("lon"),
            speed_recorded=vd.get("speed_recorded"),
            speed_limit=vd.get("speed_limit"),
            signal_status=vd.get("signal_status"),
            description=f"Demo violation #{idx + 1}",
            status=vd["status"],
            created_at=created,
        )
        db.add(viol)
        db.flush()

        if vd["status"] in ("challan_issued", "paid", "appealed"):
            challan_status = "paid" if vd["status"] == "paid" else \
                             "under_appeal" if vd["status"] == "appealed" else "unpaid"
            challan = Challan(
                violation_id=viol.id,
                challan_number=generate_challan_number(),
                amount=vd["amount"],
                status=challan_status,
                due_date=created + timedelta(days=30),
                payment_date=created + timedelta(days=5) if challan_status == "paid" else None,
                created_at=created,
            )
            db.add(challan)
            db.flush()

            if vd["status"] == "appealed" and vd["vehicle"].owner_id:
                appeal = Appeal(
                    challan_id=challan.id,
                    citizen_id=vd["vehicle"].owner_id,
                    reason="I was not in the city on that date. This is a case of mistaken identity.",
                    status="pending",
                    submitted_at=created + timedelta(days=3),
                )
                db.add(appeal)

    db.commit()
    print("[OK] Demo violations and challans seeded.")
    print("\n Demo Login Credentials:")
    print("  Admin    : admin@traffic.gov    / Admin@123")
    print("  Officer  : officer@traffic.gov  / Officer@123")
    print("  Citizen  : citizen@example.com  / Citizen@123")
    print("  Reviewer : reviewer@traffic.gov / Reviewer@123")
    print("  Auditor  : auditor@traffic.gov  / Auditor@123")
    db.close()


if __name__ == "__main__":
    seed()
