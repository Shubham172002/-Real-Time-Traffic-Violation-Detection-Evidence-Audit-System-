"""
Admin Dashboard — analytics, hotspots, repeat offenders, rule management, user accounts.
"""
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Admin Dashboard", page_icon="📊", layout="wide")

from utils.auth import require_role
from utils.database import get_db, init_db
from utils.models import (
    Violation, Challan, Appeal, User, Vehicle,
    ViolationRule, Notification
)
from utils.helpers import (
    format_currency, format_datetime, status_badge,
    violation_type_label
)
from utils.auth import hash_password

init_db()
require_role(st, "admin")

admin_id = st.session_state["user_id"]

st.title("📊 Admin Dashboard")
st.caption("System-wide analytics, violation management, and configuration.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Analytics", "🗺️ Hotspots", "🔁 Repeat Offenders",
    "⚙️ Rules & Config", "👥 User Management"
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Analytics
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    db = get_db()
    try:
        import pandas as pd
        import plotly.express as px
        from sqlalchemy import func

        # Date filter
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            date_from = st.date_input("From Date", datetime.utcnow().date() - timedelta(days=90))
        with col_f2:
            date_to = st.date_input("To Date", datetime.utcnow().date())

        from_dt = datetime.combine(date_from, datetime.min.time())
        to_dt   = datetime.combine(date_to,   datetime.max.time())

        # KPI metrics
        total_v  = db.query(func.count(Violation.id)).filter(Violation.created_at.between(from_dt, to_dt)).scalar()
        total_c  = db.query(func.count(Challan.id)).filter(Challan.created_at.between(from_dt, to_dt)).scalar()
        total_paid = db.query(func.sum(Challan.amount)).filter(Challan.status == "paid", Challan.created_at.between(from_dt, to_dt)).scalar() or 0
        total_due  = db.query(func.sum(Challan.amount)).filter(Challan.status == "unpaid", Challan.created_at.between(from_dt, to_dt)).scalar() or 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Violations", total_v)
        k2.metric("Challans Issued", total_c)
        k3.metric("Revenue Collected", format_currency(total_paid))
        k4.metric("Pending Collections", format_currency(total_due))

        st.markdown("---")

        col_a, col_b = st.columns(2)

        # Violations by type
        with col_a:
            vtype_data = (
                db.query(Violation.violation_type, func.count(Violation.id).label("count"))
                .filter(Violation.created_at.between(from_dt, to_dt))
                .group_by(Violation.violation_type)
                .all()
            )
            if vtype_data:
                df_type = pd.DataFrame([{"Type": violation_type_label(r[0]), "Count": r[1]} for r in vtype_data])
                fig = px.pie(df_type, names="Type", values="Count", title="Violations by Type",
                             color_discrete_sequence=px.colors.qualitative.Set3)
                st.plotly_chart(fig, use_container_width=True)

        # Violations over time
        with col_b:
            vtime_data = (
                db.query(
                    func.date(Violation.created_at).label("date"),
                    func.count(Violation.id).label("count")
                )
                .filter(Violation.created_at.between(from_dt, to_dt))
                .group_by(func.date(Violation.created_at))
                .order_by(func.date(Violation.created_at))
                .all()
            )
            if vtime_data:
                df_time = pd.DataFrame([{"Date": str(r[0]), "Violations": r[1]} for r in vtime_data])
                fig2 = px.line(df_time, x="Date", y="Violations", title="Violations Over Time",
                               markers=True, line_shape="spline")
                st.plotly_chart(fig2, use_container_width=True)

        # Challan payment status distribution
        col_c, col_d = st.columns(2)
        with col_c:
            pay_data = (
                db.query(Challan.status, func.count(Challan.id).label("count"))
                .filter(Challan.created_at.between(from_dt, to_dt))
                .group_by(Challan.status)
                .all()
            )
            if pay_data:
                df_pay = pd.DataFrame([{"Status": r[0].replace("_", " ").title(), "Count": r[1]} for r in pay_data])
                fig3 = px.bar(df_pay, x="Status", y="Count", title="Challan Payment Status",
                              color="Status", color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig3, use_container_width=True)

        # Appeal outcomes
        with col_d:
            appeal_data = (
                db.query(Appeal.status, func.count(Appeal.id).label("count"))
                .group_by(Appeal.status)
                .all()
            )
            if appeal_data:
                df_ap = pd.DataFrame([{"Status": r[0].replace("_", " ").title(), "Count": r[1]} for r in appeal_data])
                fig4 = px.bar(df_ap, x="Status", y="Count", title="Appeal Outcomes",
                              color="Status", color_discrete_sequence=px.colors.qualitative.Safe)
                st.plotly_chart(fig4, use_container_width=True)

    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Hotspots
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Violation Hotspot Analysis")
    db = get_db()
    try:
        import pandas as pd
        import plotly.express as px
        from sqlalchemy import func

        days = st.slider("Analyse last N days", 7, 365, 30, key="hotspot_days")
        since = datetime.utcnow() - timedelta(days=days)

        hotspots = (
            db.query(Violation.location, func.count(Violation.id).label("count"))
            .filter(Violation.created_at >= since, Violation.location.isnot(None))
            .group_by(Violation.location)
            .order_by(func.count(Violation.id).desc())
            .limit(20)
            .all()
        )

        if not hotspots:
            st.info("No violation data for the selected period.")
        else:
            df_hot = pd.DataFrame([{"Location": r[0], "Violations": r[1]} for r in hotspots])
            fig = px.bar(
                df_hot, x="Violations", y="Location", orientation="h",
                title=f"Top Violation Hotspots (Last {days} Days)",
                color="Violations", color_continuous_scale="Reds"
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(df_hot, use_container_width=True, hide_index=True)

            # Hotspot by violation type
            hotspot_type = (
                db.query(Violation.location, Violation.violation_type, func.count(Violation.id).label("count"))
                .filter(Violation.created_at >= since)
                .group_by(Violation.location, Violation.violation_type)
                .order_by(func.count(Violation.id).desc())
                .limit(30)
                .all()
            )
            if hotspot_type:
                df_ht = pd.DataFrame([{
                    "Location": r[0] or "Unknown",
                    "Type": violation_type_label(r[1]),
                    "Count": r[2]
                } for r in hotspot_type])
                fig2 = px.bar(df_ht, x="Location", y="Count", color="Type",
                              title="Violation Types by Location", barmode="stack")
                fig2.update_xaxes(tickangle=45)
                st.plotly_chart(fig2, use_container_width=True)
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Repeat Offenders
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Repeat Offender Analysis")
    db = get_db()
    try:
        import pandas as pd
        import plotly.express as px
        from sqlalchemy import func

        min_violations = st.slider("Minimum violations to flag", 2, 10, 3, key="repeat_slider")

        repeat_vehicles = (
            db.query(Vehicle.plate_number, func.count(Violation.id).label("count"))
            .join(Violation, Vehicle.id == Violation.vehicle_id)
            .group_by(Vehicle.plate_number)
            .having(func.count(Violation.id) >= min_violations)
            .order_by(func.count(Violation.id).desc())
            .all()
        )

        if not repeat_vehicles:
            st.success(f"No vehicles with {min_violations}+ violations.")
        else:
            st.warning(f"Found {len(repeat_vehicles)} repeat offender vehicle(s).")
            rows = []
            for plate, count in repeat_vehicles:
                vehicle = db.query(Vehicle).filter_by(plate_number=plate).first()
                owner = vehicle.owner if vehicle else None
                rows.append({
                    "Plate Number": plate,
                    "Total Violations": count,
                    "Owner": owner.name if owner else "Unknown",
                    "Phone": owner.phone if owner else "N/A",
                    "Model": vehicle.model if vehicle else "N/A",
                })
            df_repeat = pd.DataFrame(rows)
            st.dataframe(df_repeat, use_container_width=True, hide_index=True)

            fig = px.bar(
                df_repeat, x="Plate Number", y="Total Violations",
                title="Repeat Offenders by Vehicle",
                color="Total Violations", color_continuous_scale="Oranges"
            )
            st.plotly_chart(fig, use_container_width=True)

            # Violation types breakdown for repeat offenders
            st.subheader("Violation Breakdown for Repeat Offenders")
            repeat_plates = [r[0] for r in repeat_vehicles]
            breakdown = (
                db.query(Violation.violation_type, func.count(Violation.id).label("count"))
                .join(Vehicle, Violation.vehicle_id == Vehicle.id)
                .filter(Vehicle.plate_number.in_(repeat_plates))
                .group_by(Violation.violation_type)
                .all()
            )
            if breakdown:
                df_bd = pd.DataFrame([{
                    "Type": violation_type_label(r[0]), "Count": r[1]
                } for r in breakdown])
                fig2 = px.pie(df_bd, names="Type", values="Count",
                              title="Violation Types Among Repeat Offenders")
                st.plotly_chart(fig2, use_container_width=True)
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — Rules & Config
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("Violation Rules & Fine Amounts")
    db = get_db()
    try:
        rules = db.query(ViolationRule).order_by(ViolationRule.violation_type).all()

        if rules:
            import pandas as pd
            for rule in rules:
                with st.expander(f"{violation_type_label(rule.violation_type)} — {format_currency(rule.fine_amount)}"):
                    with st.form(f"edit_rule_{rule.id}"):
                        new_amount = st.number_input("Fine Amount (₹)", value=rule.fine_amount, min_value=0.0, step=50.0)
                        new_desc = st.text_input("Description", value=rule.description or "")
                        new_active = st.checkbox("Active", value=rule.is_active)
                        if st.form_submit_button("Update Rule"):
                            rule.fine_amount = new_amount
                            rule.description = new_desc
                            rule.is_active = new_active
                            rule.updated_by = admin_id
                            rule.updated_at = datetime.utcnow()
                            db.commit()
                            st.success("Rule updated!")

        st.markdown("---")
        st.subheader("Add New Violation Rule")
        with st.form("add_rule"):
            new_type = st.text_input("Violation Type (snake_case)", placeholder="e.g. no_insurance")
            new_amount = st.number_input("Fine Amount (₹)", min_value=0.0, value=500.0, step=50.0)
            new_desc = st.text_area("Description")
            if st.form_submit_button("Add Rule"):
                if not new_type.strip():
                    st.error("Violation type is required.")
                elif db.query(ViolationRule).filter_by(violation_type=new_type.strip()).first():
                    st.error("Rule already exists.")
                else:
                    db.add(ViolationRule(
                        violation_type=new_type.strip(),
                        fine_amount=new_amount,
                        description=new_desc,
                        updated_by=admin_id,
                    ))
                    db.commit()
                    st.success("New rule added!")
                    st.rerun()
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — User Management
# ════════════════════════════════════════════════════════════════════════════════
with tab5:
    st.subheader("User Accounts")
    db = get_db()
    try:
        import pandas as pd
        from sqlalchemy import func

        role_filter = st.selectbox("Filter by Role", ["all", "admin", "officer", "citizen", "reviewer", "auditor"])

        query = db.query(User)
        if role_filter != "all":
            query = query.filter_by(role=role_filter)
        users = query.order_by(User.role, User.name).all()

        rows = [{
            "ID": u.id,
            "Name": u.name,
            "Email": u.email,
            "Phone": u.phone or "N/A",
            "Role": u.role.upper(),
            "Active": "Yes" if u.is_active else "No",
            "Joined": u.created_at.strftime("%d %b %Y") if u.created_at else "N/A",
        } for u in users]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("---")

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Create New User")
            with st.form("create_user"):
                u_name  = st.text_input("Full Name")
                u_email = st.text_input("Email")
                u_phone = st.text_input("Phone")
                u_role  = st.selectbox("Role", ["officer", "citizen", "reviewer", "auditor", "admin"])
                u_pwd   = st.text_input("Password", type="password")
                if st.form_submit_button("Create User"):
                    if not all([u_name, u_email, u_pwd]):
                        st.error("Name, email and password are required.")
                    elif db.query(User).filter_by(email=u_email.lower()).first():
                        st.error("Email already registered.")
                    else:
                        new_u = User(
                            name=u_name, email=u_email.lower(), phone=u_phone,
                            password_hash=hash_password(u_pwd), role=u_role
                        )
                        db.add(new_u)
                        db.commit()
                        st.success(f"User {u_name} created as {u_role}.")
                        st.rerun()

        with col_b:
            st.subheader("Deactivate / Activate User")
            user_id_toggle = st.number_input("User ID", min_value=1, step=1, key="toggle_user")
            toggle_user = db.query(User).get(int(user_id_toggle))
            if toggle_user:
                st.write(f"**{toggle_user.name}** ({toggle_user.role}) — {'Active' if toggle_user.is_active else 'Inactive'}")
                if toggle_user.id != admin_id:
                    if st.button("Toggle Active Status"):
                        toggle_user.is_active = not toggle_user.is_active
                        db.commit()
                        st.success(f"User {'activated' if toggle_user.is_active else 'deactivated'}.")
                        st.rerun()
                else:
                    st.warning("Cannot deactivate your own account.")
    finally:
        db.close()
