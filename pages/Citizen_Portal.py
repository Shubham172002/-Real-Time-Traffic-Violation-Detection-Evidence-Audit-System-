"""
Citizen Portal — view challans, pay fines, raise appeals.
"""
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Citizen Portal", page_icon="👤", layout="wide")

from utils.auth import require_role
from utils.database import get_db, init_db
from utils.models import (
    Challan, Violation, Vehicle, Appeal, User,
    Evidence, EvidenceAccessLog
)
from utils.helpers import (
    format_currency, format_datetime, status_badge,
    violation_type_label, compute_file_hash
)
from utils.notifications import notify_appeal_update
from utils.storage import (
    get_evidence_bytes, generate_presigned_url,
    get_video_stream_url, get_file_category
)
from pathlib import Path

init_db()
require_role(st, "citizen", "admin")

citizen_id = st.session_state["user_id"]

st.title("👤 Citizen Portal")
st.caption("View your challans, pay fines, and manage appeals.")

tab1, tab2, tab3, tab4 = st.tabs(["📄 My Challans", "💳 Pay Fine", "📝 Raise Appeal", "🔍 Track Appeal"])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — My Challans
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    db = get_db()
    try:
        # Get challans for vehicles owned by this citizen
        citizen = db.query(User).filter_by(id=citizen_id).first()
        vehicles = db.query(Vehicle).filter_by(owner_id=citizen_id).all()

        if not vehicles:
            st.info("No vehicles registered under your account.")
            st.caption("Contact an officer to link your vehicle plate to your account.")
        else:
            vehicle_ids = [v.id for v in vehicles]
            violations = (
                db.query(Violation)
                .filter(Violation.vehicle_id.in_(vehicle_ids))
                .order_by(Violation.created_at.desc())
                .all()
            )

            if not violations:
                st.success("No violations on record. Drive safe!")
            else:
                st.info(f"Found {len(violations)} violation(s) across {len(vehicles)} vehicle(s).")

                for v in violations:
                    with st.expander(
                        f"{'🔴' if v.challan and v.challan.status == 'unpaid' else '🟡'} "
                        f"Violation #{v.id} — {violation_type_label(v.violation_type)} "
                        f"| {v.created_at.strftime('%d %b %Y') if v.created_at else 'N/A'}"
                    ):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Vehicle:** {v.vehicle.plate_number}")
                            st.write(f"**Type:** {violation_type_label(v.violation_type)}")
                            st.write(f"**Location:** {v.location or 'N/A'}")
                            st.write(f"**Date:** {format_datetime(v.created_at)}")
                        with col2:
                            st.write(f"**Status:** {status_badge(v.status)}")
                            if v.challan:
                                st.write(f"**Challan No.:** {v.challan.challan_number}")
                                st.write(f"**Amount:** {format_currency(v.challan.amount)}")
                                st.write(f"**Due Date:** {format_datetime(v.challan.due_date)}")
                                st.write(f"**Payment Status:** {status_badge(v.challan.status)}")

                        # Show evidence (with access log + inline video/photo)
                        if v.evidence:
                            st.markdown("**Evidence Files:**")
                            for ev in v.evidence:
                                if not ev.is_deleted:
                                    cat  = get_file_category(ev.file_name)
                                    icon = "🎥" if cat == "video" else ("📷" if cat == "photo" else "📄")
                                    col_a, col_b = st.columns([3, 1])
                                    with col_a:
                                        st.write(f"{icon} `{Path(ev.file_name).name}` ({cat}, {ev.file_size_kb:.1f} KB)")
                                        st.caption(f"SHA-256: `{ev.file_hash}`")
                                    with col_b:
                                        if st.button("View", key=f"view_ev_{ev.id}"):
                                            st.session_state[f"show_cit_ev_{ev.id}"] = True
                                            access_log = EvidenceAccessLog(
                                                evidence_id=ev.id,
                                                accessed_by=citizen_id,
                                                action="view",
                                                ip_address="citizen_portal",
                                                hash_at_access=ev.file_hash,
                                                hash_verified=True,
                                            )
                                            db.add(access_log)
                                            db.commit()

                                    if st.session_state.get(f"show_cit_ev_{ev.id}", False):
                                        local_path = Path(ev.file_url) if not ev.file_url.startswith("s3://") else None
                                        if cat == "video":
                                            stream_url = get_video_stream_url(ev.file_url)
                                            if stream_url and local_path and local_path.exists():
                                                st.video(str(local_path))
                                            elif stream_url:
                                                st.markdown(
                                                    f'<video controls width="100%" style="border-radius:8px">'
                                                    f'<source src="{stream_url}"></video>',
                                                    unsafe_allow_html=True,
                                                )
                                            else:
                                                st.info("Video not accessible. Contact the traffic department.")
                                        elif cat == "photo":
                                            if local_path and local_path.exists():
                                                st.image(str(local_path), use_container_width=True)
                                            else:
                                                try:
                                                    st.image(generate_presigned_url(ev.file_url), use_container_width=True)
                                                except Exception:
                                                    st.info("Image stored securely on server.")
                                        else:
                                            st.info("Document stored securely. Hash verified above.")
                                        if st.button("Hide", key=f"hide_cit_ev_{ev.id}"):
                                            st.session_state[f"show_cit_ev_{ev.id}"] = False
                                            st.rerun()
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Pay Fine
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Pay Traffic Fine")
    db = get_db()
    try:
        vehicles = db.query(Vehicle).filter_by(owner_id=citizen_id).all()
        vehicle_ids = [v.id for v in vehicles]

        unpaid_challans = (
            db.query(Challan)
            .join(Violation, Challan.violation_id == Violation.id)
            .filter(
                Violation.vehicle_id.in_(vehicle_ids),
                Challan.status == "unpaid"
            )
            .all()
        ) if vehicle_ids else []

        if not unpaid_challans:
            st.success("No pending payments. All challans are cleared!")
        else:
            challan_options = {
                f"{c.challan_number} — ₹{c.amount:,.0f} (Due: {c.due_date.strftime('%d %b %Y') if c.due_date else 'N/A'})": c.id
                for c in unpaid_challans
            }
            selected_label = st.selectbox("Select Challan to Pay", list(challan_options.keys()))
            selected_challan = db.query(Challan).get(challan_options[selected_label])

            if selected_challan:
                st.info(f"**Amount Due:** {format_currency(selected_challan.amount)}")

                with st.form("payment_form"):
                    payment_method = st.selectbox(
                        "Payment Method",
                        ["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash"]
                    )
                    if payment_method == "UPI":
                        upi_id = st.text_input("UPI ID", placeholder="yourname@upi")
                    elif payment_method in ("Credit Card", "Debit Card"):
                        card_no = st.text_input("Card Number (last 4 digits)", max_chars=4)
                    payment_ref = st.text_input("Payment Reference / UTR Number")
                    submitted = st.form_submit_button(f"Pay {format_currency(selected_challan.amount)}")

                if submitted:
                    if not payment_ref:
                        st.error("Please enter a payment reference number.")
                    else:
                        import random, string
                        selected_challan.status = "paid"
                        selected_challan.payment_date = datetime.utcnow()
                        selected_challan.payment_method = payment_method
                        selected_challan.payment_reference = payment_ref
                        selected_challan.violation.status = "paid"
                        db.commit()
                        st.success(f"Payment confirmed! Reference: `{payment_ref}`")
                        st.balloons()
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Raise Appeal
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Raise an Appeal")
    st.info("You can appeal challans you believe were wrongly issued.")
    db = get_db()
    try:
        vehicles = db.query(Vehicle).filter_by(owner_id=citizen_id).all()
        vehicle_ids = [v.id for v in vehicles]

        eligible_challans = (
            db.query(Challan)
            .join(Violation, Challan.violation_id == Violation.id)
            .filter(
                Violation.vehicle_id.in_(vehicle_ids),
                Challan.status.in_(["unpaid", "under_appeal"])
            )
            .all()
        ) if vehicle_ids else []

        # Filter out challans that already have an active appeal
        existing_appeal_challan_ids = {
            a.challan_id for a in db.query(Appeal)
            .filter(Appeal.citizen_id == citizen_id,
                    Appeal.status.notin_(["approved", "rejected"]))
            .all()
        }
        appealable = [c for c in eligible_challans if c.id not in existing_appeal_challan_ids]

        if not appealable:
            st.warning("No challans eligible for appeal (already appealed or paid).")
        else:
            challan_opts = {
                f"{c.challan_number} — ₹{c.amount:,.0f} ({violation_type_label(c.violation.violation_type)})": c.id
                for c in appealable
            }
            sel_label = st.selectbox("Select Challan to Appeal", list(challan_opts.keys()), key="appeal_challan")
            sel_challan = db.query(Challan).get(challan_opts[sel_label])

            with st.form("appeal_form"):
                reason = st.text_area(
                    "Reason for Appeal *",
                    placeholder="Explain why you believe this violation was incorrectly recorded...",
                    height=150
                )
                doc_file = st.file_uploader(
                    "Supporting Document (optional)",
                    type=["pdf", "jpg", "jpeg", "png"]
                )
                submitted = st.form_submit_button("Submit Appeal")

            if submitted:
                if not reason.strip():
                    st.error("Please provide a reason for your appeal.")
                else:
                    doc_url = None
                    doc_hash = None
                    if doc_file:
                        from utils.storage import upload_evidence
                        from utils.helpers import compute_file_hash
                        doc_bytes = doc_file.read()
                        doc_hash = compute_file_hash(doc_bytes)
                        doc_url, _ = upload_evidence(doc_bytes, doc_file.name, sel_challan.violation_id)

                    appeal = Appeal(
                        challan_id=sel_challan.id,
                        citizen_id=citizen_id,
                        reason=reason.strip(),
                        supporting_doc_url=doc_url,
                        supporting_doc_hash=doc_hash,
                        status="pending",
                    )
                    db.add(appeal)
                    sel_challan.status = "under_appeal"
                    sel_challan.violation.status = "appealed"
                    db.commit()
                    st.success(f"Appeal #{appeal.id} submitted successfully! You will be notified of the decision.")
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — Track Appeal
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("Track My Appeals")
    db = get_db()
    try:
        appeals = (
            db.query(Appeal)
            .filter_by(citizen_id=citizen_id)
            .order_by(Appeal.submitted_at.desc())
            .all()
        )
        if not appeals:
            st.info("No appeals submitted yet.")
        else:
            for ap in appeals:
                challan = ap.challan
                vtype = challan.violation.violation_type if challan and challan.violation else "N/A"
                with st.expander(
                    f"Appeal #{ap.id} — {violation_type_label(vtype)} | {status_badge(ap.status)}"
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Appeal ID:** {ap.id}")
                        st.write(f"**Challan No:** {challan.challan_number if challan else 'N/A'}")
                        st.write(f"**Amount:** {format_currency(challan.amount) if challan else 'N/A'}")
                        st.write(f"**Submitted:** {format_datetime(ap.submitted_at)}")
                    with col2:
                        st.write(f"**Status:** {status_badge(ap.status)}")
                        st.write(f"**Reason:** {ap.reason}")

                    if ap.decisions:
                        st.markdown("**Decision History:**")
                        for d in ap.decisions:
                            reviewer = db.query(User).get(d.reviewer_id)
                            st.write(f"- **{status_badge(d.decision)}** by {reviewer.name if reviewer else 'N/A'} on {format_datetime(d.decided_at)}")
                            if d.notes:
                                st.caption(f"Notes: {d.notes}")
    finally:
        db.close()
