import re
import numpy as np
import pandas as pd
import pdfplumber
import streamlit as st

st.set_page_config(
    page_title="Kenyan Freight Audit & Reconciliation", layout="wide"
)

st.title("🚛 Kenyan Freight Audit & Reconciliation Dashboard")
st.caption(
    "Automated PDF Invoice Parsing, eTIMS Verification & Rate Card Reconciliation"
)


# REGEX EXTRACTION ENGINE FOR PDF INVOICES
def parse_pdf_invoice(file_obj):
    extracted_text = ""
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            extracted_text += (page.extract_text() or "") + "\n"

    # Regex patterns for key Kenyan logistics fields
    inv_match = re.search(r"Invoice\s*#?\s*:?\s*([A-Za-z0-9-]+)", extracted_text)
    carrier_match = re.search(
        r"(Swara Express|Rift Transport|Siginon|Freight In Time)", extracted_text
    )
    bol_match = re.search(r"BoL\s*Ref\s*:?\s*([A-Za-z0-9-]+)", extracted_text)
    etims_match = re.search(r"(KRA[A-Za-z0-9]{8,15})", extracted_text)
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

    def clean_num(match_obj):
        return (
            float(match_obj.group(1).replace(",", "")) if match_obj else 0.0
        )

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


# SIDEBAR FILE UPLOADS
st.sidebar.header("📁 Upload Documents")
pdf_files = st.sidebar.file_uploader(
    "1. Upload PDF Carrier Invoices (Bulk Supported)",
    type=["pdf"],
    accept_multiple_files=True,
)
contract_file = st.sidebar.file_uploader(
    "2. Upload Rate Card (CSV/Excel)", type=["csv", "xlsx"]
)

# DEMO SETUP / INSTRUCTIONS
if not pdf_files or not contract_file:
    st.info(
        "👈 Please upload one or more PDF carrier invoices alongside your Contract Rate Card in the sidebar."
    )

    with st.expander("ℹ️ Rate Card Format Instructions"):
        st.write(
            "Your Contract Rate Card (CSV/Excel) should contain these columns:"
        )
        st.code(
            "Carrier, Contract_Base, Max_Fuel_Allowance, Max_Offloading_Allowance",
            language="text",
        )

# AUDIT & MATCHING PROCESSING
if pdf_files and contract_file:
    # Parse all uploaded PDF invoices into a structured Dataframe
    invoice_records = [parse_pdf_invoice(pdf) for pdf in pdf_files]
    df_inv = pd.DataFrame(invoice_records)

    # Load Contract Rate Card
    df_rates = (
        pd.read_csv(contract_file)
        if contract_file.name.endswith(".csv")
        else pd.read_excel(contract_file)
    )

    # Merge Dataframes on Carrier Name
    df_merged = pd.merge(df_inv, df_rates, on="Carrier", how="left").fillna(0)

    # Calculate Itemized Variances
    df_merged["Base_Variance"] = np.maximum(
        0, df_merged["Billed_Base"] - df_merged["Contract_Base"]
    )
    df_merged["Fuel_Variance"] = np.maximum(
        0, df_merged["Billed_Fuel"] - df_merged["Max_Fuel_Allowance"]
    )
    df_merged["Offloading_Variance"] = np.maximum(
        0,
        df_merged["Billed_Offloading"]
        - df_merged["Max_Offloading_Allowance"],
    )

    # Total Overcharge
    df_merged["Total_Overcharge"] = (
        df_merged["Base_Variance"]
        + df_merged["Fuel_Variance"]
        + df_merged["Offloading_Variance"]
    )

    # eTIMS & 16% KRA VAT Verification Logic
    df_merged["Expected_Subtotal"] = (
        df_merged["Contract_Base"]
        + df_merged["Max_Fuel_Allowance"]
        + df_merged["Max_Offloading_Allowance"]
    )
    df_merged["Expected_VAT"] = df_merged["Expected_Subtotal"] * 0.16
    df_merged["VAT_Discrepancy"] = np.abs(
        df_merged["Billed_VAT"] - df_merged["Expected_VAT"]
    )

    df_merged["eTIMS_Valid"] = df_merged["eTIMS_CU_Serial"].astype(
        str
    ).str.startswith("KRA") & (df_merged["VAT_Discrepancy"] < 1.0)

    # Assign Audit Status Flag
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

    # DASHBOARD KPI METRICS
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("PDF Invoices Processed", len(df_merged))
    col2.metric(
        "Verified Clean",
        len(df_merged[df_merged["Audit_Status"] == "PASSED_VERIFIED"]),
    )
    col3.metric(
        "Flagged Discrepancies",
        len(df_merged[df_merged["Audit_Status"] != "PASSED_VERIFIED"]),
    )
    col4.metric(
        "Total Overcharges Identified",
        f"KES {df_merged['Total_Overcharge'].sum():,.2f}",
    )

    st.markdown("---")

    # AUDIT RESULTS TABLE
    st.subheader("📋 Extraction & Audit Summary")
    st.dataframe(
        df_merged[
            [
                "Invoice_No",
                "Carrier",
                "BoL_Ref",
                "eTIMS_CU_Serial",
                "Billed_Base",
                "Contract_Base",
                "Total_Overcharge",
                "Audit_Status",
            ]
        ],
        use_container_width=True,
    )

    # REPORT EXPORT BUTTON
    csv_data = df_merged.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Full Reconciliation Report (CSV)",
        data=csv_data,
        file_name="Audit_Reconciliation_Report.csv",
        mime="text/csv",
    )

    st.markdown("---")

    # DISPUTE ACTION CENTER
    st.subheader("⚠️ Action Center: Generate Carrier Dispute Notices")
    flagged = df_merged[df_merged["Audit_Status"] != "PASSED_VERIFIED"]

    if not flagged.empty:
        selected_inv = st.selectbox(
            "Select Flagged Invoice to Generate Dispute Draft:",
            flagged["Invoice_No"],
        )
        row = flagged[flagged["Invoice_No"] == selected_inv].iloc[0]

        dispute_email = f"""TO: Accounts Payable - {row['Carrier']}
DATE: {pd.Timestamp.now().strftime('%Y-%m-%d')}
SUBJECT: Payment Hold / Rate Discrepancy Notice - Invoice #{row['Invoice_No']}

Dear Accounts Team,

Our automated freight audit system has processed PDF invoice #{row['Invoice_No']} (BoL Ref: {row['BoL_Ref']}) and detected compliance/rate discrepancies against our contract card.

AUDIT BREAKDOWN:
--------------------------------------------------
- Base Freight Rate: Billed KES {row['Billed_Base']:,.2f} | Contracted KES {row['Contract_Base']:,.2f}
- Fuel Surcharge: Billed KES {row['Billed_Fuel']:,.2f} | Allowance KES {row['Max_Fuel_Allowance']:,.2f}
- Offloading Fee: Billed KES {row['Billed_Offloading']:,.2f} | Allowance KES {row['Max_Offloading_Allowance']:,.2f}

COMPLIANCE & VARIANCE SUMMARY:
--------------------------------------------------
- Total Overcharge Variance: KES {row['Total_Overcharge']:,.2f}
- eTIMS CU Serial Number: {row['eTIMS_CU_Serial']} ({'VALID' if row['eTIMS_Valid'] else 'INVALID OR VAT 16% MISMATCH'})

REQUIRED ACTION:
Please issue a credit note or a corrected eTIMS invoice reflecting the contracted rate of KES {row['Expected_Subtotal']:,.2f} + 16% KRA VAT.

Regards,
Logistics & Audit Team
"""
        st.code(dispute_email, language="text")

        st.download_button(
            label=f"📄 Download Dispute Draft for {row['Invoice_No']} (.txt)",
            data=dispute_email,
            file_name=f"Dispute_Notice_{row['Invoice_No']}.txt",
            mime="text/plain",
        )
    else:
        st.success("🎉 All uploaded PDF invoices passed audit verification!")
