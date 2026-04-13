"""
SQLAlchemy ORM models for the Traffic Violation Detection System.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text,
    DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timezone
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    password_hash = Column(String(200), nullable=False)
    role = Column(
    SAEnum(
            "admin", "officer", "citizen", "reviewer", "auditor",
            name="user_role",
            create_type=False   # IMPORTANT
        ),
        nullable=False,
        default="citizen",
    )
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    violations_reported = relationship("Violation", back_populates="officer", foreign_keys="Violation.officer_id")
    vehicles = relationship("Vehicle", back_populates="owner")
    appeals = relationship("Appeal", back_populates="citizen")
    evidence_logs = relationship("EvidenceAccessLog", back_populates="user")
    notifications = relationship("Notification", back_populates="user")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(20), unique=True, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    model = Column(String(100))
    color = Column(String(50))
    vehicle_type = Column(String(50), default="car")
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="vehicles")
    violations = relationship("Violation", back_populates="vehicle")


class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    violation_type = Column(
        SAEnum("speeding", "red_light", "wrong_lane", "no_helmet", "no_seatbelt", "illegal_parking", "other",
               name="violation_type"),
        nullable=False,
    )
    location = Column(String(300))
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    speed_recorded = Column(Float, nullable=True)
    speed_limit = Column(Float, nullable=True)
    signal_status = Column(String(10), nullable=True)   # RED / GREEN / YELLOW
    description = Column(Text)
    status = Column(
        SAEnum("pending", "challan_issued", "paid", "appealed", "appeal_approved",
               "appeal_rejected", "cancelled", name="violation_status"),
        default="pending",
    )
    detection_method = Column(String(50), default="manual")  # manual / automatic
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="violations")
    officer = relationship("User", back_populates="violations_reported", foreign_keys=[officer_id])
    evidence = relationship("Evidence", back_populates="violation")
    challan = relationship("Challan", back_populates="violation", uselist=False)


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, index=True)
    violation_id = Column(Integer, ForeignKey("violations.id"), nullable=False)
    file_name = Column(String(300), nullable=False)
    file_url = Column(String(600))
    file_hash = Column(String(64), nullable=False)   # SHA-256 hex digest
    file_type = Column(String(10))                   # photo / video / doc
    file_size_kb = Column(Float)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    violation = relationship("Violation", back_populates="evidence")
    uploader = relationship("User")
    access_logs = relationship("EvidenceAccessLog", back_populates="evidence")


class EvidenceAccessLog(Base):
    """Tamper-evident audit trail for all evidence access / modifications."""
    __tablename__ = "evidence_access_logs"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=False)
    accessed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(30))   # view / download / upload / delete / verify
    ip_address = Column(String(50))
    user_agent = Column(String(300))
    hash_at_access = Column(String(64))   # hash captured at time of access
    hash_verified = Column(Boolean, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    evidence = relationship("Evidence", back_populates="access_logs")
    user = relationship("User", back_populates="evidence_logs")


class Challan(Base):
    __tablename__ = "challans"

    id = Column(Integer, primary_key=True, index=True)
    violation_id = Column(Integer, ForeignKey("violations.id"), unique=True, nullable=False)
    challan_number = Column(String(30), unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(
        SAEnum("unpaid", "paid", "waived", "under_appeal", name="challan_status"),
        default="unpaid",
    )
    due_date = Column(DateTime)
    payment_date = Column(DateTime, nullable=True)
    payment_method = Column(String(50), nullable=True)
    payment_reference = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    violation = relationship("Violation", back_populates="challan")
    appeals = relationship("Appeal", back_populates="challan")


class Appeal(Base):
    __tablename__ = "appeals"

    id = Column(Integer, primary_key=True, index=True)
    challan_id = Column(Integer, ForeignKey("challans.id"), nullable=False)
    citizen_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    supporting_doc_url = Column(String(600), nullable=True)
    supporting_doc_hash = Column(String(64), nullable=True)
    status = Column(
        SAEnum("pending", "under_review", "approved", "rejected", "more_info_needed",
               name="appeal_status"),
        default="pending",
    )
    submitted_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    challan = relationship("Challan", back_populates="appeals")
    citizen = relationship("User", back_populates="appeals")
    decisions = relationship("AppealDecision", back_populates="appeal")


class AppealDecision(Base):
    __tablename__ = "appeal_decisions"

    id = Column(Integer, primary_key=True, index=True)
    appeal_id = Column(Integer, ForeignKey("appeals.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(
        SAEnum("approved", "rejected", "more_info_needed", name="decision_type"),
        nullable=False,
    )
    notes = Column(Text)
    decided_at = Column(DateTime, default=datetime.utcnow)

    appeal = relationship("Appeal", back_populates="decisions")
    reviewer = relationship("User")


class RoadSegment(Base):
    __tablename__ = "road_segments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    speed_limit = Column(Float, nullable=False, default=60.0)
    location_description = Column(String(400))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ViolationRule(Base):
    __tablename__ = "violation_rules"

    id = Column(Integer, primary_key=True, index=True)
    violation_type = Column(String(50), unique=True, nullable=False)
    fine_amount = Column(Float, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    updater = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject = Column(String(200))
    message = Column(Text, nullable=False)
    channel = Column(String(20), default="in_app")   # email / sms / in_app
    status = Column(String(20), default="pending")   # pending / sent / failed
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="notifications")
