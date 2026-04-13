"""
Traffic violation detection and validation logic.
Rules-based engine: determines violation type, status, and challan amount.
"""
from typing import Optional
from dataclasses import dataclass


@dataclass
class DetectionResult:
    is_violation: bool
    violation_type: Optional[str]
    violation_status: str            # confirmed / possible / none
    challan_amount: float
    evidence_hash_verified: bool
    notes: str


def detect_speeding(speed_recorded: float, speed_limit: float) -> bool:
    """Return True if speed exceeds limit by more than 0 km/h."""
    return speed_recorded > speed_limit


def detect_red_light(signal_status: str, crossing_detected: bool) -> bool:
    """Red-light violation: signal is RED and crossing was detected."""
    return signal_status.upper() == "RED" and crossing_detected


def evaluate_violation(
    violation_type: str,
    speed_recorded: Optional[float],
    speed_limit: Optional[float],
    signal_status: Optional[str],
    crossing_detected: bool,
    fine_rules: dict,
    evidence_bytes: Optional[bytes],
    stored_hash: Optional[str],
) -> DetectionResult:
    """
    Core detection logic. fine_rules maps violation_type -> amount.
    Returns a DetectionResult with full evaluation.
    """
    from utils.helpers import verify_file_hash

    # Evidence integrity check
    hash_verified = False
    if evidence_bytes and stored_hash:
        hash_verified = verify_file_hash(evidence_bytes, stored_hash)

    is_violation = False
    status = "none"
    amount = 0.0
    notes = ""

    if violation_type == "speeding" and speed_recorded and speed_limit:
        excess = speed_recorded - speed_limit
        is_violation = detect_speeding(speed_recorded, speed_limit)
        if is_violation:
            status = "confirmed"
            base = fine_rules.get("speeding", 1000.0)
            # Progressive fines: +50% per 20 km/h over limit
            multiplier = 1.0 + (excess // 20) * 0.5
            amount = base * multiplier
            notes = f"Speed {speed_recorded:.1f} km/h in a {speed_limit:.0f} km/h zone (+{excess:.1f} km/h over)."

    elif violation_type == "red_light":
        is_violation = detect_red_light(signal_status or "", crossing_detected)
        if is_violation:
            status = "confirmed"
            amount = fine_rules.get("red_light", 1500.0)
            notes = "Vehicle crossed signal during RED phase."

    elif violation_type == "wrong_lane":
        is_violation = True
        status = "confirmed"
        amount = fine_rules.get("wrong_lane", 500.0)
        notes = "Vehicle detected in wrong lane."

    elif violation_type == "no_helmet":
        is_violation = True
        status = "confirmed"
        amount = fine_rules.get("no_helmet", 500.0)
        notes = "Rider without helmet detected."

    elif violation_type == "no_seatbelt":
        is_violation = True
        status = "confirmed"
        amount = fine_rules.get("no_seatbelt", 1000.0)
        notes = "Driver without seatbelt detected."

    elif violation_type == "illegal_parking":
        is_violation = True
        status = "confirmed"
        amount = fine_rules.get("illegal_parking", 500.0)
        notes = "Vehicle parked in no-parking zone."

    else:  # other
        is_violation = True
        status = "possible"
        amount = fine_rules.get("other", 200.0)
        notes = "Violation recorded by officer."

    return DetectionResult(
        is_violation=is_violation,
        violation_type=violation_type if is_violation else None,
        violation_status=status,
        challan_amount=amount,
        evidence_hash_verified=hash_verified,
        notes=notes,
    )


def get_default_fine_rules() -> dict:
    return {
        "speeding": 1000.0,
        "red_light": 1500.0,
        "wrong_lane": 500.0,
        "no_helmet": 500.0,
        "no_seatbelt": 1000.0,
        "illegal_parking": 500.0,
        "other": 200.0,
    }


def load_fine_rules(db) -> dict:
    """Load active fine rules from DB, fall back to defaults."""
    try:
        from utils.models import ViolationRule
        rules = db.query(ViolationRule).filter(ViolationRule.is_active == True).all()
        if rules:
            return {r.violation_type: r.fine_amount for r in rules}
    except Exception:
        pass
    return get_default_fine_rules()
