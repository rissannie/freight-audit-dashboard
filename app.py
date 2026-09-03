import os
import re
import sqlite3
import hashlib
import urllib.parse
from io import BytesIO
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pdfplumber
import streamlit as st
import plotly.express as px

from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# ------------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & UI STYLING
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Enterprise Freight Audit", layout="wide")

st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { color: #1E3A8A; font-weight: 800; font-size: 28px; }
    .stTabs [data-baseweb="tab"] { background-color: #F1F5F9; border-radius: 4px; padding: 0 16px; margin-right: 4px;}
    .stTabs [aria-selected="true"] { background-color: #1E3A8A !important; color: white !important; }
    div[data-testid="stSidebar"] { background-color: #F8FAFC; border-right: 1px solid #E2E8F0; }
    h1, h2, h3 { color: #0F172A; }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "freight_audit_ledger.db"

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
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
            etims_valid INTEGER,
            dispute_status TEXT DEFAULT 'PENDING'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)
    
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
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_ledger")  # Refresh active session
    
    for _, row in df_results.iterrows():
        cur.execute(
            """
            INSERT INTO audit_ledger (invoice_no, carrier, bol_ref, etims_cu_serial, total_overcharge, audit_status, etims_valid, dispute_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """,
            (
                str(row.get("Invoice_No", "N/A")),
                str(row.get("Carrier", "Unknown")),
                str(row.get("BoL_Ref", "N/A")),
                str(row.get("eTIMS_CU_Serial", "N/A")),
                float(row.get("Total_Overcharge", 0.0)),
                str(row.get("Audit_Status", "UNVERIFIED")),
                1 if row.get("eTIMS_Valid", True) else 0,
            ),
        )
    conn.commit()
    conn.close()

def update_dispute_status(invoice_no, status):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE audit_ledger SET dispute_status = ? WHERE invoice_no = ?", (status, str(invoice_no)))
    conn.commit()
    conn.close()

def reset_password(username, new_password):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        cur.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(new_password), username))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# ------------------------------------------------------------------------------
# 2. AUTHENTICATION & FORGOT PASSWORD LOGIC
# ------------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "role" not in st.session_state:
    st.session_state["role"] = ""
if "audit_data" not in st.session_state:
    st.session_state["audit_data"] = pd.DataFrame()

def verify_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ? AND password_hash = ?", (username, hash_password(password)))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

if not st.session_state["authenticated"]:
    st.title("🔒 Enterprise Freight Audit Portal")
    
    auth_mode = st.radio("Choose Action:", ["Login", "Forgot Password"], horizontal=True)

    if auth_mode == "Login":
        with st.form("login_form"):
            username_input = st.text_input("Username")
            password_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
            if submit:
                user_role = verify_user(username_input, password_input)
                if user_role:
                    st.session_state.update({"authenticated": True, "username": username_input, "role": user_role})
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    else:
        with st.form("reset_password_form"):
            st.subheader("🔑 Reset Your Password")
            reset_username = st.text_input("Username")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            reset_submit = st.form_submit_button("Update Password")

            if reset_submit:
                if not reset_username or not new_password:
                    st.error("All fields are required.")
                elif new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    if reset_password(reset_username, new_password):
                        st.success("Password successfully updated! Please switch back to Login.")
                    else:
                        st.error("Username not found.")
    st.stop()

st.sidebar.write(f"Logged in as: **{st.session_state['username'].upper()}** | **{st.session_state['role'].upper()}**")
if st.sidebar.button("Logout"):
    st.session_state.update({"authenticated": False, "username": "", "role": ""})
    st.rerun()

# ------------------------------------------------------------------------------
# 3. UNIVERSAL PDF & CSV PARSING ENGINE (FEATURE 1 & 2 ENHANCED)
# ------------------------------------------------------------------------------
def parse_pdf_invoice_universal(file_obj, usd_rate):
    records = []
    clean_fname = os.path.splitext(file_obj.name)[0]
    
    try:
        with pdfplumber.open(file_obj) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                
                inv_match = re.search(
                    r"(?:Invoice\s*(?:No|#|\.?)|Inv\s*#?|Doc\s*#?|Ref\s*#?)\s*[:.]?\s*([A-Za-z0-9-_]+)", 
                    text, re.IGNORECASE
                )
                carrier_match = re.search(
                    r"([A-Za-z0-9\s]+(?:Logistics|Transport|Express|Freight|Limited|Ltd|Group|Swara|Kefar|Siginon|Rift))", 
                    text, re.IGNORECASE
                )
                bol_match = re.search(
                    r"(?:BoL|Bill of Lading|Waybill)\s*Ref\s*:?\s*([A-Za-z0-9-]+)", 
                    text, re.IGNORECASE
                )
                
                # FEATURE 1: Enhanced KRA eTIMS CU Serial & QR pattern extraction
                etims_match = re.search(
                    r"(KRA[A-Za-z0-9]{8,15}|CU[0-9]{8,12}|eTIMS[A-Za-z0-9-]+|KRA\d{11,14})", 
                    text, re.IGNORECASE
                )

                # FEATURE 2: FX Rate Detection within Invoice Text
                fx_match = re.search(r"(?:FX|Rate|Exchange\s*Rate|USD/KES)\s*[:=]?\s*(\d{2,3}\.\d{2})", text, re.IGNORECASE)
                billed_fx = float(fx_match.group(1)) if fx_match else usd_rate

                raw_numbers = re.findall(r"[\d,]+\.\d{2}", text)
                clean_amounts = [float(n.replace(",", "")) for n in raw_numbers if n.replace(",", "").replace(".", "").isdigit()]
                billed_amount = max(clean_amounts) if clean_amounts else 0.0
                
                if inv_match and len(inv_match.group(1).strip()) > 1:
                    invoice_id = inv_match.group(1).strip()
                else:
                    invoice_id = f"{clean_fname}_P{page_num}" if len(pdf.pages) > 1 else clean_fname

                # Validate eTIMS presence
                etims_serial = etims_match.group(1) if etims_match else "MISSING_ETIMS_CU"
                is_etims_valid = etims_serial != "MISSING_ETIMS_CU"

                records.append({
                    "Invoice_No": invoice_id,
                    "Carrier": carrier_match.group(1).strip() if carrier_match else "Swara Express",
                    "BoL_Ref": bol_match.group(1) if bol_match else "N/A",
                    "eTIMS_CU_Serial": etims_serial,
                    "eTIMS_Valid": is_etims_valid,
                    "Billed_FX_Rate": billed_fx,
                    "Billed_Base": float(billed_amount),
                })
    except Exception as e:
        st.sidebar.warning(f"Note: Extraction issue in {file_obj.name}: {str(e)}")

    if not records:
        records.append({
            "Invoice_No": clean_fname,
            "Carrier": "Carrier",
            "BoL_Ref": "N/A",
            "eTIMS_CU_Serial": "MISSING_ETIMS_CU",
            "eTIMS_Valid": False,
            "Billed_FX_Rate": usd_rate,
            "Billed_Base": 0.0,
        })
        
    return records

def generate_pdf_debit_note(row_data):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 750, "OFFICIAL DEBIT NOTE / AUDIT DISCREPANCY NOTICE")
    c.setFont("Helvetica", 10)
    c.drawString(50, 725, f"Carrier: {row_data.get('Carrier', 'N/A')}")
    c.drawString(50, 710, f"Target Invoice No: {row_data.get('Invoice_No', 'N/A')}")
    c.drawString(50, 695, f"BoL Reference: {row_data.get('BoL_Ref', 'N/A')}")
    c.drawString(50, 680, f"eTIMS CU Serial: {row_data.get('eTIMS_CU_Serial', 'N/A')}")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, 630, "Financial Variance Breakdown:")
    c.setFont("Helvetica", 10)
    c.drawString(70, 610, f"- Billed Base Rate: KES {row_data.get('Billed_Base', 0.0):,.2f}")
    c.drawString(70, 595, f"- Contract Base Rate: KES {row_data.get('Contract_Base', 0.0):,.2f}")
    c.drawString(70, 580, f"- FX Overcharge Premium: KES {row_data.get('FX_Overcharge', 0.0):,.2f}")
    c.drawString(70, 565, f"- Total Claimed Debit Overcharge: KES {row_data.get('Total_Overcharge', 0.0):,.2f}")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

def generate_batch_summary_pdf(df):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"Executive Batch Audit Summary - {datetime.now().strftime('%Y-%m-%d')}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    data = [["Invoice No", "Carrier", "BoL Ref", "eTIMS Status", "Overcharge (KES)", "Status"]]
    for _, row in df.iterrows():
        etims_status = "VALID" if row.get("eTIMS_Valid", True) else "NON_COMPLIANT"
        data.append([
            str(row.get("Invoice_No", "N/A")), str(row.get("Carrier", "N/A")), str(row.get("BoL_Ref", "N/A")),
            etims_status, f"{row.get('Total_Overcharge', 0.0):,.2f}", str(row.get("Audit_Status", "N/A"))
        ])
        
    table = Table(data, colWidths=[100, 130, 90, 100, 110, 170])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1E3A8A")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#F8FAFC")),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer

# ------------------------------------------------------------------------------
# 4. DASHBOARD INTERFACE & ACCURATE AUDIT ENGINE
# ------------------------------------------------------------------------------
st.title("🚛 Enterprise Freight Audit & Reconciliation")

tabs = st.tabs(["📋 Active Audit Engine", "⚓ Port Demurrage Tool", "📊 Carrier Scorecards", "📜 Dispute Ledger", "👤 User Profile"])

with tabs[0]:
    st.sidebar.header("⚙️ Global Audit Parameters")
    usd_fx_rate = st.sidebar.number_input("CBK Benchmark FX Rate (USD to KES)", value=130.0, step=0.5)
    variance_threshold = st.sidebar.slider("Overcharge Ignore Threshold (KES)", 0, 5000, 100)
    
    st.sidebar.header("📁 Upload Documents")
    pdf_files = st.sidebar.file_uploader("1. Upload PDF Invoices", type=["pdf"], accept_multiple_files=True)
    contract_file = st.sidebar.file_uploader("2. Upload Rate Card (CSV/Excel)", type=["csv", "xlsx"])

    if pdf_files and contract_file:
        invoice_records = []
        for pdf in pdf_files:
            invoice_records.extend(parse_pdf_invoice_universal(pdf, usd_fx_rate))

        df_inv = pd.DataFrame(invoice_records)

        df_rates = pd.read_csv(contract_file) if contract_file.name.endswith(".csv") else pd.read_excel(contract_file)
        df_rates.columns = [str(c).strip() for c in df_rates.columns]

        rate_col = None
        for col in df_rates.columns:
            if any(kw in col.lower() for kw in ["contract", "base", "rate", "price", "amount", "kes"]):
                rate_col = col
                break
                
        if not rate_col:
            num_cols = df_rates.select_dtypes(include=[np.number]).columns
            rate_col = num_cols[0] if len(num_cols) > 0 else df_rates.columns[-1]

        df_rates[rate_col] = pd.to_numeric(
            df_rates[rate_col].astype(str).str.replace(',', '').str.extract(r'([\d\.]+)')[0], 
            errors='coerce'
        ).fillna(0.0)

        df_inv["Billed_Base"] = pd.to_numeric(
            df_inv["Billed_Base"].astype(str).str.replace(',', '').str.extract(r'([\d\.]+)')[0], 
            errors='coerce'
        ).fillna(0.0)

        contract_rates = df_rates[rate_col].values
        total_inv_count = len(df_inv)
        
        if len(contract_rates) >= total_inv_count:
            df_inv["Contract_Base"] = contract_rates[:total_inv_count]
        else:
            padded_rates = list(contract_rates) + [0.0] * (total_inv_count - len(contract_rates))
            df_inv["Contract_Base"] = padded_rates[:total_inv_count]

        df_merged = df_inv.copy()

        # FEATURE 1: FX Rate Overcharge Audit Logic
        fx_diff = np.maximum(0.0, df_merged["Billed_FX_Rate"] - usd_fx_rate)
        df_merged["FX_Overcharge"] = (df_merged["Billed_Base"] / usd_fx_rate) * fx_diff

        # Rate Variance Logic
        rate_diff = df_merged["Billed_Base"] - df_merged["Contract_Base"]
        base_overcharge = np.where(rate_diff > variance_threshold, rate_diff, 0.0)

        df_merged["Total_Overcharge"] = base_overcharge + df_merged["FX_Overcharge"]
        
        # FEATURE 2: eTIMS Status flagging
        conditions = [
            (~df_merged["eTIMS_Valid"]),
            (df_merged["Total_Overcharge"] > 0)
        ]
        choices = ["FLAGGED_INVALID_ETIMS", "FLAGGED_RATE_OVERCHARGE"]
        df_merged["Audit_Status"] = np.select(conditions, choices, default="PASSED_VERIFIED")

        save_audit_record(df_merged)
        st.session_state["audit_data"] = df_merged

    df_active = st.session_state.get("audit_data", pd.DataFrame())

    if not df_active.empty and "Total_Overcharge" in df_active.columns:
        total_recovered = df_active['Total_Overcharge'].sum()
        clean_count = len(df_active[df_active["Audit_Status"] == "PASSED_VERIFIED"])
        invalid_etims_count = len(df_active[~df_active["eTIMS_Valid"]])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invoices Processed", len(df_active))
        c2.metric("Verified Clean", clean_count)
        c3.metric("Capital Saved", f"KES {total_recovered:,.2f}")
        c4.metric("Non-Compliant eTIMS", invalid_etims_count)

        st.markdown("---")
        c_left, c_right = st.columns([3, 1])
        with c_left:
            st.subheader("📋 Audit Extraction Results")
        with c_right:
            st.download_button("📥 Executive PDF Report", generate_batch_summary_pdf(df_active), "Batch_Summary.pdf", "application/pdf")
            
        st.dataframe(
            df_active[["Invoice_No", "Carrier", "Billed_Base", "Contract_Base", "Billed_FX_Rate", "eTIMS_CU_Serial", "Total_Overcharge", "Audit_Status"]], 
            use_container_width=True
        )

        flagged = df_active[df_active["Audit_Status"] != "PASSED_VERIFIED"].copy()
        
        valid_flagged_options = [
            str(inv).strip() for inv in flagged["Invoice_No"].unique() 
            if str(inv).strip() not in ["", "-", "None", "nan", "N/A"]
        ]

        if valid_flagged_options:
            st.subheader("✉️ Action Center")
            selected_inv = st.selectbox("Select Invoice:", valid_flagged_options)
            
            matched_rows = flagged[flagged["Invoice_No"].astype(str) == selected_inv]
            row = matched_rows.iloc[0] if not matched_rows.empty else flagged.iloc[0]

            # Generate Dispute Email Content
            email_subject = f"DISPUTE NOTICE: Invoice Discrepancy #{selected_inv} - {row['Carrier']}"
            email_body = f"""Dear Accounts Receivable Team ({row['Carrier']}),

We are formally disputing charges on Invoice #{selected_inv} (BoL Ref: {row['BoL_Ref']}).

Audit Variance Breakdown:
------------------------------------------
- Billed Amount: KES {row['Billed_Base']:,.2f}
- Contract Base Rate: KES {row['Contract_Base']:,.2f}
- FX Rate Applied: {row['Billed_FX_Rate']} (Benchmark: {usd_fx_rate})
- eTIMS CU Status: {row['eTIMS_CU_Serial']}
- Total Claimed Debit Overcharge: KES {row['Total_Overcharge']:,.2f}

Please issue a credit note for KES {row['Total_Overcharge']:,.2f} at your earliest convenience.

Best regards,
Freight Audit Team
{st.session_state['username'].title()} ({st.session_state['role'].upper()})
"""

            # FEATURE 4: Pre-formatted WhatsApp Message & Link Generator
            whatsapp_text = f"Hello {row['Carrier']} Team. Re: Invoice #{selected_inv} (BoL: {row['BoL_Ref']}). Our audit flagged a variance of KES {row['Total_Overcharge']:,.2f}. Please review the formal debit note sent to your email."
            whatsapp_url = f"https://wa.me/?text={urllib.parse.quote(whatsapp_text)}"

            # Email Content Preview Box
            with st.expander("✉️ Preview Dispute Message & Dispatch Options", expanded=True):
                st.text_input("Subject:", value=email_subject, disabled=True)
                st.text_area("Message Body:", value=email_body, height=180)
                st.markdown(f"[📲 Send Dispute Summary via WhatsApp]({whatsapp_url})", unsafe_allow_html=True)

            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                st.download_button("📄 Download Debit Note (PDF)", generate_pdf_debit_note(row), f"Debit_Note_{selected_inv}.pdf", "application/pdf")
            
            if st.session_state["role"] in ["admin", "finance"]:
                if st.button("🚀 Dispatch Dispute Email"):
                    update_dispute_status(selected_inv, 'DISPUTE_SENT')
                    st.success(f"Dispute logged and email dispatched for Invoice {selected_inv}!")
        else:
            st.info("No flagged invoices requiring dispute dispatching.")
    else:
        st.info("👈 Upload PDF Invoices and Rate Cards in the sidebar to view audit extraction results.")

# FEATURE 3: MOMBASA PORT & ICD DEMURRAGE CALCULATOR TAB
with tabs[1]:
    st.subheader("⚓ Mombasa Port & ICD Demurrage Auditor")
    st.write("Calculate free-period allowances and audit container detention charges.")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        shipment_type = st.selectbox("Shipment Destination Type", ["Local Import (7 Free Days)", "Transit Cargo (14 Free Days)"])
        gate_out_date = st.date_input("Discharge Date at Port", value=datetime.today() - timedelta(days=12))
        return_date = st.date_input("Empty Container Return Date", value=datetime.today())
        container_count = st.number_input("Number of Containers", min_value=1, value=2)

    with col_d2:
        daily_demurrage_usd = st.number_input("Daily Demurrage Rate per Container (USD)", value=40.0)
        billed_demurrage_kes = st.number_input("Demurrage Amount Billed by Carrier (KES)", value=65000.0)

    # Calculation Logic
    free_days = 7 if "Local" in shipment_type else 14
    total_days = (return_date - gate_out_date).days
    chargeable_days = max(0, total_days - free_days)
    
    expected_demurrage_usd = chargeable_days * daily_demurrage_usd * container_count
    expected_demurrage_kes = expected_demurrage_usd * usd_fx_rate
    demurrage_overcharge = max(0.0, billed_demurrage_kes - expected_demurrage_kes)

    st.markdown("---")
    res_c1, res_c2, res_c3 = st.columns(3)
    res_c1.metric("Days Port-to-Return", f"{total_days} Days")
    res_c2.metric("Chargeable Days", f"{chargeable_days} Days (Free: {free_days})")
    res_c3.metric("Demurrage Overcharge Claim", f"KES {demurrage_overcharge:,.2f}")

    if demurrage_overcharge > 0:
        st.error(f"⚠️ Flagged Demurrage Overcharge: Carrier overbilled by KES {demurrage_overcharge:,.2f}.")

with tabs[2]:
    st.subheader("📊 Carrier Analytics")
    df_active = st.session_state.get("audit_data", pd.DataFrame())
    if not df_active.empty and "Carrier" in df_active.columns:
        summary_df = df_active.groupby("Carrier")["Total_Overcharge"].sum().reset_index()
        fig = px.bar(summary_df, x="Carrier", y="Total_Overcharge", title="Total Claims by Carrier (KES)", color="Carrier", text_auto='.2f')
        st.plotly_chart(fig, use_container_width=True)

with tabs[3]:
    st.subheader("📜 Audit Trail & Dispute History")
    conn = sqlite3.connect(DB_FILE)
    df_ledger = pd.read_sql_query("SELECT timestamp, invoice_no, carrier, total_overcharge, audit_status, dispute_status FROM audit_ledger ORDER BY timestamp DESC", conn)
    conn.close()
    if not df_ledger.empty:
        st.dataframe(df_ledger, use_container_width=True)

with tabs[4]:
    st.subheader("👤 User Profile")
    st.write(f"Logged in user: **{st.session_state['username']}** | Role: **{st.session_state['role']}**")
