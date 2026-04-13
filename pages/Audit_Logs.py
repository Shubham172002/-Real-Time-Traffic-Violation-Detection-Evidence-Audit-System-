"""
Audit Logs — tamper-evident evidence access trail, challan history, system events.
Accessible by: admin, officer, auditor, reviewer.
"""
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Audit Logs", page_icon="🔒", layout="wide")

from utils.auth import require_role
from utils.database import get_db, init_db
from utils.models import (
    EvidenceAccessLog, Evidence, Violation, Challan,
    Appeal, AppealDecision, User, Vehicle
)
from utils.helpers import format_datetime, status_badge, violation_type_label, compute_file_hash, format_currency
from utils.storage import get_evidence_bytes

init_db()
require_role(st, "admin", "officer", "reviewer", "auditor")

current_user_id = st.session_state["user_id"]
current_role    = st.session_state["user_role"]

st.title("🔒 Audit Logs")
st.caption("Tamper-evident evidence access trail and complete challan history.")

tab1, tab2, tab3, tab4 = st.tabs([
    "🧾 Evidence Access Logs",
    "📋 Challan History",
    "⚖️ Appeal Audit Trail",
    "🔍 Hash Integrity Check",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Evidence Access Logs
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Evidence Access Audit Trail")
    st.info("Every access, upload, view, download, and verification of evidence is logged here.")

    db = get_db()
    try:
        import pandas as pd
        from sqlalchemy import func

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            date_from = st.date_input("From", datetime.utcnow().date() - timedelta(days=30), key="elog_from")
        with col_f2:
            date_to = st.date_input("To", datetime.utcnow().date(), key="elog_to")
        with col_f3:
            action_filter = st.selectbox("Action", ["all", "upload", "view", "download", "verify", "delete"])

        from_dt = datetime.combine(date_from, datetime.min.time())
        to_dt   = datetime.combine(date_to,   datetime.max.time())

        query = (
            db.query(EvidenceAccessLog)
            .filter(EvidenceAccessLog.created_at.between(from_dt, to_dt))
        )
        if action_filter != "all":
            query = query.filter(EvidenceAccessLog.action == action_filter)

        # Officers/reviewers only see logs for violations they're involved with
        if current_role == "officer":
            ev_ids = [
                ev.id
                for v in db.query(Violation).filter_by(officer_id=current_user_id).all()
                for ev in v.evidence
            ]
            query = query.filter(EvidenceAccessLog.evidence_id.in_(ev_ids))

        logs = query.order_by(EvidenceAccessLog.created_at.desc()).limit(500).all()

        if not logs:
            st.info("No evidence access logs for the selected filters.")
        else:
            rows = []
            for log in logs:
                user = db.query(User).get(log.accessed_by)
                evidence = db.query(Evidence).get(log.evidence_id)
                violation = evidence.violation if evidence else None
                rows.append({
                    "Log ID": log.id,
                    "Evidence ID": log.evidence_id,
                    "Violation ID": violation.id if violation else "N/A",
                    "Action": log.action.upper(),
                    "Accessed By": user.name if user else f"User #{log.accessed_by}",
                    "Role": user.role.upper() if user else "N/A",
                    "IP Address": log.ip_address or "N/A",
                    "Hash Verified": "Yes" if log.hash_verified else ("No" if log.hash_verified is False else "N/A"),
                    "Notes": (log.notes or "")[:50],
                    "Timestamp": log.created_at.strftime("%d %b %Y, %H:%M:%S") if log.created_at else "N/A",
                })
            df_logs = pd.DataFrame(rows)
            st.dataframe(df_logs, use_container_width=True, hide_index=True)
            st.caption(f"Showing {len(rows)} log entries.")

            # Stats
            st.markdown("---")
            col_s1, col_s2, col_s3 = st.columns(3)
            action_counts = df_logs["Action"].value_counts()
            with col_s1:
                st.metric("Total Access Events", len(rows))
            with col_s2:
                upload_count = action_counts.get("UPLOAD", 0)
                st.metric("Uploads", upload_count)
            with col_s3:
                verify_count = action_counts.get("VERIFY", 0)
                st.metric("Verifications", verify_count)

            import plotly.express as px
            if len(rows) > 0:
                fig = px.histogram(df_logs, x="Action", color="Role",
                                   title="Evidence Access by Action and Role",
                                   barmode="group")
                st.plotly_chart(fig, use_container_width=True)
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Challan History
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Complete Challan History")
    db = get_db()
    try:
        import pandas as pd

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            status_filter = st.selectbox("Status", ["all", "unpaid", "paid", "waived", "under_appeal"], key="ch_status")
        with col_f2:
            search_plate = st.text_input("Search by Plate Number", placeholder="MH12AB1234", key="ch_plate").upper()

        query = db.query(Challan).join(Violation, Challan.violation_id == Violation.id)
        if status_filter != "all":
            query = query.filter(Challan.status == status_filter)
        if search_plate:
            query = query.join(Vehicle, Violation.vehicle_id == Vehicle.id).filter(
                Vehicle.plate_number.ilike(f"%{search_plate}%")
            )

        challans = query.order_by(Challan.created_at.desc()).limit(300).all()

        if not challans:
            st.info("No challans found.")
        else:
            rows = []
            for c in challans:
                v = c.violation
                owner = v.vehicle.owner if v and v.vehicle else None
                rows.append({
                    "Challan No": c.challan_number,
                    "Plate": v.vehicle.plate_number if v and v.vehicle else "N/A",
                    "Owner": owner.name if owner else "Unknown",
                    "Violation": violation_type_label(v.violation_type) if v else "N/A",
                    "Location": (v.location or "N/A")[:40] if v else "N/A",
                    "Amount": format_currency(c.amount),
                    "Status": c.status.replace("_", " ").title(),
                    "Due Date": c.due_date.strftime("%d %b %Y") if c.due_date else "N/A",
                    "Paid On": c.payment_date.strftime("%d %b %Y") if c.payment_date else "—",
                    "Method": c.payment_method or "—",
                    "Issued": c.created_at.strftime("%d %b %Y") if c.created_at else "N/A",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"{len(rows)} challans shown.")

            import plotly.express as px
            status_counts = pd.DataFrame(rows)["Status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            fig = px.bar(status_counts, x="Status", y="Count",
                         title="Challan Status Distribution", color="Status")
            st.plotly_chart(fig, use_container_width=True)
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Appeal Audit Trail
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Appeal Audit Trail")
    db = get_db()
    try:
        import pandas as pd

        status_filter_ap = st.selectbox(
            "Appeal Status",
            ["all", "pending", "under_review", "approved", "rejected", "more_info_needed"],
            key="ap_status"
        )

        query = db.query(Appeal)
        if status_filter_ap != "all":
            query = query.filter(Appeal.status == status_filter_ap)
        appeals = query.order_by(Appeal.submitted_at.desc()).limit(200).all()

        if not appeals:
            st.info("No appeals found.")
        else:
            rows = []
            for ap in appeals:
                challan = ap.challan
                citizen = ap.citizen
                last_decision = ap.decisions[-1] if ap.decisions else None
                reviewer = db.query(User).get(last_decision.reviewer_id) if last_decision else None
                rows.append({
                    "Appeal ID": ap.id,
                    "Citizen": citizen.name if citizen else "N/A",
                    "Challan No": challan.challan_number if challan else "N/A",
                    "Amount": format_currency(challan.amount) if challan else "N/A",
                    "Violation": violation_type_label(challan.violation.violation_type) if challan and challan.violation else "N/A",
                    "Status": ap.status.replace("_", " ").title(),
                    "Reviewer": reviewer.name if reviewer else "Pending",
                    "Decision": last_decision.decision.replace("_", " ").title() if last_decision else "—",
                    "Decision Date": last_decision.decided_at.strftime("%d %b %Y") if last_decision and last_decision.decided_at else "—",
                    "Submitted": ap.submitted_at.strftime("%d %b %Y, %H:%M") if ap.submitted_at else "N/A",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — Hash Integrity Check
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("Evidence Hash Integrity Verification")
    st.info(
        "Verify that evidence files have not been tampered with by comparing "
        "the stored SHA-256 hash against the current file hash."
    )

    db = get_db()
    try:
        verify_mode = st.radio(
            "Verification Mode",
            ["Single File", "Bulk Verify All"],
            horizontal=True
        )

        if verify_mode == "Single File":
            ev_id = st.number_input("Evidence ID", min_value=1, step=1)
            uploaded_file = st.file_uploader(
                "Upload the file to verify (optional — checks stored copy if not uploaded)",
                type=["jpg", "jpeg", "png", "mp4", "avi", "pdf"]
            )

            if st.button("Verify Integrity", key="verify_single"):
                ev = db.query(Evidence).get(int(ev_id))
                if not ev:
                    st.error(f"Evidence #{ev_id} not found.")
                else:
                    stored_hash = ev.file_hash
                    st.write(f"**File:** `{ev.file_name}`")
                    st.write(f"**Stored Hash:** `{stored_hash}`")

                    if uploaded_file:
                        file_bytes = uploaded_file.read()
                        computed = compute_file_hash(file_bytes)
                        st.write(f"**Computed Hash:** `{computed}`")
                        verified = computed == stored_hash
                    else:
                        # Try to verify from stored copy
                        file_bytes = get_evidence_bytes(ev.file_url)
                        if file_bytes:
                            computed = compute_file_hash(file_bytes)
                            st.write(f"**Computed Hash:** `{computed}`")
                            verified = computed == stored_hash
                        else:
                            st.warning("File not accessible from storage. Upload the file manually to verify.")
                            verified = None

                    if verified is True:
                        st.success("INTEGRITY VERIFIED — File has not been tampered with.")
                    elif verified is False:
                        st.error("INTEGRITY FAILED — Hash mismatch! File may have been modified.")

                    # Log the verification
                    log = EvidenceAccessLog(
                        evidence_id=ev.id,
                        accessed_by=current_user_id,
                        action="verify",
                        ip_address="audit_portal",
                        hash_at_access=stored_hash,
                        hash_verified=verified,
                        notes=f"Integrity check by {current_role} #{current_user_id}",
                    )
                    db.add(log)
                    db.commit()

        else:  # Bulk verify
            if st.button("Run Bulk Integrity Check", key="bulk_verify"):
                evidences = db.query(Evidence).filter_by(is_deleted=False).all()
                results = []
                verified_count = 0
                failed_count = 0
                skip_count = 0
                progress = st.progress(0)

                for i, ev in enumerate(evidences):
                    progress.progress((i + 1) / len(evidences))
                    file_bytes = get_evidence_bytes(ev.file_url)
                    if file_bytes:
                        computed = compute_file_hash(file_bytes)
                        verified = computed == ev.file_hash
                        if verified:
                            verified_count += 1
                        else:
                            failed_count += 1
                        # Log
                        log = EvidenceAccessLog(
                            evidence_id=ev.id,
                            accessed_by=current_user_id,
                            action="verify",
                            ip_address="bulk_audit",
                            hash_at_access=ev.file_hash,
                            hash_verified=verified,
                            notes="Bulk integrity check",
                        )
                        db.add(log)
                    else:
                        verified = None
                        skip_count += 1

                    results.append({
                        "Evidence ID": ev.id,
                        "File": ev.file_name,
                        "Stored Hash": ev.file_hash[:16] + "...",
                        "Status": "PASS" if verified is True else ("FAIL" if verified is False else "SKIPPED"),
                    })

                db.commit()
                progress.empty()

                import pandas as pd
                df_bulk = pd.DataFrame(results)
                st.dataframe(df_bulk, use_container_width=True, hide_index=True)

                col_r1, col_r2, col_r3 = st.columns(3)
                col_r1.metric("Verified", verified_count, delta="PASS")
                col_r2.metric("Failed", failed_count, delta="FAIL" if failed_count else None, delta_color="inverse")
                col_r3.metric("Skipped", skip_count)

                if failed_count > 0:
                    st.error(f"{failed_count} file(s) FAILED integrity check! Investigate immediately.")
                elif verified_count > 0:
                    st.success(f"All {verified_count} accessible files passed integrity check.")
    finally:
        db.close()
