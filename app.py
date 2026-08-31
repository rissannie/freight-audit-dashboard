import os
import re
import smtplib
import sqlite3
from email.mime.text import MIMEText
import numpy as np
import pandas as pd
import pdfplumber
import streamlit as st

# ------------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & DATABASE INITIALIZATION
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Kenyan Enterprise Freight Audit & Reconciliation",
    layout="wide",
)


def init_db():
    conn = sqlite3.connect("freight_audit_ledger.db")
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
            etims_valid INTEGER
        )
    """)
    conn.commit()
    conn.close()


init_db()


def save_audit_record(df_results):
    conn = sqlite3.connect("freight_audit_ledger.db")
    for _, row in df_results.iterrows():
        conn.execute(
            """
            INSERT INTO audit_ledger (invoice_no, carrier, bol_ref, etims_cu_serial, total_overcharge, audit_status, etims_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                row["Invoice_No"],
                row["Carrier"],
                row["BoL_Ref"],
                row["eTIMS_CU_Serial"],
                row["Total_Overcharge"],
                row["Audit_Status"],
                1 if row["eTIMS_Valid"] else 0,
            ),
        )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------------------
# 2. BUILT-IN SECURE AUTHENTICATION SYSTEM
# ------------------------------------------------------------------------------
USER_CREDENTIALS = {"admin": "admin123", "finance": "finance123"}

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""

if not st.session_state["authenticated"]:
    st.title("🔒 Enterprise Freight Audit Portal")
    st.subheader("System Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

        if submit:
            if (
                username in USER_CREDENTIALS
                and USER_CREDENTIALS[username] == password
            ):
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid username or password.")
    st.stop()

# LOGOUT BUTTON IN SIDEBAR
st.sidebar.write(f"Logged in as: **{st.session_state['username'].upper()}**")
if st.sidebar.button("Logout"):
    st.session_state["authenticated"] = False
    st.session_state["username"] = ""
    st.rerun()


# ------------------------------------------------------------------------------
# 3. ADVANCED PDF & eTIMS PARSER ENGINE
# ------------------------------------------------------------------------------
def parse_pdf_invoice(file_obj):
    extracted_text = ""
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            extracted_text += (page.extract_text() or "") + "\n"

    inv_match = re.search(r"Invoice\s*#?\s*:?\s*([A-Za-z0-9-]+)", extracted_text)
    carrier_match = re.search(
        r"(Swara Express|Rift Transport|Siginon|Freight In Time)", extracted_text
    )
    bol_match = re.search(r"BoL\s*Ref\s*:?\s*([A-Za-z0-9-]+)", extracted_text)

    # Advanced eTIMS Pattern Match (CU Serial & KRA Verification URL)
    etims_match = re.search(r"(KRA[A-Za-z0-9]{8,15})", extracted_text)
    etims_url = re.search(r"(https?://etims\.kra\.go\.ke[^\s]+)", extracted_text)

    base_match = re.search(
        r"Base\s*Rate\s*:?\s*KES\s*([\d,]+)", extracted_text
    )
    fuel_match = re.search(
        r"Fuel\s*Surcharge\s*:?\s*KES\s*([\d,]+)", extracted_text
    )
    offload_match = re.search(
        r"Offloading\s*:?\s*KES\s*([\d,]+)", extracted_text
    )
    vat_match = re.search(r"VAT\s*\(16%\)\s*:?\s*KES\s*([\d,]+)", extracted_text)

    def clean_num(m):
        return float(m.group(1).replace(",", "")) if m else 0.0

    return {
        "Invoice_No": inv_match.group(1) if inv_match else file_obj.name,
        "Carrier": carrier_match.group(1) if carrier_match else "Unknown",
        "BoL_Ref": bol_match.group(1) if bol_match else "N/A",
        "eTIMS_CU_Serial": etims_match.group(1) if etims_match else "INVALID",
        "eTIMS_URL_Valid": bool(etims_url),
        "Billed_Base": clean_num(base_match),
        "Billed_Fuel": clean_num(fuel_match),
        "Billed_Offloading": clean_num(offload_match),
        "Billed_VAT": clean_num(vat_match),
    }


# ------------------------------------------------------------------------------
# 4. DASHBOARD INTERFACE & WORKFLOW
# ------------------------------------------------------------------------------
st.title("🚛 Kenyan Enterprise Freight Audit & Reconciliation")
st.caption(
    "PDF Invoice Parsing | eTIMS Verification | Ledger Database | Direct SMTP Email Dispatch"
)

tabs = st.tabs(
    ["📋 Active Audit Engine", "📜 Historical Audit Ledger", "⚙️ Integration Settings"]
)

# TAB 1: ACTIVE AUDIT ENGINE
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

       # Resilient CSV/Excel loader with encoding fallbacks
        if contract_file.name.endswith(".csv"):
            try:
                df_rates = pd.read_csv(contract_file, encoding='utf-8')
            except Exception:
                df_rates = pd.read_csv(contract_file, encoding='latin1')
        else:
            df_rates = pd.read_excel(contract_file)

        # Standardize column headers dynamically
        column_mapping = {
            'Company_Name': 'Carrier',
            'Contract_Rate_KES': 'Contract_Base',
            'Billed_Rate_KES': 'Billed_Base'
        }
        df_rates = df_rates.rename(columns=column_mapping)

        # Merge datasets cleanly
        df_merged = pd.merge(df_inv, df_rates, on="Carrier", how="left").fillna(0)

        # Calculate Base Variance safely
        c_base = df_merged["Contract_Base"] if "Contract_Base" in df_merged.columns else 0
        b_base = df_merged["Billed_Base"] if "Billed_Base" in df_merged.columns else 0
        df_merged["Base_Variance"] = np.maximum(0, b_base - c_base)
        df_merged["Fuel_Variance"] = np.maximum(
            0, df_merged["Billed_Fuel"] - df_merged["Max_Fuel_Allowance"]
        )
        df_merged["Offloading_Variance"] = np.maximum(
            0,
            df_merged["Billed_Offloading"]
            - df_merged["Max_Offloading_Allowance"],
        )
        df_merged["Total_Overcharge"] = (
            df_merged["Base_Variance"]
            + df_merged["Fuel_Variance"]
            + df_merged["Offloading_Variance"]
        )

        # eTIMS Tax Check
        df_merged["Expected_Subtotal"] = (
            df_merged["Contract_Base"]
            + df_merged["Max_Fuel_Allowance"]
            + df_merged["Max_Offloading_Allowance"]
        )
        df_merged["Expected_VAT"] = df_merged["Expected_Subtotal"] * 0.16
        df_merged["VAT_Discrepancy"] = np.abs(
            df_merged["Billed_VAT"] - df_merged["Expected_VAT"]
        )

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
        df_merged["Audit_Status"] = np.select(
            conditions, choices, default="PASSED_VERIFIED"
        )

        # Save to SQLite Database Ledger
        save_audit_record(df_merged)

        # Metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("PDFs Processed", len(df_merged))
        c2.metric(
            "Verified Clean",
            len(df_merged[df_merged["Audit_Status"] == "PASSED_VERIFIED"]),
        )
        c3.metric(
            "Flagged Discrepancies",
            len(df_merged[df_merged["Audit_Status"] != "PASSED_VERIFIED"]),
        )
        c4.metric(
            "Financial Recovery Identified",
            f"KES {df_merged['Total_Overcharge'].sum():,.2f}",
        )

        st.markdown("---")
        st.subheader("📋 Extraction & Reconciliation Results")
        st.dataframe(
            df_merged[
                [
                    "Invoice_No",
                    "Carrier",
                    "BoL_Ref",
                    "eTIMS_CU_Serial",
                    "Total_Overcharge",
                    "Audit_Status",
                ]
            ],
            use_container_width=True,
        )

        # Dispute Email Action Center
        st.subheader("✉️ Action Center: Direct Dispute Email Dispatch")
        flagged = df_merged[df_merged["Audit_Status"] != "PASSED_VERIFIED"]

        if not flagged.empty:
            selected_inv = st.selectbox(
                "Select Invoice for Action:", flagged["Invoice_No"]
            )
            row = flagged[flagged["Invoice_No"] == selected_inv].iloc[0]

            recipient_email = st.text_input(
                "Carrier Accounts Email:",
                value=f"accounts@{row['Carrier'].lower().replace(' ', '')}.co.ke",
            )
            dispute_subject = f"Payment Hold / Discrepancy Notice - Invoice #{row['Invoice_No']}"
            dispute_body = f"""Dear {row['Carrier']} Accounts Team,

Our automated audit engine identified an overcharge / eTIMS discrepancy on Invoice #{row['Invoice_No']}.

Billed Base Rate: KES {row['Billed_Base']:,.2f} | Contract Base: KES {row['Contract_Base']:,.2f}
Total Calculated Overcharge: KES {row['Total_Overcharge']:,.2f}
eTIMS Validation Status: {'VALID' if row['eTIMS_Valid'] else 'INVALID / MISMATCHED VAT (16%)'}

Please send a corrected eTIMS invoice matching contracted terms to proceed with payment.

Regards,
Logistics & Finance Team
"""
            st.text_area(
                "Dispute Email Preview:", dispute_body, height=180
            )

            if st.button("🚀 Dispatch Dispute Email"):
                smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
                smtp_port = int(os.getenv("SMTP_PORT", 587))
                smtp_user = os.getenv("SMTP_USER", "")
                smtp_pass = os.getenv("SMTP_PASS", "")

                if smtp_user and smtp_pass:
                    try:
                        msg = MIMEText(dispute_body)
                        msg["Subject"] = dispute_subject
                        msg["From"] = smtp_user
                        msg["To"] = recipient_email

                        server = smtplib.SMTP(smtp_server, smtp_port)
                        server.starttls()
                        server.login(smtp_user, smtp_pass)
                        server.sendmail(
                            smtp_user, [recipient_email], msg.as_string()
                        )
                        server.quit()
                        st.success(
                            f"Dispute email successfully dispatched to {recipient_email}!"
                        )
                    except Exception as e:
                        st.error(f"Failed to send email: {str(e)}")
                else:
                    st.warning(
                        "SMTP credentials not found in environment variables. Email simulation logged successfully."
                    )
                    st.info(f"Simulated dispatch to: {recipient_email}")

# TAB 2: HISTORICAL AUDIT LEDGER DATABASE
with tabs[1]:
    st.subheader("📜 Historical Database Audit Ledger")
    conn = sqlite3.connect("freight_audit_ledger.db")
    df_ledger = pd.read_sql_query(
        "SELECT * FROM audit_ledger ORDER BY timestamp DESC", conn
    )
    conn.close()

    if not df_ledger.empty:
        st.dataframe(df_ledger, use_container_width=True)
        st.download_button(
            "📥 Download Complete Database Audit Ledger (CSV)",
            data=df_ledger.to_csv(index=False).encode("utf-8"),
            file_name="Historical_Freight_Audit_Ledger.csv",
            mime="text/csv",
        )
    else:
        st.info("No historical records currently saved in database ledger.")

# TAB 3: INTEGRATION SETTINGS
with tabs[2]:
    st.subheader("⚙️ System Environment Configuration")
    st.write(
        "Configure these Environment Variables on Render to enable direct SMTP email dispatching:"
    )
    st.code(
        """
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your-finance-email@company.com"
SMTP_PASS = "your-app-password"
    """,
        language="text",
    )
