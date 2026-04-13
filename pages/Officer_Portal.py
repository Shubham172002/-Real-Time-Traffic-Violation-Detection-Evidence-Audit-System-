"""
Officer Portal — record violations, upload photo/video evidence, issue challans.
"""
import streamlit as st
from datetime import datetime, timedelta
from pathlib import Path

st.set_page_config(page_title="Officer Portal", page_icon="👮", layout="wide")

from utils.auth import require_role
from utils.database import get_db, init_db
from utils.models import (
    Violation, Vehicle, User, Evidence, EvidenceAccessLog,
    Challan, ViolationRule
)
from utils.helpers import (
    generate_challan_number, format_currency, format_datetime,
    status_badge, violation_type_label, compute_file_hash
)
from utils.storage import (
    upload_evidence, get_file_category, validate_file_size,
    get_video_stream_url, generate_presigned_url,
    VIDEO_EXTENSIONS, IMAGE_EXTENSIONS
)
from utils.detection import evaluate_violation, load_fine_rules
from utils.notifications import notify_challan_issued

init_db()
require_role(st, "officer", "admin")

officer_id = st.session_state["user_id"]

st.title("👮 Officer Portal")
st.caption("Record violations, upload photo/video evidence, issue challans.")

tab1, tab2, tab3 = st.tabs(["📋 My Violations", "➕ New Violation", "🔍 Search Vehicle"])


# ─────────────────────────────────────────────────────────────────────────────
def render_evidence_viewer(ev, db, current_user_id, key_prefix="off"):
    """Render an evidence card with photo/video viewer + hash info."""
    ext = Path(ev.file_name).suffix.lower()
    cat = get_file_category(ev.file_name)

    with st.container():
        col_info, col_action = st.columns([4, 1])
        with col_info:
            icon = "🎥" if cat == "video" else ("📷" if cat == "photo" else "📄")
            st.markdown(
                f"{icon} **{Path(ev.file_name).name}** &nbsp; "
                f"`{cat}` &nbsp; `{ev.file_size_kb:.1f} KB`"
            )
            st.caption(f"SHA-256: `{ev.file_hash}`")
            st.caption(f"Uploaded: {format_datetime(ev.created_at)}")

        with col_action:
            view_key = f"{key_prefix}_view_{ev.id}"
            if st.button("View", key=view_key):
                st.session_state[f"show_ev_{ev.id}"] = True
                # Log access
                log = EvidenceAccessLog(
                    evidence_id=ev.id,
                    accessed_by=current_user_id,
                    action="view",
                    ip_address="officer_portal",
                    hash_at_access=ev.file_hash,
                    hash_verified=True,
                    notes=f"Viewed by officer #{current_user_id}",
                )
                db.add(log)
                db.commit()

        # Show media when "View" is clicked
        if st.session_state.get(f"show_ev_{ev.id}", False):
            stream_url = get_video_stream_url(ev.file_url) if cat == "video" else None
            local_path = Path(ev.file_url) if not ev.file_url.startswith("s3://") else None

            if cat == "video":
                st.markdown("**Video Evidence:**")
                if stream_url and local_path and local_path.exists():
                    st.video(str(local_path))
                elif stream_url:
                    st.markdown(
                        f'<video controls width="100%" style="border-radius:8px">'
                        f'<source src="{stream_url}"></video>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.warning("Video file not accessible. Check storage configuration.")
            elif cat == "photo":
                st.markdown("**Photo Evidence:**")
                if local_path and local_path.exists():
                    st.image(str(local_path), use_container_width=True)
                else:
                    try:
                        url = generate_presigned_url(ev.file_url)
                        st.image(url, use_container_width=True)
                    except Exception:
                        st.info("Image stored securely. Configure S3 to view inline.")
            else:
                st.info("Document stored. Use audit portal to verify hash.")

            if st.button("Hide", key=f"{key_prefix}_hide_{ev.id}"):
                st.session_state[f"show_ev_{ev.id}"] = False
                st.rerun()

        st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — My Violations
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    db = get_db()
    try:
        violations = (
            db.query(Violation)
            .filter(Violation.officer_id == officer_id)
            .order_by(Violation.created_at.desc())
            .all()
        )

        if not violations:
            st.info("No violations recorded yet. Use the 'New Violation' tab to create one.")
        else:
            import pandas as pd
            rows = []
            for v in violations:
                videos = sum(1 for e in v.evidence if get_file_category(e.file_name) == "video")
                photos = sum(1 for e in v.evidence if get_file_category(e.file_name) == "photo")
                rows.append({
                    "ID": v.id,
                    "Plate": v.vehicle.plate_number if v.vehicle else "N/A",
                    "Type": violation_type_label(v.violation_type),
                    "Location": (v.location or "N/A")[:35],
                    "Status": v.status.replace("_", " ").title(),
                    "Photos": photos,
                    "Videos": videos,
                    "Challan": v.challan.challan_number if v.challan else "—",
                    "Date": v.created_at.strftime("%d %b %Y, %H:%M") if v.created_at else "N/A",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("Upload Evidence / Issue Challan")
            viol_id = st.number_input("Enter Violation ID", min_value=1, step=1, key="viol_id_tab1")

            selected_v = db.query(Violation).filter_by(id=int(viol_id), officer_id=officer_id).first()
            if selected_v:
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Plate:** {selected_v.vehicle.plate_number if selected_v.vehicle else 'N/A'}")
                    st.write(f"**Type:** {violation_type_label(selected_v.violation_type)}")
                    st.write(f"**Status:** {status_badge(selected_v.status)}")
                with c2:
                    st.write(f"**Location:** {selected_v.location}")
                    st.write(f"**Date:** {format_datetime(selected_v.created_at)}")
                    st.write(f"**Evidence files:** {len(selected_v.evidence)}")

                # ── Evidence Upload ───────────────────────────────────────────
                st.subheader("Upload Evidence")

                col_up1, col_up2 = st.columns(2)
                with col_up1:
                    st.markdown("**Photo Evidence**")
                    photo_file = st.file_uploader(
                        "Upload photo (JPG/PNG)",
                        type=["jpg", "jpeg", "png", "webp"],
                        key="photo_upload",
                        help="Max 10 MB. Supports JPG, PNG, WebP."
                    )
                    if photo_file:
                        st.image(photo_file, caption="Preview", use_container_width=True)
                        size_mb = len(photo_file.getvalue()) / (1024 * 1024)
                        st.caption(f"Size: {size_mb:.2f} MB")

                with col_up2:
                    st.markdown("**Video Evidence**")
                    video_file = st.file_uploader(
                        "Upload video (MP4/AVI/MOV)",
                        type=["mp4", "avi", "mov", "mkv", "webm"],
                        key="video_upload",
                        help="Max 200 MB. Supports MP4, AVI, MOV, MKV, WebM."
                    )
                    if video_file:
                        st.video(video_file)
                        size_mb = len(video_file.getvalue()) / (1024 * 1024)
                        st.caption(f"Size: {size_mb:.2f} MB")
                        if size_mb > 200:
                            st.error("Video exceeds 200 MB limit.")

                # Also allow document
                doc_file = st.file_uploader(
                    "Supporting Document (PDF) — optional",
                    type=["pdf"],
                    key="doc_upload",
                )

                files_to_upload = []
                if photo_file:
                    files_to_upload.append(photo_file)
                if video_file:
                    files_to_upload.append(video_file)
                if doc_file:
                    files_to_upload.append(doc_file)

                if files_to_upload and st.button("Upload All Evidence", key="upload_btn"):
                    upload_results = []
                    for f in files_to_upload:
                        f.seek(0)
                        file_bytes = f.read()
                        size_err = validate_file_size(file_bytes, f.name)
                        if size_err:
                            st.error(f"{f.name}: {size_err}")
                            continue
                        file_hash = compute_file_hash(file_bytes)
                        cat       = get_file_category(f.name)
                        try:
                            with st.spinner(f"Uploading {f.name} ({cat})..."):
                                file_url, unique_name = upload_evidence(
                                    file_bytes, f.name, selected_v.id
                                )
                            ev = Evidence(
                                violation_id=selected_v.id,
                                file_name=unique_name,
                                file_url=file_url,
                                file_hash=file_hash,
                                file_type=cat,
                                file_size_kb=round(len(file_bytes) / 1024, 2),
                                uploaded_by=officer_id,
                            )
                            db.add(ev)
                            db.flush()
                            log = EvidenceAccessLog(
                                evidence_id=ev.id,
                                accessed_by=officer_id,
                                action="upload",
                                ip_address="officer_portal",
                                hash_at_access=file_hash,
                                hash_verified=True,
                                notes=f"Uploaded {cat} evidence by officer #{officer_id}",
                            )
                            db.add(log)
                            upload_results.append((f.name, cat, file_hash))
                        except Exception as e:
                            st.error(f"Upload failed for {f.name}: {e}")

                    if upload_results:
                        db.commit()
                        st.success(f"Uploaded {len(upload_results)} file(s) successfully!")
                        for name, cat, fhash in upload_results:
                            st.write(f"  - `{name}` ({cat}) | Hash: `{fhash[:20]}...`")
                        st.rerun()

                # ── View Existing Evidence ─────────────────────────────────────
                if selected_v.evidence:
                    st.subheader(f"Stored Evidence ({len(selected_v.evidence)} file(s))")
                    for ev in selected_v.evidence:
                        if not ev.is_deleted:
                            render_evidence_viewer(ev, db, officer_id, key_prefix="t1")

                # ── Issue Challan ─────────────────────────────────────────────
                if selected_v.status == "pending" and not selected_v.challan:
                    st.subheader("Issue Challan")
                    fine_rules   = load_fine_rules(db)
                    default_amt  = fine_rules.get(selected_v.violation_type, 500.0)
                    amount       = st.number_input("Fine Amount (Rs.)", value=default_amt, min_value=100.0, step=50.0)
                    due_days     = st.slider("Due in (days)", 7, 60, 30)
                    if st.button("Issue Challan", key="issue_challan"):
                        challan = Challan(
                            violation_id=selected_v.id,
                            challan_number=generate_challan_number(),
                            amount=amount,
                            status="unpaid",
                            due_date=datetime.utcnow() + timedelta(days=due_days),
                        )
                        db.add(challan)
                        selected_v.status = "challan_issued"
                        db.commit()
                        if selected_v.vehicle and selected_v.vehicle.owner:
                            try:
                                notify_challan_issued(db, selected_v.vehicle.owner, challan)
                            except Exception:
                                pass
                        st.success(f"Challan {challan.challan_number} issued for Rs.{amount:,.0f}!")
                        st.rerun()
                elif selected_v.challan:
                    st.info(f"Challan already issued: **{selected_v.challan.challan_number}** — {status_badge(selected_v.challan.status)}")
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — New Violation
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Record New Traffic Violation")
    with st.form("new_violation_form"):
        col1, col2 = st.columns(2)
        with col1:
            plate            = st.text_input("Vehicle Plate Number *", placeholder="MH12AB1234").upper()
            owner_name       = st.text_input("Owner Name (if known)", placeholder="Optional")
            vtype            = st.selectbox(
                "Violation Type *",
                ["speeding", "red_light", "wrong_lane", "no_helmet", "no_seatbelt", "illegal_parking", "other"],
                format_func=violation_type_label,
            )
            location         = st.text_input("Location *", placeholder="NH-48, Pune Bypass Km 12")
        with col2:
            speed_recorded   = st.number_input("Speed Recorded (km/h)", min_value=0.0, value=0.0, step=1.0)
            speed_limit      = st.number_input("Speed Limit (km/h)", min_value=0.0, value=60.0, step=5.0)
            signal_status    = st.selectbox("Signal Status", ["N/A", "RED", "GREEN", "YELLOW"])
            crossing_detected = st.checkbox("Crossing Detected at Signal")
            detection_method = st.selectbox("Detection Method", ["manual", "automatic"])

        lat         = st.number_input("Latitude", value=0.0, format="%.6f")
        lon         = st.number_input("Longitude", value=0.0, format="%.6f")
        description = st.text_area("Description / Notes")
        submitted   = st.form_submit_button("Record Violation", use_container_width=True)

    if submitted:
        if not plate or not location:
            st.error("Plate number and location are required.")
        else:
            db = get_db()
            try:
                vehicle = db.query(Vehicle).filter_by(plate_number=plate).first()
                if not vehicle:
                    vehicle = Vehicle(plate_number=plate, model="Unknown")
                    if owner_name:
                        owner = db.query(User).filter(
                            User.name.ilike(f"%{owner_name}%"), User.role == "citizen"
                        ).first()
                        if owner:
                            vehicle.owner_id = owner.id
                    db.add(vehicle)
                    db.flush()

                fine_rules = load_fine_rules(db)
                result     = evaluate_violation(
                    violation_type=vtype,
                    speed_recorded=speed_recorded if speed_recorded > 0 else None,
                    speed_limit=speed_limit if speed_limit > 0 else None,
                    signal_status=signal_status if signal_status != "N/A" else None,
                    crossing_detected=crossing_detected,
                    fine_rules=fine_rules,
                    evidence_bytes=None,
                    stored_hash=None,
                )

                violation = Violation(
                    vehicle_id=vehicle.id,
                    officer_id=officer_id,
                    violation_type=vtype,
                    location=location,
                    latitude=lat if lat != 0.0 else None,
                    longitude=lon if lon != 0.0 else None,
                    speed_recorded=speed_recorded if speed_recorded > 0 else None,
                    speed_limit=speed_limit if speed_limit > 0 else None,
                    signal_status=signal_status if signal_status != "N/A" else None,
                    description=description or result.notes,
                    status="pending",
                    detection_method=detection_method,
                )
                db.add(violation)
                db.commit()

                st.success(f"Violation #{violation.id} recorded!")
                st.info(
                    f"**Detection:** {result.violation_status.upper()} | "
                    f"Suggested fine: Rs.{result.challan_amount:,.0f}"
                )
                if result.notes:
                    st.caption(result.notes)
                st.info("Go to 'My Violations' tab to upload evidence and issue a challan.")
            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Search Vehicle
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Search Vehicle Violation History")
    search_plate = st.text_input("Enter Plate Number", placeholder="MH12AB1234").upper()
    if st.button("Search", key="search_vehicle"):
        if not search_plate:
            st.warning("Enter a plate number.")
        else:
            db = get_db()
            try:
                vehicle = db.query(Vehicle).filter_by(plate_number=search_plate).first()
                if not vehicle:
                    st.warning("Vehicle not found in the system.")
                else:
                    st.write(f"**Vehicle:** {vehicle.plate_number} | {vehicle.model} ({vehicle.color or 'N/A'})")
                    st.write(f"**Owner:** {vehicle.owner.name if vehicle.owner else 'Unknown'}")
                    viols = (
                        db.query(Violation)
                        .filter_by(vehicle_id=vehicle.id)
                        .order_by(Violation.created_at.desc())
                        .all()
                    )
                    st.write(f"**Total Violations:** {len(viols)}")
                    if len(viols) >= 3:
                        st.warning("Repeat offender — 3 or more violations on record!")

                    import pandas as pd
                    if viols:
                        rows = [{
                            "ID": v.id,
                            "Type": violation_type_label(v.violation_type),
                            "Location": (v.location or "N/A")[:35],
                            "Status": v.status.replace("_", " ").title(),
                            "Evidence": len(v.evidence),
                            "Date": v.created_at.strftime("%d %b %Y") if v.created_at else "N/A",
                            "Challan": v.challan.challan_number if v.challan else "—",
                        } for v in viols]
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            finally:
                db.close()
