import pandas as pd
import streamlit as st

st.set_page_config(page_title="Kenyan Freight Audit Dashboard", layout="wide")

st.title("🚛 Freight Audit & Reconciliation Dashboard")
st.caption("Automated Freight Rate Auditing & Discrepancy Tracking")

# Sample Freight Data
data = [
    {
        "Invoice No": "INV-2026-8840",
        "Carrier": "Swara Express Logistics Ltd",
        "BoL Ref": "BOL-KE-8840",
        "Billed Base": 120000,
        "Contract Base": 120000,
        "Total Billed": 162400,
        "Status": "PASSED_VERIFIED",
    },
    {
        "Invoice No": "INV-2026-9011",
        "Carrier": "Rift Transport Ltd",
        "BoL Ref": "BOL-KE-9102",
        "Billed Base": 145000,
        "Contract Base": 120000,
        "Total Billed": 191400,
        "Status": "FLAGGED_DISCREPANCY",
    },
]

df = pd.DataFrame(data)

# KPI Cards
col1, col2, col3 = st.columns(3)
col1.metric("Total Invoices Audited", len(df))
col2.metric("Verified Clean", len(df[df["Status"] == "PASSED_VERIFIED"]))
col3.metric(
    "Flagged Overcharges", len(df[df["Status"] == "FLAGGED_DISCREPANCY"])
)

st.subheader("Invoice Records")
st.dataframe(df, use_container_width=True)

# Dispute Email Action
st.subheader("⚠️ Action Center: Generate Dispute Draft")
flagged = df[df["Status"] == "FLAGGED_DISCREPANCY"].iloc[0]

st.warning(
    f"Discrepancy detected on **{flagged['Invoice No']}** ({flagged['Carrier']}): "
    f"Billed base (KES {flagged['Billed Base']:,}) exceeds contracted rate (KES {flagged['Contract Base']:,})."
)

if st.button("Generate Dispute Email"):
    variance = flagged["Billed Base"] - flagged["Contract Base"]
    email_body = f"""
    To: accounts@{flagged['Carrier'].lower().replace(' ', '')}.co.ke
    Subject: Payment Hold / Rate Discrepancy Notice - Invoice #{flagged['Invoice No']}

    Dear Accounts Team,

    Our automated audit system flagged a rate mismatch on Invoice #{flagged['Invoice No']} (Ref: {flagged['BoL Ref']}).

    - Billed Base Rate: KES {flagged['Billed Base']:,}
    - Contracted Rate: KES {flagged['Contract Base']:,}
    - Variance / Overcharge: KES {variance:,}

    Please issue a revised eTIMS invoice matching the contracted rate card to proceed with disbursement.
    """
    st.code(email_body, language="text")
