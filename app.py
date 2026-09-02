import os
import re
import smtplib
import sqlite3
import hashlib
import secrets
from io import BytesIO
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import pdfplumber
import streamlit as st
import plotly.express as px

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ------------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & DATABASE ARCHITECTURE
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Kenyan Enterprise Freight Audit & Reconciliation",
    layout="wide",
)

DB_FILE = "freight_audit_ledger.db"

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Audit Ledger Table (Company History)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            invoice_no TEXT,
            carrier TEXT,
            bol_ref TEXT,
            etims_cu_serial TEXT,
            total_overcharge REAL,
            audit_status TEXT,
            etims_valid INTEGER
        )
    """)
    
    # User Management & RBAC Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL,
            reset_token TEXT
        )
    """)
    
    # Seed Default Accounts if Empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("admin", hash_password("admin123"), "admin@company.co.ke", "admin"),
            ("finance", hash_password("finance123"), "finance@company.co.ke", "finance"),
            ("auditor", hash_password("auditor123"), "auditor@company.co.ke", "auditor")
        ]
        cursor.executemany("INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)", default_users)
        
    conn.commit()
    conn.close()

init_db()

def save_audit_record(df_results):
    conn = sqlite3.connect(DB_FILE)
    for _, row in df_results.iterrows():
        conn.execute(
            """
            INSERT INTO audit_ledger (invoice_no, carrier, bol_ref, etims_cu_serial, total_overcharge, audit_status, etims_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(row.get("Invoice_No", "N/A")),
                str(row.get("Carrier", "Unknown")),
                str(row.get("BoL_Ref", "N/A")),
                str(row.get("eTIMS_CU_Serial", "INVALID")),
                float(row.get("Total_Overcharge", 0.0)),
                str(row.get("Audit_Status", "FLAGGED")),
                1 if row.get("eTIMS_Valid", False) else 0,
            ),
        )
    conn.commit()
    conn.close()

# ------------------------------------------------------------------------------
# 2. AUTHENTICATION, RBAC & PASSWORD MANAGEMENT
# ------------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "role" not in st.session_state:
    st.session_state["role"] = ""
if "auth_view" not in st.session_state:
    st.session_state["auth_view"] = "login"

def verify_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ? AND password_hash = ?", (username, hash_password(password)))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_user_password(username, new_password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(new_password), username))
    conn.commit()
    conn.close()

if not st.session_state["authenticated"]:
    st.title("🔒 Enterprise Freight Audit Portal")
    
    if st.session_state["auth_view"] == "login":
        st.subheader("System Login")
        with st.form("login_form"):
            username_input = st.text_input("Username")
            password_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")

            if submit:
                user_role = verify_user(username_input, password_input)
                if user_role:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username_input
                    st.session_state["role"] = user_role
                    st.success(f"Welcome back, {username_input} ({user_role.upper()})!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        
        if st.button("Forgot Password?"):
            st.session_state["auth_view"] = "forgot"
            st.rerun()

    elif st.session_state["auth_view"] == "forgot":
        st.subheader("🔑 Password Reset Request")
        email_input = st.text_input("Enter your registered account email:")
        if st.button("Send Reset Token"):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users WHERE email = ?", (email_input,))
            user_found = cursor.fetchone()
            
            if user_found:
                token = secrets.token_hex(4).upper()
                cursor.execute("UPDATE users SET reset_token = ? WHERE email = ?", (token, email_input))
                conn.commit()
                st.info(f"SIMULATED EMAIL DISPATCH: Your password reset token is: **{token}**")
            else:
                st.error("Email address not found in system record.")
            conn.close()

        st.markdown("---")
        with st.form("reset_form"):
            token_input = st.text_input("Enter Reset Token")
            new_pass = st.text_input("Enter New Password", type="password")
            reset_submit = st.form_submit_button("Reset Password")
            if reset_submit:
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("SELECT username FROM users WHERE reset_token = ?", (token_input,))
                res = cursor.fetchone()
                if res:
                    cursor.execute("UPDATE users SET password_hash = ?, reset_token = NULL WHERE username = ?", (hash_password(new_pass), res[0]))
                    conn.commit()
                    st.success("Password updated successfully! Please login.")
                    st.session_state["auth_view"] = "login"
                    st.rerun()
                else:
                    st.error("Invalid or expired reset token.")
                conn.close()

        if st.button("Back to Login"):
            st.session_state["auth_view"] = "login"
            st.rerun()

    st.stop()

# SIDEBAR CONTROLS
st.sidebar.write(f"Logged in as: **{st.session_state['username'].upper()}**")
st.sidebar.caption(f"Role: **{st.session_state['role'].upper()}**")

if st.sidebar.button("Logout"):
    st.session_state["authenticated"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.rerun()

# ------------------------------------------------------------------------------
# 3. PDF ENGINE & DEBIT NOTE GENERATOR
# ------------------------------------------------------------------------------
def parse_pdf_invoice(file_obj):
    extracted_text = ""
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            extracted_text += (page.extract_text() or "") + "\n"

    inv_match = re.search(r"Invoice\s*#?\s*:?\s*([A-Za-z0-9-]+)", extracted_text)
    carrier_match = re.search(r"(Swara Express|Rift Transport|Siginon|Freight In Time)", extracted_text)
    bol_match = re.search(r"BoL\s*Ref\s*:?\s*([A-Za-z0-9-]+)", extracted_text)
    etims_match = re.search(r"(KRA[A-Za-z0-9]{8,15})", extracted_text)

    base_match = re.search(r"Base\s*Rate\s*:?\s*KES\s*([\d,]+\.?\d*)", extracted_text)
    fuel_match = re.search(r"Fuel\s*Surcharge\s*:?\s*KES\s*([\d,]+\.?\d*)", extracted_text)
    offload_match = re.search(r"Offloading\s*:?\s*KES\s*([\d,]+\.?\d*)", extracted_text)
    vat_match = re.search(r"VAT\s*\(16%\)\s*:?\s*KES\s*([\d,]+\.?\d*)", extracted_text)

    def clean_num(m):
        return float(m.group(1).replace(",", "")) if m else 0.0

    return {
        "Invoice_No": inv_match.group(1) if inv_match else file_obj.name,
        "Carrier": carrier_match.group(1) if carrier_match else "Unknown",
        "BoL_Ref": bol_match.group(1) if bol_match else "N/A",
        "eTIMS_CU_Serial": etims_match.group(1) if etims_match else "INVALID",
        "Billed_Base": clean_num(base_match),
        "Billed_Fuel": clean_num(fuel_match),
        "Billed_Offloading": clean_num(offload_match),
        "Billed_VAT": clean_num(vat_match),
    }

def generate_pdf_debit_note(row_data):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, "OFFICIAL DEBIT NOTE / AUDIT DISCREPANCY NOTICE")
    
    c.setFont("Helvetica", 10)
    c.drawString(50, 725, f"Carrier: {row_data.get('Carrier', 'N/A')}")
    c.drawString(50, 710, f"Target Invoice No: {row_data.get('Invoice_No', 'N/A')}")
    c.drawString(50, 695, f"BoL Reference: {row_data.get('BoL_Ref', 'N/A')}")
    c.drawString(50, 680, f"eTIMS Serial: {row_data.get('eTIMS_CU_Serial', 'N/A')}")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, 640, "Financial Variance Breakdown:")
    
    c.setFont("Helvetica", 10)
    b_base = row_data.get('Billed_Base', row_data.get('Billed_Base_Rate', 0.0))
    c_base = row_data.get('Contract_Base', 0.0)
    overcharge = row_data.get('Total_Overcharge', 0.0)
    
    c.drawString(70, 620, f"- Billed Base Rate: KES {b_base:,.2f}")
    c.drawString(70, 605, f"- Contract Base Rate: KES {c_base:,.2f}")
    c.drawString(70, 590, f"- Total Claimed Debit Overcharge: KES {overcharge:,.2f}")
    
    c.drawString(50, 540, "Action Required: Please issue a Credit Note matching contracted rate cards.")
    c.showPage()
    c.save()
    
    buffer.seek(0)
    return buffer

# ------------------------------------------------------------------------------
# 4. DASHBOARD INTERFACE & WORKFLOW
# ------------------------------------------------------------------------------
st.title("🚛 Kenyan Enterprise Freight Audit & Reconciliation")
st.caption("PDF Parsing | eTIMS Compliance | Persistent History | RBAC Security")

tabs = st.tabs([
    "📋 Active Audit Engine", 
    "📊 Carrier Scorecards & ROI", 
    "📜 Historical Audit Ledger", 
    "👤 User Profile",
    "⚙️ Integration Settings"
])

# ------------------------------------------------------------------------------
# TAB 1: ACTIVE AUDIT ENGINE
# ------------------------------------------------------------------------------
with tabs[0]:
    st.sidebar.header("📁 Upload Documents")
    pdf_files = st.sidebar.file_uploader(
        "1. Upload PDF Carrier Invoices", type=["pdf"], accept_multiple_files=True
    )
    contract_file = st.sidebar.file_uploader(
        "2. Upload Rate Card (CSV/Excel)", type=["csv", "xlsx"]
    )

    if pdf_files and contract_file:
        invoice_records = [parse_pdf_invoice(pdf) for pdf in pdf_files]
        df_inv = pd.DataFrame(invoice_records)

        if contract_file.name.endswith(".csv"):
            try:
                contract_file.seek(0)
                df_rates = pd.read_csv(contract_file, encoding='utf-8')
            except Exception:
                contract_file.seek(0)
                df_rates = pd.read_csv(contract_file, encoding='latin1', on_bad_lines='skip')
        else:
            contract_file.seek(0)
            df_rates = pd.read_excel(contract_file)

        column_mapping = {
            'Company_Name': 'Carrier',
            'Contract_Rate_KES': 'Contract_Base',
            'Billed_Rate_KES': 'Billed_Base'
        }
        df_rates = df_rates.rename(columns=column_mapping)

        df_merged = pd.merge(df_inv, df_rates, on="Carrier", how="left").fillna(0)

        c_base = df_merged["Contract_Base"] if "Contract_Base" in df_merged.columns else 0
        b_base = df_merged["Billed_Base"] if "Billed_Base" in df_merged.columns else 0
        df_merged["Base_Variance"] = np.maximum(0, b_base - c_base)

        b_fuel = df_merged["Billed_Fuel"] if "Billed_Fuel" in df_merged.columns else 0
        m_fuel = df_merged["Max_Fuel_Allowance"] if "Max_Fuel_Allowance" in df_merged.columns else 0
        df_merged["Fuel_Variance"] = np.maximum(0, b_fuel - m_fuel)

        b_off = df_merged["Billed_Offloading"] if "Billed_Offloading" in df_merged.columns else 0
        m_off = df_merged["Max_Offloading_Allowance"] if "Max_Offloading_Allowance" in df_merged.columns else 0
        df_merged["Offloading_Variance"] = np.maximum(0, b_off - m_off)

        df_merged["Total_Overcharge"] = (
            df_merged["Base_Variance"] + df_merged["Fuel_Variance"] + df_merged["Offloading_Variance"]
        )

        df_merged["Expected_Subtotal"] = (c_base + m_fuel + m_off)
        df_merged["Expected_VAT"] = df_merged["Expected_Subtotal"] * 0.16
        df_merged["VAT_Discrepancy"] = np.abs(df_merged["Billed_VAT"] - df_merged["Expected_VAT"])

        df_merged["eTIMS_Valid"] = (
            df_merged["eTIMS_CU_Serial"].astype(str).str.startswith("KRA")
            & (df_merged["VAT_Discrepancy"] < 1.0)
        )

        conditions = [
            (df_merged["Total_Overcharge"] > 0) & (~df_merged["eTIMS_Valid"]),
            (df_merged["Total_Overcharge"] > 0),
            (~df_merged["eTIMS_Valid"]),
        ]
        choices = [
            "FLAGGED_OVERCHARGE_AND_ETIMS",
            "FLAGGED_RATE_OVERCHARGE",
            "FLAGGED_ETIMS_NON_COMPLIANT",
        ]
        df_merged["Audit_Status"] = np.select(conditions, choices, default="PASSED_VERIFIED")

        # Automatically store batch run in permanent database history
        save_audit_record(df_merged)

        # ROI Calculator Metrics
        total_recovered = df_merged['Total_Overcharge'].sum()
        estimated_tool_cost = 25000.0  # KES Monthly License Baseline
        roi_multiplier = (total_recovered / estimated_tool_cost) if total_recovered > 0 else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("PDFs Processed", len(df_merged))
        m2.metric("Verified Clean", len(df_merged[df_merged["Audit_Status"] == "PASSED_VERIFIED"]))
        m3.metric("Capital Saved", f"KES {total_recovered:,.2f}")
        m4.metric("Estimated Platform ROI", f"{roi_multiplier:.1f}x")

        st.markdown("---")
        st.subheader("📋 Audit Extraction Results")
        st.dataframe(
            df_merged[[
                "Invoice_No", "Carrier", "BoL_Ref", "eTIMS_CU_Serial", "Total_Overcharge", "Audit_Status"
            ]],
            use_container_width=True,
        )

        # Dispute Email Action Center
        st.subheader("✉️ Action Center: Direct Dispute Resolution")
        flagged = df_merged[df_merged["Audit_Status"] != "PASSED_VERIFIED"]

        if not flagged.empty:
            selected_inv = st.selectbox("Select Invoice for Action:", flagged["Invoice_No"])
            selected_df = flagged[flagged["Invoice_No"] == selected_inv]
            row = selected_df.iloc[0]

            b_base_val = row.get("Billed_Base", row.get("Billed_Base_Rate", 0.0))
            c_base_val = row.get("Contract_Base", 0.0)
            overcharge_val = row.get("Total_Overcharge", 0.0)
            status_val = row.get("Audit_Status", "FLAGGED")

            carrier_name = str(row.get("Carrier", "Carrier"))
            email_slug = carrier_name.lower().replace(" ", "")

            recipient_email = st.text_input("Carrier Accounts Email:", value=f"accounts@{email_slug}.co.ke")
            
            # PDF Debit Note Generator Download Button
            pdf_bytes = generate_pdf_debit_note(row)
            st.download_button(
                label="📄 Generate & Download Official Debit Note (PDF)",
                data=pdf_bytes,
                file_name=f"Debit_Note_{row.get('Invoice_No', 'INV')}.pdf",
                mime="application/pdf"
            )

            dispute_body = f"""Dear {carrier_name} Accounts Team,

Our automated audit engine identified an overcharge / eTIMS discrepancy on Invoice #{row.get('Invoice_No', 'N/A')}.

Audit Summary:
- Status: {status_val}
- Billed Base Rate: KES {b_base_val:,.2f} | Contract Base: KES {c_base_val:,.2f}
- Calculated Overcharge: KES {overcharge_val:,.2f}
- eTIMS Validation: {'VALID' if row.get('eTIMS_Valid', False) else 'INVALID / MISMATCHED VAT'}

Please issue a revised tax invoice or credit note matching contract rates.

Regards,
Logistics & Finance Team
"""
            st.text_area("Dispute Email Preview:", dispute_body, height=160)

            # RBAC Enforcement for Email Dispatch
            if st.session_state["role"] in ["admin", "finance"]:
                if st.button("🚀 Dispatch Dispute Email"):
                    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
                    smtp_port = int(os.getenv("SMTP_PORT", 587))
                    smtp_user = os.getenv("SMTP_USER", "")
                    smtp_pass = os.getenv("SMTP_PASS", "")

                    if smtp_user and smtp_pass:
                        try:
                            msg = MIMEText(dispute_body)
                            msg["Subject"] = f"Discrepancy Notice - Invoice #{row.get('Invoice_No', 'N/A')}"
                            msg["From"] = smtp_user
                            msg["To"] = recipient_email

                            server = smtplib.SMTP(smtp_server, smtp_port)
                            server.starttls()
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(smtp_user, [recipient_email], msg.as_string())
                            server.quit()
                            st.success(f"Dispute notice dispatched to {recipient_email}!")
                        except Exception as e:
                            st.error(f"Failed to send email: {str(e)}")
                    else:
                        st.warning("SMTP credentials not configured. Simulated dispatch logged.")
            else:
                st.info("🔒 Note: Only users with 'Finance Manager' or 'Admin' roles can dispatch live dispute emails.")

# ------------------------------------------------------------------------------
# TAB 2: CARRIER SCORECARDS & ROI ANALYTICS
# ------------------------------------------------------------------------------
with tabs[1]:
    st.subheader("📊 Carrier Performance & Audit Scorecards")
    
    conn = sqlite3.connect(DB_FILE)
    df_ledger_analytics = pd.read_sql_query("SELECT * FROM audit_ledger", conn)
    conn.close()

    if not df_ledger_analytics.empty:
        c1, c2 = st.columns(2)
        
        with c1:
            st.markdown("**Total Financial Overcharges by Carrier (Cumulative)**")
            carrier_summary = df_ledger_analytics.groupby("carrier")["total_overcharge"].sum().reset_index()
            fig1 = px.bar(carrier_summary, x="carrier", y="total_overcharge", color="carrier", labels={"total_overcharge": "Overcharge (KES)"})
            st.plotly_chart(fig1, use_container_width=True)
            
        with c2:
            st.markdown("**eTIMS Compliance Breakdown**")
            compliance_summary = df_ledger_analytics.groupby(["carrier", "etims_valid"]).size().reset_index(name="count")
            compliance_summary["etims_valid"] = compliance_summary["etims_valid"].map({1: "Valid", 0: "Non-Compliant"})
            fig2 = px.bar(compliance_summary, x="carrier", y="count", color="etims_valid", barmode="group")
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No historical ledger data available for analytics yet. Upload invoices in Tab 1 to generate scorecards.")

# ------------------------------------------------------------------------------
# TAB 3: HISTORICAL AUDIT LEDGER DATABASE
# ------------------------------------------------------------------------------
with tabs[2]:
    st.subheader("📜 Company Historical Audit Database")
    conn = sqlite3.connect(DB_FILE)
    df_ledger = pd.read_sql_query("SELECT * FROM audit_ledger ORDER BY timestamp DESC", conn)
    conn.close()

    if not df_ledger.empty:
        st.dataframe(df_ledger, use_container_width=True)
        st.download_button(
            "📥 Download Complete Audit Ledger (CSV)",
            data=df_ledger.to_csv(index=False).encode("utf-8"),
            file_name="Company_Freight_Audit_Ledger.csv",
            mime="text/csv",
        )
    else:
        st.info("No historical records currently saved in company database ledger.")

# ------------------------------------------------------------------------------
# TAB 4: USER PROFILE & PASSWORD MANAGEMENT
# ------------------------------------------------------------------------------
with tabs[3]:
    st.subheader("👤 Account Profile & Security Settings")
    st.write(f"Active Account: **{st.session_state['username']}**")
    st.write(f"Access Role: **{st.session_state['role'].upper()}**")
    
    st.markdown("---")
    st.subheader("Change Password")
    with st.form("change_pass_form"):
        old_pass = st.text_input("Current Password", type="password")
        new_pass_1 = st.text_input("New Password", type="password")
        new_pass_2 = st.text_input("Confirm New Password", type="password")
        update_btn = st.form_submit_button("Update Password")
        
        if update_btn:
            if verify_user(st.session_state["username"], old_pass):
                if new_pass_1 == new_pass_2 and len(new_pass_1) > 3:
                    update_user_password(st.session_state["username"], new_pass_1)
                    st.success("Password updated successfully!")
                else:
                    st.error("New passwords do not match or are too short.")
            else:
                st.error("Current password verification failed.")

# ------------------------------------------------------------------------------
# TAB 5: INTEGRATION SETTINGS
# ------------------------------------------------------------------------------
with tabs[4]:
    st.subheader("⚙️ System Environment Configuration")
    st.write("Configure these Environment Variables on Render to enable live SMTP email dispatching:")
    st.code(
        """
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your-finance-email@company.com"
SMTP_PASS = "your-app-password"
    """,
        language="text",
    )
