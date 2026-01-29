import json
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from services.worker.db import get_conn
from services.worker.drive import get_drive_service, load_drive_schema, ensure_folder, move_file

st.set_page_config(page_title="Family Archive Curator", layout="wide")

service = get_drive_service()
schema = load_drive_schema(service)


def load_assets(status: str | None = None):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM assets WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM assets ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_asset_status(asset_id: str, status: str):
    conn = get_conn()
    conn.execute("UPDATE assets SET status = ? WHERE asset_id = ?", (status, asset_id))
    conn.execute("UPDATE media SET status = ? WHERE drive_id = (SELECT drive_file_id FROM assets WHERE asset_id = ?)", (status, asset_id))
    conn.commit()
    conn.close()


def approve_asset(asset: dict, decade: str | None):
    drive_id = asset["drive_file_id"]
    mime_type = asset.get("mime_type") or ""
    decade_label = decade or asset.get("decade") or "Unknown"

    if mime_type.startswith("video/"):
        parent = ensure_folder(service, schema["ARCHIVE_VIDEOS"], decade_label)
    else:
        parent = ensure_folder(service, schema["ARCHIVE_ORIGINALS"], decade_label)

    move_file(service, drive_id, parent)
    update_asset_status(asset["asset_id"], "approved")


st.sidebar.title("Curator Dashboard")
section = st.sidebar.radio("View", ["Needs Review", "Batch Review", "Duplicates", "People", "Search"]) 

if section == "Needs Review":
    st.header("Needs Review")
    assets = load_assets("needs_review")
    if not assets:
        st.info("No assets awaiting review.")
    else:
        df = pd.DataFrame(assets)
        selected = st.multiselect("Select assets", df["asset_id"].tolist())
        decade = st.text_input("Decade for approval (optional)")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve Selected"):
                for asset_id in selected:
                    asset = next(a for a in assets if a["asset_id"] == asset_id)
                    approve_asset(asset, decade)
                st.success("Approved selected assets.")
        with col2:
            if st.button("Reject Selected"):
                for asset_id in selected:
                    update_asset_status(asset_id, "rejected")
                st.warning("Rejected selected assets.")

        st.dataframe(df[["asset_id", "original_filename", "status", "created_at"]])

if section == "Batch Review":
    st.header("Batch Review")
    batch_id = st.text_input("Batch ID")
    if batch_id:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM assets WHERE batch_id = ?", (batch_id,)).fetchall()
        conn.close()
        assets = [dict(r) for r in rows]
        st.dataframe(pd.DataFrame(assets))

if section == "Duplicates":
    st.header("Possible Duplicates")
    conn = get_conn()
    rows = conn.execute("SELECT * FROM duplicates ORDER BY id DESC").fetchall()
    conn.close()
    if not rows:
        st.info("No duplicates flagged.")
    else:
        dup_df = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(dup_df)
        dup_id = st.number_input("Duplicate ID to review", min_value=0, step=1)
        if dup_id:
            conn = get_conn()
            dup_row = conn.execute("SELECT * FROM duplicates WHERE id = ?", (dup_id,)).fetchone()
            if dup_row:
                asset_a = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (dup_row["asset_id"],)).fetchone()
                asset_b = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (dup_row["duplicate_of"],)).fetchone()
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Asset A")
                    st.json(dict(asset_a) if asset_a else {})
                with col2:
                    st.subheader("Asset B")
                    st.json(dict(asset_b) if asset_b else {})
            conn.close()

if section == "People":
    st.header("People Clusters")
    conn = get_conn()
    clusters = conn.execute("SELECT * FROM clusters ORDER BY id DESC").fetchall()
    conn.close()
    if not clusters:
        st.info("No clusters yet.")
    else:
        df = pd.DataFrame([dict(r) for r in clusters])
        st.dataframe(df)
        cluster_id = st.number_input("Cluster ID", min_value=1, step=1)
        new_name = st.text_input("New name")
        if st.button("Rename Cluster"):
            conn = get_conn()
            conn.execute("UPDATE clusters SET name = ? WHERE id = ?", (new_name, cluster_id))
            conn.commit()
            conn.close()
            st.success("Cluster renamed.")

        st.subheader("Merge Clusters")
        source_id = st.number_input("Source Cluster ID", min_value=1, step=1, key="merge_source")
        target_id = st.number_input("Target Cluster ID", min_value=1, step=1, key="merge_target")
        if st.button("Merge"):
            conn = get_conn()
            conn.execute("UPDATE faces SET cluster_id = ? WHERE cluster_id = ?", (target_id, source_id))
            conn.execute("DELETE FROM clusters WHERE id = ?", (source_id,))
            conn.commit()
            conn.close()
            st.success("Clusters merged.")

if section == "Search":
    st.header("Search")
    query = st.text_input("Search caption or filename")
    if query:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM assets WHERE caption LIKE ? OR original_filename LIKE ?",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        conn.close()
        st.dataframe(pd.DataFrame([dict(r) for r in rows]))
