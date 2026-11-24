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
# ------------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & EXECUTIVE DARK UI STYLING
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Enterprise Freight Audit & Telematics", layout="wide")

st.markdown("""
    <style>
    /* Deep Obsidian & Midnight Slate Background Theme */
    .stApp {
        background: linear-gradient(135deg, #090D16 0%, #0F172A 50%, #111827 100%);
        color: #F8FAFC;
    }

    /* Top Header Bar Transparency */
    header[data-testid="stHeader"] {
        background-color: rgba(9, 13, 22, 0.85) !important;
        border-bottom: 1px solid #1E293B;
    }

    /* Sidebar Deep Carbon Gradient */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #060911 0%, #0F172A 100%) !important;
        border-right: 1px solid #1E293B;
    }
    section[data-testid="stSidebar"] * {
        color: #E2E8F0 !important;
    }
    section[data-testid="stSidebar"] input,
    section[data-testid="stSidebar"] select,
    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background-color: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid #334155 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background-color: rgba(30, 41, 59, 0.6) !important;
        border: 1px dashed #475569 !important;
    }
    section[data-testid="stSidebar"] button {
        background: linear-gradient(90deg, #1D4ED8 0%, #2563EB 100%) !important;
        color: #FFFFFF !important;
        border: 1px solid #3B82F6 !important;
    }

    /* Main Content Inputs, Selectboxes, Textareas & Expanders */
    .stTextInput input, .stNumberInput input, .stTextArea textarea, .stDateInput input {
        background-color: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid #334155 !important;
    }
    [data-baseweb="select"] > div {
        background-color: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid #334155 !important;
    }
    [data-testid="stExpander"] {
        background-color: #111827 !important;
        border: 1px solid #1E293B !important;
        border-radius: 10px !important;
    }
    [data-testid="stExpander"] summary, [data-testid="stExpander"] * {
        color: #E2E8F0 !important;
    }

    /* Dark Mode Native Metrics */
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
        color: #F8FAFC !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
    }
    [data-testid="stMetricLabel"] {
        color: #94A3B8 !important;
    }
    [data-testid="stMetric"] {
        width: 100% !important;
        background: linear-gradient(180deg, #1E293B 0%, #111827 100%);
        padding: 14px;
        border-radius: 10px;
        border: 1px solid #334155;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
    }

    /* Styled Dark Navigation Tabs */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #111827;
        padding: 6px;
        border-radius: 10px;
        border: 1px solid #1E293B;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 6px;
        padding: 8px 16px;
        margin-right: 4px;
        font-weight: 600;
        color: #94A3B8;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: #F8FAFC;
        background-color: rgba(51, 65, 85, 0.4);
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, #1E3A8A 0%, #2563EB 100%) !important;
        color: #FFFFFF !important;
    }

    /* Typography & Dividers */
    h1, h2, h3, p, label, .stMarkdown {
        color: #F1F5F9;
    }
    h1, h2, h3 {
        font-weight: 800;
    }
    hr {
        border-color: #1E293B !important;
    }

    /* Action & Download Buttons */
    .stDownloadButton button, .stButton button {
        background-color: #1E293B !important;
        color: #F8FAFC !important;
        border: 1px solid #3B82F6 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    .stDownloadButton button:hover, .stButton button:hover {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
    }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "freight_audit_ledger.db"


def colored_metric(label, value, text_color="#38BDF8", subtitle=""):
    # Automatically brighten deep light-mode colors so they pop on dark slate cards
    dark_mode_color_map = {
        "#1E3A8A": "#60A5FA",  # Luminous Royal Blue
        "#0284C7": "#38BDF8",  # Bright Cyan
        "#16A34A": "#4ADE80",  # Emerald Green
        "#334155": "#E2E8F0",  # Crisp Silver Slate
        "#DC2626": "#F87171",  # Coral Red
        "#D97706": "#FBBF24",  # Warm Amber
    }
    display_color = dark_mode_color_map.get(text_color.upper(), text_color)
    sub_html = f'<div style="color: #94A3B8; font-size: 0.75rem; margin-top: 4px;">{subtitle}</div>' if subtitle else ""
    st.markdown(f"""
        <div style="background: linear-gradient(180deg, #1E293B 0%, #0F172A 100%); padding: 16px 18px; border-radius: 10px; border: 1px solid #334155; border-top: 4px solid {display_color}; box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35);">
            <div style="color: #94A3B8; font-size: 0.80rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">{label}</div>
            <div style="color: {display_color}; font-size: 1.45rem; font-weight: 800; line-height: 1.2;">{value}</div>
            {sub_html}
        </div>
    """, unsafe_allow_html=True)


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
            billed_total REAL DEFAULT 0.0,
            approved_payable REAL DEFAULT 0.0,
            total_overcharge REAL DEFAULT 0.0,
            audit_status TEXT,
            etims_valid INTEGER DEFAULT 1,
            dispute_status TEXT DEFAULT 'PENDING'
        )
    """)

    # Ensure backward-compatible columns exist if upgrading from an older DB file
    existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(audit_ledger)").fetchall()]
    if "billed_total" not in existing_cols:
        cursor.execute("ALTER TABLE audit_ledger ADD COLUMN billed_total REAL DEFAULT 0.0")
    if "approved_payable" not in existing_cols:
        cursor.execute("ALTER TABLE audit_ledger ADD COLUMN approved_payable REAL DEFAULT 0.0")

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
            ("auditor", hash_password("auditor123"), "auditor@company.co.ke", "auditor"),
        ]
        cursor.executemany(
            "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
            default_users,
        )

    conn.commit()
    conn.close()


init_db()


def get_existing_ledger_keys():
    """Persistent historical memory for duplicate & split-billing detection."""
    conn = sqlite3.connect(DB_FILE)
    df_hist = pd.read_sql_query(
        "SELECT invoice_no, bol_ref, etims_cu_serial FROM audit_ledger",
        conn,
    )
    conn.close()
    existing_invs = set(
        df_hist["invoice_no"].dropna().astype(str).str.strip().str.upper().tolist()
    ) - {"", "N/A", "NONE", "NAN"}
    existing_bols = set(
        df_hist["bol_ref"].dropna().astype(str).str.strip().str.upper().tolist()
    ) - {"", "N/A", "NONE", "NAN"}
    existing_etims = set(
        df_hist["etims_cu_serial"].dropna().astype(str).str.strip().str.upper().tolist()
    ) - {"", "N/A", "NONE", "NAN", "MISSING_ETIMS_CU"}
    return existing_invs, existing_bols, existing_etims


def save_audit_record(df_results, replace_existing=False):
    """Persists audit records without wiping historical memory unless explicitly requested."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if replace_existing:
        cur.execute("DELETE FROM audit_ledger")

    for _, row in df_results.iterrows():
        inv_no = str(row.get("Invoice_No", "N/A")).strip()
        # Avoid re-inserting exact same invoice row on Streamlit UI reruns
        cur.execute(
            "SELECT id FROM audit_ledger WHERE invoice_no = ? AND bol_ref = ? AND billed_total = ?",
            (inv_no, str(row.get("BoL_Ref", "N/A")), float(row.get("Billed_Total", 0.0))),
        )
        if cur.fetchone():
            continue

        cur.execute(
            """
            INSERT INTO audit_ledger (
                invoice_no, carrier, bol_ref, etims_cu_serial,
                billed_total, approved_payable, total_overcharge,
                audit_status, etims_valid, dispute_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                inv_no,
                str(row.get("Carrier", "Unknown")),
                str(row.get("BoL_Ref", "N/A")),
                str(row.get("eTIMS_CU_Serial", "N/A")),
                float(row.get("Billed_Total", 0.0)),
                float(row.get("Approved_Payable", 0.0)),
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
if "telematics_df" not in st.session_state:
    st.session_state["telematics_df"] = pd.DataFrame()


def verify_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role FROM users WHERE username = ? AND password_hash = ?",
        (username, hash_password(password)),
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


if not st.session_state["authenticated"]:
    st.markdown("""
        <div style="background: linear-gradient(90deg, #0F172A 0%, #1E3A8A 100%); padding: 24px 30px; border-radius: 12px; color: white; margin-bottom: 24px;">
            <h1 style="color: white; margin: 0;">🔒 Enterprise Freight Audit & Telematics Portal</h1>
            <p style="color: #CBD5E1; margin: 6px 0 0 0;">Forensic Carrier Reconciliation • 3-Way GPS/POD Verification • KRA eTIMS Compliance</p>
        </div>
    """, unsafe_allow_html=True)

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

st.sidebar.markdown(
    f"👤 **{st.session_state['username'].upper()}** | Role: **{st.session_state['role'].upper()}**"
)
if st.sidebar.button("Logout"):
    st.session_state.update({"authenticated": False, "username": "", "role": ""})
    st.rerun()


# ------------------------------------------------------------------------------
# 3. UNIVERSAL LINE-ITEM PDF PARSING ENGINE & VOUCHER GENERATORS
# ------------------------------------------------------------------------------
def _parse_amount(val_str: str) -> float:
    if not val_str:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(val_str))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def parse_pdf_invoice_universal(file_obj, usd_rate):
    """
    Extracts structured line items (Base Rate, Fuel Surcharge, Offloading, Detention, VAT, Total),
    splits repeated invoice blocks on the same page, and handles both integer (145,000) and
    decimal (145,000.00) currency formats.
    """
    records = []
    clean_fname = os.path.splitext(file_obj.name)[0]

    try:
        with pdfplumber.open(file_obj) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""

                # Split repeated invoice blocks on the same page if standalone "INVOICE" headers exist
                blocks = re.split(r"(?im)^\s*INVOICE\s*$", text.strip())
                blocks = [b.strip() for b in blocks if b.strip()] or [text]

                for block_idx, block in enumerate(blocks, start=1):
                    inv_match = re.search(
                        r"(?:Invoice\s*(?:#|No\.?)|Inv\s*#?|Doc\s*#?)\s*[:.]?\s*([A-Za-z0-9-]+)",
                        block,
                        re.IGNORECASE,
                    )
                    # Single-line carrier capture (never crosses newlines)
                    carrier_match = re.search(
                        r"^([A-Za-z0-9&.,' -]+?(?:Logistics|Transport|Express|Freight|Limited|Ltd|Group|Hauliers|Cargo|Swara|Kefar|Siginon|Rift)[A-Za-z0-9&.,' -]*)$",
                        block,
                        re.IGNORECASE | re.MULTILINE,
                    )
                    bol_match = re.search(
                        r"(?:BoL|Bill\s*of\s*Lading|Waybill)\s*(?:Ref|ID|#)?\s*[:.]?\s*([A-Za-z0-9-]+)",
                        block,
                        re.IGNORECASE,
                    )
                    etims_match = re.search(
                        r" (KRA[A-Za-z0-9]{8,15}|CU[0-9]{8,12}|eTIMS[A-Za-z0-9-]+|INVALID-[A-Za-z0-9-]+|MISSING-SERIAL) ",
                        block,
                        re.IGNORECASE,
                    )
                    fx_match = re.search(
                        r"(?:FX|Exchange\s*Rate|USD/KES)\s*[:=]?\s*(\d{2,3}(?:\.\d{1,4})?)",
                        block,
                        re.IGNORECASE,
                    )
                    route_match = re.search(
                        r"(?:Route|Corridor|Lane)\s*[:=]?\s*([A-Za-z0-9\s\-–>]+)",
                        block,
                        re.IGNORECASE,
                    )
                    truck_match = re.search(
                        r"(?:Truck|Plate|Reg|Vehicle)\s*(?:No|ID|#)?\s*[:=]?\s*([A-Z]{2,3}\s?\d{3}[A-Z]?|TRK-\d+)",
                        block,
                        re.IGNORECASE,
                    )
                    tonnage_match = re.search(
                        r"(\d+(?:\.\d+)?)\s*(?:Ton|Tons|Tonne|Tonnes|T) ",
                        block,
                        re.IGNORECASE,
                    )

                    # Line-item extractions (supports both comma integers and decimals)
                    num_pat = r"(?:KES|USD)?\s*([\d,]+(?:\.\d{1,2})?)"
                    base_match = re.search(rf"Base\s*(?:Rate|Freight)?\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)
                    fuel_match = re.search(rf"Fuel\s*(?:Surcharge|Allowance|FAF)?\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)
                    offload_match = re.search(rf"(?:Offloading|Loading|Handling)\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)
                    detention_match = re.search(rf"(?:Detention|Demurrage|Waiting\s*Time)\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)
                    subtotal_match = re.search(rf"SUBTOTAL\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)
                    vat_match = re.search(rf"VAT\s*(?:\(\d+%\))?\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)
                    total_match = re.search(rf"(?:TOTAL\s*DUE|GRAND\s*TOTAL|TOTAL)\s*[:=]?\s*{num_pat}", block, re.IGNORECASE)

                    billed_base = _parse_amount(base_match.group(1)) if base_match else 0.0
                    billed_fuel = _parse_amount(fuel_match.group(1)) if fuel_match else 0.0
                    billed_offload = _parse_amount(offload_match.group(1)) if offload_match else 0.0
                    billed_detention = _parse_amount(detention_match.group(1)) if detention_match else 0.0
                    billed_subtotal = _parse_amount(subtotal_match.group(1)) if subtotal_match else 0.0
                    billed_vat = _parse_amount(vat_match.group(1)) if vat_match else 0.0
                    billed_total = _parse_amount(total_match.group(1)) if total_match else 0.0

                    # Fallback if invoice is a single lump sum without itemized labels
                    if billed_base == 0.0:
                        raw_nums = re.findall(r" \d{1,3}(?:,\d{3})+(?:\.\d{1,2})? | \d+\.\d{2} ", block)
                        amounts = [_parse_amount(n) for n in raw_nums]
                        if billed_subtotal > 0:
                            billed_base = billed_subtotal
                        elif billed_total > 0:
                            billed_base = billed_total
                        elif amounts:
                            billed_base = max(amounts)

                    if billed_subtotal == 0.0:
                        billed_subtotal = billed_base + billed_fuel + billed_offload + billed_detention

                    if billed_total == 0.0:
                        billed_total = billed_subtotal + billed_vat

                    suffix = f"_P{page_num}" if len(pdf.pages) > 1 else ""
                    if len(blocks) > 1:
                        suffix += f"_B{block_idx}"

                    invoice_id = (
                        inv_match.group(1).strip()
                        if inv_match and len(inv_match.group(1).strip()) > 1
                        else f"{clean_fname}{suffix}"
                    )

                    etims_serial = etims_match.group(1).strip() if etims_match else "MISSING_ETIMS_CU"
                    is_etims_valid = not (
                        etims_serial.upper().startswith("MISSING")
                        or etims_serial.upper().startswith("INVALID")
                    )

                    records.append({
                        "Invoice_No": invoice_id,
                        "Carrier": carrier_match.group(1).strip() if carrier_match else "Unknown Carrier",
                        "BoL_Ref": bol_match.group(1).strip() if bol_match else "N/A",
                        "Route": route_match.group(1).strip() if route_match else "N/A",
                        "Truck_ID": truck_match.group(1).strip() if truck_match else "N/A",
                        "Vehicle_Tonnage": float(tonnage_match.group(1)) if tonnage_match else 0.0,
                        "eTIMS_CU_Serial": etims_serial,
                        "eTIMS_Valid": is_etims_valid,
                        "Billed_FX_Rate": float(fx_match.group(1)) if fx_match else float(usd_rate),
                        "Billed_Base": billed_base,
                        "Billed_Fuel": billed_fuel,
                        "Billed_Offloading": billed_offload,
                        "Billed_Detention": billed_detention,
                        "Billed_Subtotal": billed_subtotal,
                        "Billed_VAT": billed_vat,
                        "Billed_Total": billed_total,
                    })
    except Exception as e:
        st.sidebar.warning(f"Note: Extraction issue in {file_obj.name}: {str(e)}")

    if not records:
        records.append({
            "Invoice_No": clean_fname,
            "Carrier": "Unknown Carrier",
            "BoL_Ref": "N/A",
            "Route": "N/A",
            "Truck_ID": "N/A",
            "Vehicle_Tonnage": 0.0,
            "eTIMS_CU_Serial": "MISSING_ETIMS_CU",
            "eTIMS_Valid": False,
            "Billed_FX_Rate": float(usd_rate),
            "Billed_Base": 0.0,
            "Billed_Fuel": 0.0,
            "Billed_Offloading": 0.0,
            "Billed_Detention": 0.0,
            "Billed_Subtotal": 0.0,
            "Billed_VAT": 0.0,
            "Billed_Total": 0.0,
        })

    return records


def generate_pdf_debit_note(row_data):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.rect(0, 730, 612, 65, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(45, 755, "OFFICIAL DEBIT NOTE & AUDIT DISCREPANCY NOTICE")
    c.setFont("Helvetica", 9)
    c.drawString(45, 740, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Enterprise Freight Audit Engine")

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(45, 700, f"Carrier: {row_data.get('Carrier', 'N/A')}")
    c.drawString(45, 682, f"Invoice No: {row_data.get('Invoice_No', 'N/A')}   |   BoL Ref: {row_data.get('BoL_Ref', 'N/A')}")
    c.drawString(45, 664, f"eTIMS CU Serial: {row_data.get('eTIMS_CU_Serial', 'N/A')}   |   Status: {row_data.get('Audit_Status', 'N/A')}")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(45, 628, "Line-Item Financial Variance Breakdown (KES):")
    c.setFont("Helvetica", 10)
    lines = [
        f"1. Base Freight: Billed KES {row_data.get('Billed_Base', 0.0):,.2f} vs Contract KES {row_data.get('Contract_Base', 0.0):,.2f} -> Overcharge: KES {row_data.get('Base_Overcharge', 0.0):,.2f}",
        f"2. Fuel Surcharge: Billed KES {row_data.get('Billed_Fuel', 0.0):,.2f} vs Cap KES {row_data.get('Max_Fuel', 0.0):,.2f} -> Overcharge: KES {row_data.get('Fuel_Overcharge', 0.0):,.2f}",
        f"3. Offloading / Handling: Billed KES {row_data.get('Billed_Offloading', 0.0):,.2f} vs Cap KES {row_data.get('Max_Offloading', 0.0):,.2f} -> Overcharge: KES {row_data.get('Offload_Overcharge', 0.0):,.2f}",
        f"4. Detention & 3-Way GPS Penalty: KES {row_data.get('GPS_Penalty', 0.0):,.2f}",
        f"5. FX Conversion Arbitrage Overcharge: KES {row_data.get('FX_Overcharge', 0.0):,.2f}",
        f"6. VAT Adjustment (16% on Disallowed Charges): KES {row_data.get('VAT_Overcharge', 0.0):,.2f}",
    ]
    y = 605
    for line in lines:
        c.drawString(55, y, line)
        y -= 18

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#DC2626"))
    c.drawString(45, y - 15, f"TOTAL CLAIMED DEBIT / DEDUCTION: KES {row_data.get('Total_Overcharge', 0.0):,.2f}")
    c.setFillColor(colors.HexColor("#16A34A"))
    c.drawString(45, y - 35, f"APPROVED NET PAYABLE AMOUNT: KES {row_data.get('Approved_Payable', 0.0):,.2f}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def generate_short_pay_voucher_pdf(row_data):
    """Generates a Remittance Advice & Short-Pay Authorization Voucher for Finance."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.rect(0, 730, 612, 65, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(45, 755, "REMITTANCE ADVICE & SHORT-PAY AUTHORIZATION VOUCHER")
    c.setFont("Helvetica", 9)
    c.drawString(45, 740, "Self-Billing Accounts Payable Control Document | Verified Contract Settlement")

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(45, 695, f"Payee / Carrier: {row_data.get('Carrier', 'N/A')}")
    c.drawString(45, 677, f"Invoice Reference: {row_data.get('Invoice_No', 'N/A')}   |   Waybill / BoL: {row_data.get('BoL_Ref', 'N/A')}")
    c.drawString(45, 659, f"eTIMS Serial: {row_data.get('eTIMS_CU_Serial', 'N/A')}")

    c.setFont("Helvetica", 11)
    c.drawString(45, 620, f"Original Gross Invoice Billed:       KES {row_data.get('Billed_Total', 0.0):,.2f}")
    c.drawString(45, 600, f"Less Audited Discrepancies & VAT:   -KES {row_data.get('Total_Overcharge', 0.0):,.2f}")
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(colors.HexColor("#15803D"))
    c.drawString(45, 572, f"AUTHORIZED NET PAYMENT RELEASE:      KES {row_data.get('Approved_Payable', 0.0):,.2f}")

    c.setFillColor(colors.HexColor("#475569"))
    c.setFont("Helvetica", 9)
    c.drawString(45, 535, "Note: Payment is remitted strictly per contracted tariff and GPS-verified delivery completion.")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def generate_batch_summary_pdf(df):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph(f"Executive Batch Audit Summary - {datetime.now().strftime('%Y-%m-%d')}", styles["Title"]))
    elements.append(Spacer(1, 12))

    data = [["Invoice No", "Carrier", "BoL Ref", "Billed (KES)", "Overcharge (KES)", "Approved Pay (KES)", "Status"]]
    for _, row in df.iterrows():
        data.append([
            str(row.get("Invoice_No", "N/A")),
            str(row.get("Carrier", "N/A"))[:22],
            str(row.get("BoL_Ref", "N/A")),
            f"{row.get('Billed_Total', 0.0):,.2f}",
            f"{row.get('Total_Overcharge', 0.0):,.2f}",
            f"{row.get('Approved_Payable', 0.0):,.2f}",
            str(row.get("Audit_Status", "N/A")),
        ])

    table = Table(data, colWidths=[95, 130, 85, 95, 95, 100, 140])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
        ("GRID", (0, 0), (-1, -1), 0.75, colors.HexColor("#CBD5E1")),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer


# ------------------------------------------------------------------------------
# 4. RELATIONAL TARIFF LOOKUP & 3-WAY RECONCILIATION HELPERS
# ------------------------------------------------------------------------------
def match_contract_tariff(df_inv: pd.DataFrame, df_rates: pd.DataFrame) -> pd.DataFrame:
    """
    Relational key-based lookup matching Carrier (+ Route / Tonnage when present)
    instead of fragile positional row slicing.
    """
    df_rates = df_rates.copy()
    df_rates.columns = [str(c).strip() for c in df_rates.columns]

    carrier_col = next((c for c in df_rates.columns if any(k in c.lower() for k in ["carrier", "vendor", "haulier", "supplier"])), None)
    base_col = next((c for c in df_rates.columns if any(k in c.lower() for k in ["contract_base", "base_rate", "base", "rate", "price", "kes"])), None)
    fuel_col = next((c for c in df_rates.columns if "fuel" in c.lower()), None)
    offload_col = next((c for c in df_rates.columns if any(k in c.lower() for k in ["offload", "handling", "loading"])), None)
    route_col = next((c for c in df_rates.columns if any(k in c.lower() for k in ["route", "corridor", "lane", "destination"])), None)
    tonnage_col = next((c for c in df_rates.columns if any(k in c.lower() for k in ["ton", "capacity", "size"])), None)

    if not base_col:
        num_cols = df_rates.select_dtypes(include=[np.number]).columns
        base_col = num_cols[0] if len(num_cols) > 0 else df_rates.columns[-1]

    for col in [c for c in [base_col, fuel_col, offload_col, tonnage_col] if c]:
        df_rates[col] = pd.to_numeric(
            df_rates[col].astype(str).str.replace(",", "").str.extract(r"([\d\.]+)")[0],
            errors="coerce",
        ).fillna(0.0)

    contract_bases, max_fuels, max_offloads = [], [], []

    for _, inv in df_inv.iterrows():
        inv_carrier = str(inv.get("Carrier", "")).lower().strip()
        inv_route = str(inv.get("Route", "")).lower().strip()
        inv_ton = float(inv.get("Vehicle_Tonnage", 0.0))

        candidates = df_rates.copy()
        if carrier_col and inv_carrier and inv_carrier != "unknown carrier":
            matched_c = candidates[
                candidates[carrier_col].astype(str).str.lower().str.strip().apply(
                    lambda rc: bool(rc) and (rc in inv_carrier or inv_carrier in rc)
                )
            ]
            if not matched_c.empty:
                candidates = matched_c

        if route_col and inv_route and inv_route != "n/a":
            matched_r = candidates[
                candidates[route_col].astype(str).str.lower().str.strip().apply(
                    lambda rr: bool(rr) and (rr in inv_route or inv_route in rr)
                )
            ]
            if not matched_r.empty:
                candidates = matched_r

        if tonnage_col and inv_ton > 0:
            matched_t = candidates[np.isclose(candidates[tonnage_col], inv_ton, atol=1.0)]
            if not matched_t.empty:
                candidates = matched_t

        best = candidates.iloc[0] if not candidates.empty else pd.Series(dtype=float)
        contract_bases.append(float(best[base_col]) if base_col in best else 0.0)
        max_fuels.append(float(best[fuel_col]) if fuel_col and fuel_col in best else np.nan)
        max_offloads.append(float(best[offload_col]) if offload_col and offload_col in best else np.nan)

    df_inv["Contract_Base"] = contract_bases
    df_inv["Max_Fuel"] = max_fuels
    df_inv["Max_Offloading"] = max_offloads
    return df_inv


# ------------------------------------------------------------------------------
# 5. DASHBOARD HEADER & NAVIGATION TABS
# ------------------------------------------------------------------------------
st.markdown("""
    <div style="background: linear-gradient(90deg, #0F172A 0%, #1E3A8A 65%, #2563EB 100%); padding: 18px 26px; border-radius: 12px; color: white; margin-bottom: 18px; box-shadow: 0 4px 14px rgba(15, 23, 42, 0.15);">
        <h1 style="color: #FFFFFF; margin: 0; font-size: 1.75rem;">🚛 Enterprise Freight Audit & Telematics Control Tower</h1>
        <p style="color: #DBEAFE; margin: 4px 0 0 0; font-size: 0.92rem;">Relational Tariff Matching • Line-Item Accessorial Audit • 3-Way GPS/POD Reconciliation • KRA eTIMS Guard</p>
    </div>
""", unsafe_allow_html=True)

tabs = st.tabs([
    "📋 Active Audit Engine",       # Index 0
    "⛽ Fleet & Fuel Telematics",   # Index 1
    "🌍 Cross-Border Audit",        # Index 2
    "⚓ Port Demurrage Tool",       # Index 3
    "📊 Carrier Scorecards",        # Index 4
    "📜 Dispute Ledger",            # Index 5
    "👤 User Profile",              # Index 6
])

with tabs[0]:
    st.sidebar.header("⚙️ Global Audit Parameters")
    usd_fx_rate = st.sidebar.number_input("CBK Benchmark FX Rate (USD to KES)", value=130.0, step=0.5)
    variance_threshold = st.sidebar.slider("Overcharge Ignore Threshold (KES)", 0, 5000, 100)
    vat_rate = st.sidebar.number_input("Statutory VAT Rate (%)", value=16.0, step=1.0) / 100.0
    check_historical_dups = st.sidebar.checkbox("Enable Persistent SQLite Duplicate Guard", value=True)

    st.sidebar.header("📁 Upload Audit Documents")
    pdf_files = st.sidebar.file_uploader("1. Upload PDF Invoices", type=["pdf"], accept_multiple_files=True)
    contract_file = st.sidebar.file_uploader("2. Upload Rate Card (CSV/Excel)", type=["csv", "xlsx"])
    optional_tele_file = st.sidebar.file_uploader("3. Optional GPS/POD Log for 3-Way Match", type=["csv", "xlsx"], key="tab0_tele")

    if optional_tele_file:
        df_t0 = pd.read_csv(optional_tele_file) if optional_tele_file.name.endswith(".csv") else pd.read_excel(optional_tele_file)
        st.session_state["telematics_df"] = df_t0

    if pdf_files and contract_file:
        invoice_records = []
        for pdf in pdf_files:
            invoice_records.extend(parse_pdf_invoice_universal(pdf, usd_fx_rate))

        df_inv = pd.DataFrame(invoice_records)
        df_rates = pd.read_csv(contract_file) if contract_file.name.endswith(".csv") else pd.read_excel(contract_file)

        # 1. Relational Key-Based Rate Matching
        df_merged = match_contract_tariff(df_inv, df_rates)

        # 2. Line-Item Overcharge Calculations (Base + Fuel + Offloading + FX + VAT)
        base_diff = df_merged["Billed_Base"] - df_merged["Contract_Base"]
        df_merged["Base_Overcharge"] = np.where(base_diff > variance_threshold, base_diff, 0.0)

        # Fuel surcharge audit (if rate card specifies Max_Fuel; otherwise 0 overcharge unless > 0 and cap is 0)
        fuel_diff = np.where(
            df_merged["Max_Fuel"].notna(),
            df_merged["Billed_Fuel"] - df_merged["Max_Fuel"].fillna(0.0),
            0.0,
        )
        df_merged["Fuel_Overcharge"] = np.where(fuel_diff > 0, fuel_diff, 0.0)

        # Offloading / handling audit
        offload_diff = np.where(
            df_merged["Max_Offloading"].notna(),
            df_merged["Billed_Offloading"] - df_merged["Max_Offloading"].fillna(0.0),
            0.0,
        )
        df_merged["Offload_Overcharge"] = np.where(offload_diff > 0, offload_diff, 0.0)

        # FX Arbitrage Premium
        fx_diff = np.maximum(0.0, df_merged["Billed_FX_Rate"] - usd_fx_rate)
        df_merged["FX_Overcharge"] = (df_merged["Billed_Base"] / usd_fx_rate) * fx_diff

        # 3. 3-Way Telematics / GPS Cross-Check (if telematics loaded)
        gps_penalties = []
        gps_notes = []
        df_tele_ref = st.session_state.get("telematics_df", pd.DataFrame())
        for _, r in df_merged.iterrows():
            pen = 0.0
            note = "NO_GPS_LOG"
            if not df_tele_ref.empty:
                bol = str(r.get("BoL_Ref", "")).strip()
                trk = str(r.get("Truck_ID", "")).strip()
                match_t = pd.DataFrame()
                for col_cand in ["BoL_Ref", "bol_ref", "waybill_id", "Waybill_ID"]:
                    if col_cand in df_tele_ref.columns and bol and bol != "N/A":
                        match_t = df_tele_ref[df_tele_ref[col_cand].astype(str).str.strip() == bol]
                        if not match_t.empty:
                            break
                if match_t.empty:
                    for col_cand in ["Truck_ID", "truck_reg", "Truck_Plate"]:
                        if col_cand in df_tele_ref.columns and trk and trk != "N/A":
                            match_t = df_tele_ref[df_tele_ref[col_cand].astype(str).str.strip() == trk]
                            if not match_t.empty:
                                break
                if not match_t.empty:
                    tr = match_t.iloc[0]
                    breach = bool(tr.get("Geofence_Breach", tr.get("geofence_deviation_flag", False)))
                    fuel_drop = float(tr.get("Fuel_Drop_Liters", 0.0))
                    note = "GPS_VERIFIED"
                    if breach or fuel_drop > 10.0:
                        pen = round(fuel_drop * 210.0, 2) if fuel_drop > 10.0 else 5000.0
                        note = "GPS_DEVIATION_FLAG"
            gps_penalties.append(pen)
            gps_notes.append(note)

        df_merged["GPS_Penalty"] = gps_penalties
        df_merged["GPS_3Way_Status"] = gps_notes

        # Subtotal & VAT-inclusive Overcharge Calculation
        subtotal_overcharge = (
            df_merged["Base_Overcharge"]
            + df_merged["Fuel_Overcharge"]
            + df_merged["Offload_Overcharge"]
            + df_merged["FX_Overcharge"]
            + df_merged["GPS_Penalty"]
        )

        # Apply VAT overcharge only if the invoice charged VAT (> 0)
        df_merged["VAT_Overcharge"] = np.where(
            df_merged["Billed_VAT"] > 0,
            np.round(subtotal_overcharge * vat_rate, 2),
            0.0,
        )
        df_merged["Total_Overcharge"] = np.round(subtotal_overcharge + df_merged["VAT_Overcharge"], 2)

        # Ensure Billed_Total reflects total invoice value accurately
        df_merged["Billed_Total"] = np.where(
            df_merged["Billed_Total"] > 0,
            df_merged["Billed_Total"],
            df_merged["Billed_Subtotal"] + df_merged["Billed_VAT"],
        )
        df_merged["Approved_Payable"] = np.maximum(0.0, np.round(df_merged["Billed_Total"] - df_merged["Total_Overcharge"], 2))

        # 4. Duplicate Invoice & Split-Billing Guard (Within-Batch + Historical SQLite)
        existing_invs, existing_bols, existing_etims = get_existing_ledger_keys() if check_historical_dups else (set(), set(), set())
        seen_batch_invs, seen_batch_bols = set(), set()
        dup_flags = []
        for _, r in df_merged.iterrows():
            inv_k = str(r["Invoice_No"]).strip().upper()
            bol_k = str(r["BoL_Ref"]).strip().upper()
            etims_k = str(r["eTIMS_CU_Serial"]).strip().upper()

            is_dup = False
            if inv_k in seen_batch_invs or (bol_k not in {"", "N/A"} and bol_k in seen_batch_bols):
                is_dup = True
            if check_historical_dups and (
                inv_k in existing_invs
                or (bol_k not in {"", "N/A"} and bol_k in existing_bols)
                or (etims_k not in {"", "N/A", "MISSING_ETIMS_CU"} and etims_k in existing_etims)
            ):
                is_dup = True

            dup_flags.append(is_dup)
            seen_batch_invs.add(inv_k)
            if bol_k not in {"", "N/A"}:
                seen_batch_bols.add(bol_k)

        df_merged["Is_Duplicate"] = dup_flags

        # 5. Final Audit Status Classification
        conditions = [
            df_merged["Is_Duplicate"],
            (~df_merged["eTIMS_Valid"]),
            (df_merged["GPS_3Way_Status"] == "GPS_DEVIATION_FLAG"),
            (df_merged["Total_Overcharge"] > 0),
        ]
        choices = [
            "FLAGGED_DUPLICATE_BILLING",
            "FLAGGED_INVALID_ETIMS",
            "FLAGGED_3WAY_GPS_BREACH",
            "FLAGGED_OVERCHARGE",
        ]
        df_merged["Audit_Status"] = np.select(conditions, choices, default="PASSED_VERIFIED")

        save_audit_record(df_merged, replace_existing=False)
        st.session_state["audit_data"] = df_merged

    df_active = st.session_state.get("audit_data", pd.DataFrame())

    total_billed_val = 0.0
    total_recovered = 0.0
    total_approved_pay = 0.0
    clean_count = 0
    invalid_etims_count = 0

    if not df_active.empty and "Total_Overcharge" in df_active.columns:
        total_billed_val = float(df_active["Billed_Total"].sum())
        total_recovered = float(df_active["Total_Overcharge"].sum())
        total_approved_pay = float(df_active["Approved_Payable"].sum())
        clean_count = int((df_active["Audit_Status"] == "PASSED_VERIFIED").sum())
        invalid_etims_count = int((~df_active["eTIMS_Valid"]).sum())

    annualized_savings = total_recovered * 12
    st.markdown(f"""
        <div style="background: linear-gradient(90deg, #0F172A 0%, #1E3A8A 100%); color: white; padding: 14px 22px; border-radius: 10px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #334155;">
            <div><strong>💼 Executive Audit Summary:</strong> Gross Billed: <strong>KES {total_billed_val:,.2f}</strong> &nbsp;|&nbsp; Approved Payable: <strong style="color: #93C5FD;">KES {total_approved_pay:,.2f}</strong></div>
            <div>Projected Annualized Savings: <strong style="color: #4ADE80;">KES {annualized_savings:,.2f}</strong></div>
        </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        colored_metric("Invoices Audited", str(len(df_active)), text_color="#1E3A8A", subtitle="Unique parsed docs")
    with c2:
        colored_metric("Verified Clean", str(clean_count), text_color="#0284C7", subtitle="Passed 3-way checks")
    with c3:
        colored_metric("Overcharge Caught", f"KES {total_recovered:,.2f}", text_color="#16A34A", subtitle="Saved via short-pay")
    with c4:
        colored_metric("Approved Payout", f"KES {total_approved_pay:,.2f}", text_color="#334155", subtitle="Net remittance")
    with c5:
        colored_metric("Bad eTIMS", str(invalid_etims_count), text_color="#DC2626", subtitle="KRA non-compliant")

    st.markdown("---")

    with st.expander("🔍 Click to View Forensic Calculation Methodology & Line-Item Formula Breakdown"):
        st.markdown("""
        ### **How Line-Item Overcharges & Net Payable Are Calculated:**
        * **1. Line-Item Discrepancy (Subtotal):**
          $$\text{Subtotal Overcharge} = \max(0, \text{Billed Base} - \text{Contract Base}) + \max(0, \text{Billed Fuel} - \text{Fuel Cap}) + \max(0, \text{Billed Offload} - \text{Offload Cap}) + \text{FX Premium} + \text{GPS Penalty}$$
        * **2. Statutory VAT Adjustment (16%):**
          $$\text{VAT Overcharge} = \text{Subtotal Overcharge} \times 0.16$$
        * **3. Total Recovery & Short-Pay Authorization:**
          $$\text{Total Overcharge} = \text{Subtotal Overcharge} + \text{VAT Overcharge}$$
          $$\text{Approved Payable} = \text{Billed Total} - \text{Total Overcharge}$$
        """)

    c_left, c_right = st.columns([3, 1])
    with c_left:
        st.subheader("📋 Line-Item Audit Extraction Results")
    with c_right:
        if not df_active.empty:
            st.download_button(
                "📥 Executive PDF Report",
                generate_batch_summary_pdf(df_active),
                "Batch_Summary.pdf",
                "application/pdf",
            )

    display_cols = [
        "Invoice_No", "Carrier", "BoL_Ref", "Billed_Base", "Contract_Base",
        "Billed_Fuel", "Billed_Offloading", "Billed_Total", "Approved_Payable",
        "Total_Overcharge", "eTIMS_CU_Serial", "GPS_3Way_Status", "Audit_Status"
    ]
    if not df_active.empty:
        available_cols = [c for c in display_cols if c in df_active.columns]
        st.dataframe(df_active[available_cols], use_container_width=True)
    else:
        st.info("Upload PDF Invoices and a Rate Card in the sidebar to run the line-item audit.")

    if not df_active.empty:
        flagged = df_active[df_active["Audit_Status"] != "PASSED_VERIFIED"].copy()
        valid_flagged_options = [
            str(inv).strip()
            for inv in flagged["Invoice_No"].unique()
            if str(inv).strip() not in ["", "-", "None", "nan", "N/A"]
        ]

        if valid_flagged_options:
            st.subheader("✉️ Dispute & Short-Pay Action Center")
            selected_inv = st.selectbox("Select Flagged Invoice:", valid_flagged_options)
            matched_rows = flagged[flagged["Invoice_No"].astype(str) == selected_inv]
            row = matched_rows.iloc[0]

            email_subject = f"DISPUTE & SHORT-PAY NOTICE: Invoice #{selected_inv} - {row['Carrier']}"
            email_body = f"""Dear Accounts Receivable Team ({row['Carrier']}),

Our automated freight audit flagged billing discrepancies on Invoice #{selected_inv} (BoL Ref: {row['BoL_Ref']}).

Forensic Line-Item Breakdown:
------------------------------------------
- Billed Base Rate: KES {row['Billed_Base']:,.2f} (Contracted: KES {row['Contract_Base']:,.2f})
- Billed Fuel Surcharge: KES {row['Billed_Fuel']:,.2f} (Overcharge: KES {row['Fuel_Overcharge']:,.2f})
- Billed Offloading: KES {row['Billed_Offloading']:,.2f} (Overcharge: KES {row['Offload_Overcharge']:,.2f})
- VAT Adjustment (16%): KES {row['VAT_Overcharge']:,.2f}
- Gross Billed Total: KES {row['Billed_Total']:,.2f}
- Total Audited Deduction: KES {row['Total_Overcharge']:,.2f}
- Approved Net Payable: KES {row['Approved_Payable']:,.2f}

Per our remittance policy, we have issued a Short-Pay Voucher for KES {row['Approved_Payable']:,.2f}. Please issue a credit note for KES {row['Total_Overcharge']:,.2f}.

Best regards,
Freight Audit Team ({st.session_state['username'].title()})
"""
            whatsapp_text = (
                f"Hello {row['Carrier']} Team. Re: Invoice #{selected_inv} (BoL: {row['BoL_Ref']}). "
                f"Our audit flagged KES {row['Total_Overcharge']:,.2f} in overcharges. "
                f"Approved net payable is KES {row['Approved_Payable']:,.2f}."
            )
            whatsapp_url = f"https://wa.me/?text={urllib.parse.quote(whatsapp_text)}"

            with st.expander("✉️ Preview Dispute Notice & Remittance Options", expanded=True):
                st.text_input("Subject:", value=email_subject, disabled=True)
                st.text_area("Message Body:", value=email_body, height=200)
                st.markdown(f"[📲 Send Dispute Summary via WhatsApp]({whatsapp_url})", unsafe_allow_html=True)

            c_btn1, c_btn2, c_btn3 = st.columns(3)
            with c_btn1:
                st.download_button(
                    "📑 Download Debit Note (PDF)",
                    generate_pdf_debit_note(row),
                    f"Debit_Note_{selected_inv}.pdf",
                )
            with c_btn2:
                st.download_button(
                    "💳 Download Short-Pay Voucher (PDF)",
                    generate_short_pay_voucher_pdf(row),
                    f"Short_Pay_Voucher_{selected_inv}.pdf",
                )
            with c_btn3:
                if st.session_state["role"] in ["admin", "finance"]:
                    if st.button("🚀 Log & Dispatch Dispute"):
                        update_dispute_status(selected_inv, "DISPUTE_SENT")
                        st.success(f"Dispute logged for Invoice {selected_inv}!")


# ⛽ FLEET & FUEL TELEMATICS MONITOR (NORMALIZED SCHEMA SUPPORT)
with tabs[1]:
    st.header("⛽ Real-Time Fleet & Fuel Telematics Monitor")
    st.info("Monitors fuel pilferage, route deviations, excessive idling, and syncs with Active Audit 3-Way Matching.")

    col_a, col_b, col_c = st.columns(3)
    fuel_price = col_a.number_input("Fuel Cost Rate (KES / Liter)", value=210.0, step=5.0)
    idle_fuel_rate = col_b.number_input("Idle Burn Rate (Liters / Hour)", value=2.5, step=0.5)
    max_idle_threshold = col_c.slider("Max Allowed Idle Time (Hours)", 0.5, 5.0, 2.0)

    st.markdown("---")
    telematics_file = st.file_uploader("Upload Telematics/GPS Log (.csv, .xlsx)", type=["csv", "xlsx"], key="telematics_upload")

    df_tele = st.session_state.get("telematics_df", pd.DataFrame())
    if telematics_file:
        try:
            df_tele = pd.read_csv(telematics_file) if telematics_file.name.endswith(".csv") else pd.read_excel(telematics_file)
            st.session_state["telematics_df"] = df_tele
            st.success("Telematics log parsed & synced with 3-Way Audit Engine!")
        except Exception as e:
            st.error(f"Error parsing log: {str(e)}")

    if not df_tele.empty:
        # Normalize column aliases so both schema conventions work seamlessly
        df_t = df_tele.copy()
        if "Fuel_Drop_Liters" not in df_t.columns and {"fuel_consumed_liters", "expected_fuel_liters"}.issubset(df_t.columns):
            df_t["Fuel_Drop_Liters"] = np.maximum(0.0, df_t["fuel_consumed_liters"] - df_t["expected_fuel_liters"])
        if "Idle_Hours" not in df_t.columns and "engine_idle_minutes" in df_t.columns:
            df_t["Idle_Hours"] = df_t["engine_idle_minutes"] / 60.0
        if "Actual_KM" not in df_t.columns and "gps_distance_km" in df_t.columns:
            df_t["Actual_KM"] = df_t["gps_distance_km"]
        if "Truck_ID" not in df_t.columns and "truck_reg" in df_t.columns:
            df_t["Truck_ID"] = df_t["truck_reg"]
        if "Driver" not in df_t.columns:
            df_t["Driver"] = "Assigned Driver"
        if "Geofence_Breach" not in df_t.columns and "geofence_deviation_flag" in df_t.columns:
            df_t["Geofence_Breach"] = df_t["geofence_deviation_flag"]

        siphoning_df = df_t[df_t["Fuel_Drop_Liters"] > 10.0] if "Fuel_Drop_Liters" in df_t.columns else pd.DataFrame()
        idling_df = df_t[df_t["Idle_Hours"] > max_idle_threshold] if "Idle_Hours" in df_t.columns else pd.DataFrame()
        route_dev_df = (
            df_t[df_t["Actual_KM"] > (df_t["Planned_KM"] * 1.10)]
            if {"Actual_KM", "Planned_KM"}.issubset(df_t.columns)
            else (df_t[df_t["Geofence_Breach"] == True] if "Geofence_Breach" in df_t.columns else pd.DataFrame())
        )
        maintenance_df = df_t[df_t["Weekly_Total_KM"] > 1200] if "Weekly_Total_KM" in df_t.columns else pd.DataFrame()

        excess_idle_hours = (
            (idling_df["Idle_Hours"] - max_idle_threshold).sum()
            if not idling_df.empty
            else 0.0
        )
        total_fuel_lost_liters = (
            (siphoning_df["Fuel_Drop_Liters"].sum() if not siphoning_df.empty else 0.0)
            + (excess_idle_hours * idle_fuel_rate)
        )
        total_cash_loss_kes = total_fuel_lost_liters * fuel_price

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            colored_metric("🚨 Fuel Anomalies", str(len(siphoning_df)), text_color="#DC2626")
        with m2:
            colored_metric("⏱️ Excessive Idling", str(len(idling_df)), text_color="#D97706")
        with m3:
            colored_metric("🛣️ Route Deviations", str(len(route_dev_df)), text_color="#D97706")
        with m4:
            colored_metric("💰 Est. Cash Leakage", f"KES {total_cash_loss_kes:,.2f}", text_color="#DC2626")

        st.markdown("---")
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("📊 Fuel Variance & Pilferage Alerts")
            if not siphoning_df.empty and "Truck_ID" in siphoning_df.columns:
                fig_fuel = px.bar(
                    siphoning_df,
                    x="Truck_ID",
                    y="Fuel_Drop_Liters",
                    color="Driver",
                    title="Excess Fuel Burn / Siphoning (Liters)",
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                st.plotly_chart(fig_fuel, use_container_width=True)
            else:
                st.success("No fuel siphoning anomalies detected.")

        with col_right:
            st.subheader("🛣️ Route Distance Drift vs Planned")
            if {"Planned_KM", "Actual_KM"}.issubset(df_t.columns):
                fig_route = px.scatter(
                    df_t,
                    x="Planned_KM",
                    y="Actual_KM",
                    color="Geofence_Breach" if "Geofence_Breach" in df_t.columns else None,
                    hover_data=["Truck_ID", "Driver"],
                    title="Planned vs Actual Distance (KM)",
                )
                st.plotly_chart(fig_route, use_container_width=True)
            else:
                st.info("Upload a log with Planned_KM and Actual_KM to view distance scatter plot.")

        if not maintenance_df.empty:
            st.subheader("🛠️ Preventive Maintenance Escalations")
            for _, row in maintenance_df.iterrows():
                st.warning(
                    f"⚠️ **High Wear Alert ({row.get('Truck_ID', 'N/A')})**: {row.get('Weekly_Total_KM', 0)} KM logged."
                )

        st.subheader("📋 Ingested Telematics Ledger")
        st.dataframe(df_t, use_container_width=True)
    else:
        st.info("👆 Upload a Telematics/GPS Log (.csv or .xlsx) above to activate fleet tracking and 3-way invoice sync.")


# 🌍 CROSS-BORDER AUDIT TAB (CORRECTED FX DIRECTION MATH)
with tabs[2]:
    st.subheader("🌍 East & Southern Africa Cross-Border Freight Audit")
    col1, col2, col3 = st.columns(3)

    with col1:
        corridor = st.selectbox("Select Transport Corridor", [
            "Northern Corridor (Mombasa - Kampala - Kigali)",
            "Central Corridor (Dar es Salaam - Mutukula - Kigali/Bujumbura)",
            "North-South Corridor (Tanzania/Kenya - Tunduma/Nakonde - Zambia)",
        ])
        origin_country = st.selectbox("Origin Country", ["Kenya (KRA)", "Tanzania (TRA)", "Uganda (URA)", "Zambia (ZRA)"])

    with col2:
        billed_currency = st.selectbox("Invoice Currency", ["USD", "KES", "UGX", "TZS", "ZMW"])
        billed_amount_usd = st.number_input("Base Contract Freight Amount (USD)", value=5000.0)
        carrier_fx = st.number_input("Carrier FX Conversion Rate Applied (Local/USD)", value=138.50)

    with col3:
        cb_rates = {"USD": 1.0, "KES": 129.50, "UGX": 3680.00, "TZS": 2650.00, "ZMW": 26.50}
        benchmark_fx = cb_rates.get(billed_currency, 1.0)
        st.metric("Official CBK/Central Bank Rate", f"{benchmark_fx} {billed_currency}/USD")
        border_delay_days = st.number_input("Border Processing Delay (Days)", min_value=0, value=3)

    tax_system_map = {
        "Kenya (KRA)": "eTIMS CU Serial Number",
        "Uganda (URA)": "EFRIS Invoice Number / QR",
        "Tanzania (TRA)": "EFD / VFD Receipt Verification",
        "Zambia (ZRA)": "Smart Invoice Mark / Clearance Code",
    }

    st.markdown("---")
    st.markdown(f"**Required Tax Compliance Check:** `{tax_system_map[origin_country]}`")

    # Correct FX Arbitrage math: Carrier converts USD freight at inflated carrier_fx instead of benchmark_fx
    if billed_currency != "USD" and benchmark_fx > 0:
        billed_local = billed_amount_usd * carrier_fx
        expected_local = billed_amount_usd * benchmark_fx
        fx_overcharge_local = max(0.0, billed_local - expected_local)
        fx_discrepancy_usd = fx_overcharge_local / benchmark_fx
    else:
        fx_discrepancy_usd = 0.0

    chargeable_border_days = max(0, border_delay_days - 1)
    border_demurrage_claim_usd = chargeable_border_days * 150.0
    total_cross_border_claim_usd = fx_discrepancy_usd + border_demurrage_claim_usd

    m1, m2, m3 = st.columns(3)
    m1.metric("FX Arbitrage Claim", f"USD {fx_discrepancy_usd:,.2f}")
    m2.metric("Border Demurrage Variance", f"USD {border_demurrage_claim_usd:,.2f}")
    m3.metric("Total Cross-Border Claim", f"USD {total_cross_border_claim_usd:,.2f}")

    if total_cross_border_claim_usd > 0:
        st.warning(f"⚠️ Cross-border billing variance detected: Total Claim USD {total_cross_border_claim_usd:,.2f}")


# ⚓ MOMBASA PORT & ICD DEMURRAGE CALCULATOR TAB
with tabs[3]:
    st.subheader("⚓ Mombasa Port & ICD Demurrage Auditor")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        shipment_type = st.selectbox("Shipment Destination Type", ["Local Import (7 Free Days)", "Transit Cargo (14 Free Days)"])
        gate_out_date = st.date_input("Discharge Date at Port", value=datetime.today() - timedelta(days=12))
        return_date = st.date_input("Empty Container Return Date", value=datetime.today())
        container_count = st.number_input("Number of Containers", min_value=1, value=2)

    with col_d2:
        daily_demurrage_usd = st.number_input("Daily Demurrage Rate per Container (USD)", value=40.0)
        billed_demurrage_kes = st.number_input("Demurrage Amount Billed by Carrier (KES)", value=65000.0)

    free_days = 7 if "Local" in shipment_type else 14
    total_days = max(0, (return_date - gate_out_date).days)
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
        st.error(f"⚠️ Flagged Demurrage Overcharge: Carrier overbilled by KES {demurrage_overcharge:,.2f} (Expected: KES {expected_demurrage_kes:,.2f}).")


# 📊 CARRIER SCORECARDS & MULTI-CARRIER LEADERBOARD TAB
with tabs[4]:
    st.subheader("📊 Multi-Carrier Comparison & Overcharge Leaderboard")
    df_active = st.session_state.get("audit_data", pd.DataFrame())
    if not df_active.empty and "Carrier" in df_active.columns:
        summary_df = (
            df_active.groupby("Carrier")
            .agg(
                Invoices=("Invoice_No", "count"),
                Gross_Billed_KES=("Billed_Total", "sum"),
                Total_Overcharge_KES=("Total_Overcharge", "sum"),
                Approved_Payable_KES=("Approved_Payable", "sum"),
            )
            .reset_index()
            .sort_values(by="Total_Overcharge_KES", ascending=False)
        )
        fig = px.bar(
            summary_df,
            x="Carrier",
            y="Total_Overcharge_KES",
            title="Total Financial Overcharges Caught by Carrier (KES)",
            color="Carrier",
            text_auto=",.2f",
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(summary_df, use_container_width=True)
    else:
        st.info("Upload invoices on Tab 0 to generate carrier scorecards.")


# 📜 PERSISTENT AUDIT TRAIL & DISPUTE HISTORY TAB
with tabs[5]:
    st.subheader("📜 Persistent Audit Trail & Duplicate Guard Ledger")
    c_l1, c_l2 = st.columns([4, 1])
    with c_l2:
        if st.session_state["role"] == "admin":
            if st.button("🗑️ Clear Ledger History"):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM audit_ledger")
                conn.commit()
                conn.close()
                st.rerun()

    conn = sqlite3.connect(DB_FILE)
    df_ledger = pd.read_sql_query(
        "SELECT timestamp, invoice_no, carrier, bol_ref, etims_cu_serial, billed_total, total_overcharge, approved_payable, audit_status, dispute_status FROM audit_ledger ORDER BY id DESC",
        conn,
    )
    conn.close()
    if not df_ledger.empty:
        st.dataframe(df_ledger, use_container_width=True)
    else:
        st.info("No records found in audit ledger.")


# 👤 USER PROFILE TAB
with tabs[6]:
    st.subheader("👤 User Profile & System Capabilities")
    st.write(f"**Logged in user:** {st.session_state['username']} | **Role:** {st.session_state['role'].upper()}")
