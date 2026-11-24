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
# 1. PAGE CONFIGURATION & EXECUTIVE COLOR PALETTE
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Enterprise Freight Audit & Telematics",
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    /* Executive Slate & Navy Palette */
    .stApp {
        background: linear-gradient(180deg, #F1F5F9 0%, #E2E8F0 100%);
        color: #0F172A;
    }
    .main .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2.5rem;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0F172A 0%, #1E293B 100%);
        border-right: 1px solid #334155;
    }
    [data-testid="stSidebar"] * {
        color: #F8FAFC !important;
    }
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] textarea {
        color: #0F172A !important;
        background-color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background-color: rgba(30, 58, 138, 0.35) !important;
        border: 1px dashed #60A5FA !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
    }
    [data-testid="stMetric"] {
        width: 100% !important;
        background-color: #FFFFFF;
        padding: 12px 16px;
        border-radius: 10px;
        border: 1px solid #CBD5E1;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background-color: #FFFFFF;
        padding: 6px;
        border-radius: 10px;
        border: 1px solid #CBD5E1;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #F8FAFC;
        color: #334155;
        border-radius: 7px;
        padding: 6px 14px;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #1E3A8A 0%, #0F172A 100%) !important;
        color: #FFFFFF !important;
    }
    .exec-hero {
        background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 65%, #1D4ED8 100%);
        color: #FFFFFF;
        padding: 16px 22px;
        border-radius: 12px;
        margin-bottom: 18px;
        border: 1px solid #3B82F6;
        box-shadow: 0 6px 16px rgba(15, 23, 42, 0.14);
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
    }
    h1, h2, h3 {
        color: #0F172A;
        letter-spacing: -0.01em;
    }
    </style>
""", unsafe_allow_html=True)

DB_FILE = "freight_audit_ledger.db"


def colored_metric(label, value, text_color="#1E3A8A"):
    st.markdown(f"""
        <div style="background-color: #FFFFFF; padding: 14px 18px; border-radius: 10px; border: 1px solid #CBD5E1; box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);">
            <div style="color: #475569; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px;">{label}</div>
            <div style="color: {text_color}; font-size: 1.45rem; font-weight: 800; line-height: 1.25; word-break: break-word;">{value}</div>
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
            route_key TEXT,
            bol_ref TEXT,
            etims_cu_serial TEXT,
            billed_total REAL,
            approved_payable REAL,
            total_overcharge REAL,
            audit_status TEXT,
            etims_valid INTEGER,
            dispute_status TEXT DEFAULT 'PENDING'
        )
    """)

    cursor.execute("PRAGMA table_info(audit_ledger)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    migrations = {
        "route_key": "TEXT DEFAULT 'DEFAULT'",
        "billed_total": "REAL DEFAULT 0.0",
        "approved_payable": "REAL DEFAULT 0.0",
    }
    for col, col_def in migrations.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE audit_ledger ADD COLUMN {col} {col_def}")

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
        cursor.executemany("INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)", default_users)

    conn.commit()
    conn.close()


init_db()


def check_historical_duplicates(df_results: pd.DataFrame) -> pd.Series:
    """Checks incoming invoices against persistent audit_ledger history."""
    conn = sqlite3.connect(DB_FILE)
    hist_df = pd.read_sql_query(
        "SELECT invoice_no, bol_ref, etims_cu_serial, billed_total FROM audit_ledger",
        conn,
    )
    conn.close()

    seen_invoices = set()
    seen_bols = set()
    seen_etims_amounts = set()

    if not hist_df.empty:
        seen_invoices.update(hist_df["invoice_no"].dropna().astype(str).str.strip().str.upper())
        for b in hist_df["bol_ref"].dropna().astype(str).str.strip().str.upper():
            if b not in ("", "N/A", "NONE", "NAN"):
                seen_bols.add(b)
        for _, hrow in hist_df.iterrows():
            serial = str(hrow.get("etims_cu_serial", "")).strip().upper()
            amt = round(float(hrow.get("billed_total") or 0.0), 2)
            if serial and serial not in ("MISSING_ETIMS_CU", "N/A", "NONE", "NAN"):
                seen_etims_amounts.add((serial, amt))

    dup_flags = []
    batch_invoices = set()
    batch_bols = set()
    batch_etims_amounts = set()

    for _, row in df_results.iterrows():
        inv = str(row.get("Invoice_No", "")).strip().upper()
        bol = str(row.get("BoL_Ref", "")).strip().upper()
        serial = str(row.get("eTIMS_CU_Serial", "")).strip().upper()
        amt = round(float(row.get("Billed_Total", row.get("Billed_Base", 0.0)) or 0.0), 2)

        is_dup = False
        if inv and inv not in ("N/A", "NONE", "NAN") and (inv in seen_invoices or inv in batch_invoices):
            is_dup = True
        if bol and bol not in ("", "N/A", "NONE", "NAN") and (bol in seen_bols or bol in batch_bols):
            is_dup = True
        if serial and serial not in ("MISSING_ETIMS_CU", "N/A", "NONE", "NAN"):
            if (serial, amt) in seen_etims_amounts or (serial, amt) in batch_etims_amounts:
                is_dup = True

        dup_flags.append(is_dup)
        if inv and inv not in ("N/A", "NONE", "NAN"):
            batch_invoices.add(inv)
        if bol and bol not in ("", "N/A", "NONE", "NAN"):
            batch_bols.add(bol)
        if serial and serial not in
