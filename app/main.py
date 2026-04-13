"""
Traffic Violation Detection + Evidence Audit System
Main Streamlit entry point — Login page + role-based navigation.
"""
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config (must be FIRST Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Traffic Violation System",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB init on first run ──────────────────────────────────────────────────────
from utils.database import init_db, get_db
from utils.auth import authenticate_user, login_user, logout_user, is_logged_in
from utils.models import User, Vehicle
from utils.helpers import status_badge

init_db()

# ── Start background scheduler (once per process) ────────────────────────────
if "scheduler_started" not in st.session_state:
    try:
        from background.scheduler import start_scheduler
        start_scheduler()
        st.session_state["scheduler_started"] = True
    except Exception as e:
        st.session_state["scheduler_started"] = False


# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { background: #1a1a2e; }
    [data-testid="stSidebar"] * { color: #e0e0e0 !important; }
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem; border-radius: 12px; margin-bottom: 1.5rem;
        text-align: center; color: white;
    }
    .role-card {
        background: #f8f9fa; border-left: 4px solid #0f3460;
        padding: 1rem; border-radius: 8px; margin: 0.5rem 0;
    }
    .stat-card {
        background: white; border-radius: 10px; padding: 1.2rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center;
    }
    .stButton > button {
        background: #0f3460; color: white; border: none;
        border-radius: 6px; font-weight: 600;
    }
    .stButton > button:hover { background: #e94560; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🚦 Traffic System")
    st.markdown("---")

    if is_logged_in(st):
        role = st.session_state.get("user_role", "")
        name = st.session_state.get("user_name", "")
        st.markdown(f"**{name}**")
        st.markdown(f"Role: `{role.upper()}`")
        st.markdown("---")

        role_pages = {
            "admin":    ["Admin Dashboard", "Audit Logs"],
            "officer":  ["Officer Portal", "Audit Logs"],
            "citizen":  ["Citizen Portal"],
            "reviewer": ["Reviewer Portal", "Audit Logs"],
            "auditor":  ["Audit Logs"],
        }
        pages = role_pages.get(role, [])
        for page in pages:
            st.page_link(f"pages/{page.replace(' ', '_')}.py", label=page)

        st.markdown("---")
        if st.button("Logout", use_container_width=True):
            logout_user(st)
            st.rerun()
    else:
        st.info("Please log in.")


# ── Main Content ──────────────────────────────────────────────────────────────
if is_logged_in(st):
    role = st.session_state.get("user_role", "")
    name = st.session_state.get("user_name", "")

    st.markdown(f"""
    <div class='main-header'>
        <h1>🚦 Traffic Violation Detection System</h1>
        <p>Welcome back, <b>{name}</b> &nbsp;|&nbsp; Role: <b>{role.upper()}</b></p>
    </div>
    """, unsafe_allow_html=True)

    # Quick stats
    db = get_db()
    try:
        from utils.models import Violation, Challan, Appeal
        from sqlalchemy import func

        total_violations = db.query(func.count(Violation.id)).scalar()
        total_challans   = db.query(func.count(Challan.id)).scalar()
        paid_challans    = db.query(func.count(Challan.id)).filter(Challan.status == "paid").scalar()
        pending_appeals  = db.query(func.count(Appeal.id)).filter(Appeal.status.in_(["pending", "under_review"])).scalar()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Total Violations", total_violations)
        with c2:
            st.metric("Challans Issued", total_challans)
        with c3:
            st.metric("Challans Paid", paid_challans)
        with c4:
            st.metric("Pending Appeals", pending_appeals)

        st.markdown("---")

        # Role-specific navigation hints
        hints = {
            "admin":    "Use the **Admin Dashboard** to manage rules, view analytics, and manage accounts.",
            "officer":  "Use the **Officer Portal** to record violations and upload evidence.",
            "citizen":  "Use the **Citizen Portal** to view your challans, pay fines, or raise appeals.",
            "reviewer": "Use the **Reviewer Portal** to review pending appeals and deliver decisions.",
            "auditor":  "Use the **Audit Logs** page to inspect evidence access history and challan trail.",
        }
        st.info(hints.get(role, "Select a page from the sidebar."))

        # Recent violations table
        if role in ("admin", "officer", "auditor"):
            st.subheader("Recent Violations")
            recent = (
                db.query(Violation)
                .order_by(Violation.created_at.desc())
                .limit(8)
                .all()
            )
            if recent:
                import pandas as pd
                rows = []
                for v in recent:
                    rows.append({
                        "ID": v.id,
                        "Plate": v.vehicle.plate_number if v.vehicle else "N/A",
                        "Type": v.violation_type.replace("_", " ").title(),
                        "Location": v.location or "N/A",
                        "Status": v.status.replace("_", " ").title(),
                        "Date": v.created_at.strftime("%d %b %Y") if v.created_at else "N/A",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No violations recorded yet.")

    except Exception as e:
        st.error(f"Error loading dashboard: {e}")
    finally:
        db.close()

else:
    # ── Login Form ────────────────────────────────────────────────────────────
    st.markdown("""
    <div class='main-header'>
        <h1>🚦 Traffic Violation Detection</h1>
        <h3>Evidence Audit System</h3>
        <p>Secure | Transparent | Tamper-Evident</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.subheader("Sign In")
        with st.form("login_form"):
            email = st.text_input("Email Address", placeholder="your@email.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("Please enter email and password.")
            else:
                db = get_db()
                try:
                    user = authenticate_user(db, email.strip().lower(), password)
                    if user:
                        login_user(st, user)
                        st.success(f"Welcome, {user.name}!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials. Please try again.")
                finally:
                    db.close()

        st.markdown("---")
        st.markdown("**Demo Accounts:**")
        demo_creds = [
            ("Admin",    "admin@traffic.gov",    "Admin@123"),
            ("Officer",  "officer@traffic.gov",  "Officer@123"),
            ("Citizen",  "citizen@example.com",  "Citizen@123"),
            ("Reviewer", "reviewer@traffic.gov", "Reviewer@123"),
            ("Auditor",  "auditor@traffic.gov",  "Auditor@123"),
        ]
        for role, email, pwd in demo_creds:
            st.code(f"{role:10s}: {email}  /  {pwd}", language=None)

        st.markdown("---")
        st.caption("First time? Run `python database/seed_data.py` to create demo data.")

        # Register link
        with st.expander("New Citizen? Register here"):
            with st.form("register_form"):
                r_name  = st.text_input("Full Name")
                r_email = st.text_input("Email")
                r_phone = st.text_input("Phone")
                r_plate = st.text_input("Vehicle Plate Number", placeholder="MH12AB1234").upper().strip()
                r_model = st.text_input("Vehicle Model", placeholder="Optional")
                r_color = st.text_input("Vehicle Color", placeholder="Optional")
                r_type  = st.selectbox("Vehicle Type", ["car", "bike", "scooter", "truck", "bus", "other"])
                r_pwd   = st.text_input("Password", type="password")
                r_sub   = st.form_submit_button("Register")
            if r_sub:
                if not all([r_name, r_email, r_phone, r_plate, r_pwd]):
                    st.error("Name, email, phone, plate number and password are required.")
                elif len(r_pwd) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    from utils.auth import hash_password
                    db = get_db()
                    try:
                        existing = db.query(User).filter_by(email=r_email.lower()).first()
                        existing_vehicle = db.query(Vehicle).filter_by(plate_number=r_plate).first()
                        if existing:
                            st.error("Email already registered.")
                        elif existing_vehicle and existing_vehicle.owner_id:
                            st.error("This vehicle plate is already linked to another citizen account.")
                        else:
                            new_user = User(
                                name=r_name,
                                email=r_email.lower(),
                                phone=r_phone,
                                password_hash=hash_password(r_pwd),
                                role="citizen",
                            )
                            db.add(new_user)
                            db.flush()

                            if existing_vehicle:
                                existing_vehicle.owner_id = new_user.id
                                existing_vehicle.model = existing_vehicle.model or (r_model.strip() if r_model else None)
                                existing_vehicle.color = existing_vehicle.color or (r_color.strip() if r_color else None)
                                existing_vehicle.vehicle_type = existing_vehicle.vehicle_type or r_type
                            else:
                                db.add(Vehicle(
                                    plate_number=r_plate,
                                    owner_id=new_user.id,
                                    model=r_model.strip() if r_model else None,
                                    color=r_color.strip() if r_color else None,
                                    vehicle_type=r_type,
                                ))

                            db.commit()
                            st.success("Registered successfully. Officers can now issue challans against your registered vehicle, and you will be able to pay or appeal them after login.")
                    finally:
                        db.close()
