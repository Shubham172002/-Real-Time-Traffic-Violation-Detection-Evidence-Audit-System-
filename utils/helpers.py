"""
General helper utilities: file hashing, challan number generation, etc.
"""
import hashlib
import os
import random
import string
from datetime import datetime
from typing import Optional


def compute_file_hash(file_bytes: bytes) -> str:
    """Return SHA-256 hex digest of file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


def verify_file_hash(file_bytes: bytes, expected_hash: str) -> bool:
    """Return True if file bytes match the stored hash."""
    return compute_file_hash(file_bytes) == expected_hash


def generate_challan_number() -> str:
    """Generate a unique challan number like TRF-2024-XXXXXX."""
    year = datetime.utcnow().year
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"TRF-{year}-{suffix}"


def format_currency(amount: float) -> str:
    return f"₹{amount:,.2f}"


def format_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "N/A"
    return dt.strftime("%d %b %Y, %I:%M %p")


def violation_type_label(vtype: str) -> str:
    labels = {
        "speeding": "Speeding",
        "red_light": "Red Light Jump",
        "wrong_lane": "Wrong Lane",
        "no_helmet": "No Helmet",
        "no_seatbelt": "No Seatbelt",
        "illegal_parking": "Illegal Parking",
        "other": "Other",
    }
    return labels.get(vtype, vtype.replace("_", " ").title())


def status_badge(status: str) -> str:
    """Return an emoji badge for a status string."""
    badges = {
        "pending": "🟡 Pending",
        "challan_issued": "🔴 Challan Issued",
        "paid": "🟢 Paid",
        "appealed": "🔵 Under Appeal",
        "appeal_approved": "✅ Appeal Approved",
        "appeal_rejected": "❌ Appeal Rejected",
        "cancelled": "⚫ Cancelled",
        "unpaid": "🔴 Unpaid",
        "waived": "🟢 Waived",
        "under_appeal": "🔵 Under Appeal",
        "under_review": "🟡 Under Review",
        "approved": "✅ Approved",
        "rejected": "❌ Rejected",
        "more_info_needed": "ℹ️ More Info Needed",
    }
    return badges.get(status, status.replace("_", " ").title())


def get_file_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def is_valid_image(filename: str) -> bool:
    return get_file_extension(filename) in [".jpg", ".jpeg", ".png", ".gif", ".webp"]


def is_valid_video(filename: str) -> bool:
    return get_file_extension(filename) in [".mp4", ".avi", ".mov", ".mkv", ".webm"]


def is_valid_evidence_file(filename: str) -> bool:
    return is_valid_image(filename) or is_valid_video(filename) or \
           get_file_extension(filename) in [".pdf"]


def paginate(items: list, page: int, page_size: int = 10) -> tuple:
    """Return (page_items, total_pages)."""
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], total_pages
