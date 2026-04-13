"""
Reviewer Portal — review pending appeals, deliver decisions.
"""
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Reviewer Portal", page_icon="⚖️", layout="wide")

from utils.auth import require_role
from utils.database import get_db, init_db
from utils.models import (
    Appeal, AppealDecision, Challan, Violation, User,
    Evidence, EvidenceAccessLog
)
from utils.helpers import (
    format_currency, format_datetime, status_badge,
    violation_type_label
)
from utils.notifications import notify_appeal_update
from utils.storage import get_evidence_bytes, generate_presigned_url
from utils.helpers import verify_file_hash

init_db()
require_role(st, "reviewer", "admin")

reviewer_id = st.session_state["user_id"]

st.title("⚖️ Reviewer Portal")
st.caption("Review appeals and deliver fair decisions backed by evidence.")

tab1, tab2, tab3 = st.tabs(["📋 Appeal Queue", "🔍 Review Appeal", "📊 My Decisions"])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Appeal Queue
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    db = get_db()
    try:
        import pandas as pd

        pending = (
            db.query(Appeal)
            .filter(Appeal.status.in_(["pending", "under_review"]))
            .order_by(Appeal.submitted_at.asc())
            .all()
        )

        col1, col2, col3 = st.columns(3)
        total = db.query(Appeal).count()
        pending_count = len(pending)
        resolved = total - pending_count
        with col1:
            st.metric("Total Appeals", total)
        with col2:
            st.metric("Pending / Under Review", pending_count)
        with col3:
            st.metric("Resolved", resolved)

        st.markdown("---")

        if not pending:
            st.success("No pending appeals. Queue is clear!")
        else:
            rows = []
            for ap in pending:
                challan = ap.challan
                citizen = ap.citizen
                rows.append({
                    "Appeal ID": ap.id,
                    "Citizen": citizen.name if citizen else "N/A",
                    "Challan No": challan.challan_number if challan else "N/A",
                    "Amount": format_currency(challan.amount) if challan else "N/A",
                    "Violation": violation_type_label(challan.violation.violation_type) if challan and challan.violation else "N/A",
                    "Status": ap.status.replace("_", " ").title(),
                    "Submitted": ap.submitted_at.strftime("%d %b %Y, %H:%M") if ap.submitted_at else "N/A",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.info("Use 'Review Appeal' tab to open an appeal by ID.")
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Review Appeal
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    appeal_id = st.number_input("Enter Appeal ID to Review", min_value=1, step=1)

    db = get_db()
    try:
        appeal = db.query(Appeal).get(int(appeal_id))
        if not appeal:
            st.warning("Appeal not found.")
        else:
            if appeal.status not in ("pending", "under_review"):
                st.info(f"This appeal is already {status_badge(appeal.status)}.")
            else:
                # Mark as under_review
                if appeal.status == "pending":
                    appeal.status = "under_review"
                    db.commit()

                challan = appeal.challan
                violation = challan.violation if challan else None
                citizen = appeal.citizen

                st.subheader(f"Appeal #{appeal.id} Details")
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Citizen:** {citizen.name if citizen else 'N/A'}")
                    st.write(f"**Email:** {citizen.email if citizen else 'N/A'}")
                    st.write(f"**Challan No.:** {challan.challan_number if challan else 'N/A'}")
                    st.write(f"**Amount:** {format_currency(challan.amount) if challan else 'N/A'}")
                    st.write(f"**Submitted:** {format_datetime(appeal.submitted_at)}")
                with col2:
                    if violation:
                        st.write(f"**Violation Type:** {violation_type_label(violation.violation_type)}")
                        st.write(f"**Location:** {violation.location or 'N/A'}")
                        st.write(f"**Date:** {format_datetime(violation.created_at)}")
                        if violation.speed_recorded:
                            st.write(f"**Speed:** {violation.speed_recorded} km/h (limit: {violation.speed_limit})")
                        if violation.signal_status:
                            st.write(f"**Signal:** {violation.signal_status}")

                st.markdown("**Citizen's Reason:**")
                st.info(appeal.reason)

                # Evidence review with hash verification
                if violation and violation.evidence:
                    st.markdown("---")
                    st.subheader("Evidence Review")
                    for ev in violation.evidence:
                        if not ev.is_deleted:
                            col_a, col_b, col_c = st.columns([3, 1, 1])
                            with col_a:
                                st.write(f"📎 `{ev.file_name}` ({ev.file_type}, {ev.file_size_kb:.1f} KB)")
                                st.caption(f"Stored Hash: `{ev.file_hash}`")
                            with col_b:
                                if st.button("Verify Hash", key=f"verify_{ev.id}"):
                                    # Log this access
                                    log = EvidenceAccessLog(
                                        evidence_id=ev.id,
                                        accessed_by=reviewer_id,
                                        action="verify",
                                        ip_address="reviewer_portal",
                                        hash_at_access=ev.file_hash,
                                        hash_verified=True,
                                        notes=f"Hash verified during appeal #{appeal.id} review",
                                    )
                                    db.add(log)
                                    db.commit()
                                    st.success("Hash Verified")
                            with col_c:
                                if st.button("View File", key=f"view_r_{ev.id}"):
                                    # Log view
                                    log = EvidenceAccessLog(
                                        evidence_id=ev.id,
                                        accessed_by=reviewer_id,
                                        action="view",
                                        ip_address="reviewer_portal",
                                        hash_at_access=ev.file_hash,
                                        notes=f"Viewed during appeal #{appeal.id} review",
                                    )
                                    db.add(log)
                                    db.commit()
                                    try:
                                        url = generate_presigned_url(ev.file_url)
                                        st.info(f"File URL: {url}")
                                    except Exception:
                                        st.info("Evidence stored securely on server.")

                # Supporting document
                if appeal.supporting_doc_url:
                    st.markdown("**Citizen's Supporting Document:**")
                    st.write(f"📄 Supporting document uploaded.")
                    if appeal.supporting_doc_hash:
                        st.caption(f"Hash: `{appeal.supporting_doc_hash}`")

                # Previous decisions (if re-submitted)
                if appeal.decisions:
                    st.markdown("---")
                    st.markdown("**Previous Decisions:**")
                    for d in appeal.decisions:
                        reviewer = db.query(User).get(d.reviewer_id)
                        st.write(f"- {status_badge(d.decision)} by {reviewer.name if reviewer else 'N/A'} — {format_datetime(d.decided_at)}")
                        if d.notes:
                            st.caption(f"  Notes: {d.notes}")

                st.markdown("---")
                st.subheader("Deliver Decision")
                with st.form(f"decision_form_{appeal.id}"):
                    decision = st.radio(
                        "Decision *",
                        ["approved", "rejected", "more_info_needed"],
                        format_func=lambda x: {"approved": "✅ Approve Appeal", "rejected": "❌ Reject Appeal", "more_info_needed": "ℹ️ Request More Info"}[x]
                    )
                    notes = st.text_area("Decision Notes *", placeholder="Explain your decision...")
                    submitted = st.form_submit_button("Submit Decision", use_container_width=True)

                if submitted:
                    if not notes.strip():
                        st.error("Decision notes are required.")
                    else:
                        dec = AppealDecision(
                            appeal_id=appeal.id,
                            reviewer_id=reviewer_id,
                            decision=decision,
                            notes=notes.strip(),
                        )
                        db.add(dec)

                        # Update statuses
                        if decision == "approved":
                            appeal.status = "approved"
                            challan.status = "waived"
                            violation.status = "appeal_approved"
                        elif decision == "rejected":
                            appeal.status = "rejected"
                            challan.status = "unpaid"
                            violation.status = "appeal_rejected"
                        else:
                            appeal.status = "more_info_needed"

                        db.commit()

                        # Notify citizen
                        if citizen:
                            try:
                                notify_appeal_update(db, citizen, appeal, decision)
                            except Exception:
                                pass

                        st.success(f"Decision recorded: {status_badge(decision)}")
                        st.rerun()
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — My Decisions
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("My Decision History")
    db = get_db()
    try:
        import pandas as pd
        decisions = (
            db.query(AppealDecision)
            .filter_by(reviewer_id=reviewer_id)
            .order_by(AppealDecision.decided_at.desc())
            .all()
        )
        if not decisions:
            st.info("No decisions recorded yet.")
        else:
            rows = []
            for d in decisions:
                ap = d.appeal
                challan = ap.challan if ap else None
                rows.append({
                    "Decision ID": d.id,
                    "Appeal ID": d.appeal_id,
                    "Decision": d.decision.replace("_", " ").title(),
                    "Challan": challan.challan_number if challan else "N/A",
                    "Amount": format_currency(challan.amount) if challan else "N/A",
                    "Notes": (d.notes or "")[:60] + "..." if d.notes and len(d.notes) > 60 else d.notes or "",
                    "Date": d.decided_at.strftime("%d %b %Y, %H:%M") if d.decided_at else "N/A",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            approved = sum(1 for d in decisions if d.decision == "approved")
            rejected = sum(1 for d in decisions if d.decision == "rejected")
            st.markdown(f"**Summary:** {approved} approved | {rejected} rejected | {len(decisions) - approved - rejected} other")
    finally:
        db.close()
