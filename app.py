import streamlit as st
import pandas as pd
from datetime import date, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="B2B Reconciled Aging", layout="wide")

# Shipping Delay Mapping (Mumbai Origin)
POS_DELAY = {
    'MH': 2, 'GJ': 3, 'GA': 3, 'KA': 5, 'TN': 5, 'KL': 6, 'TS': 5, 'AP': 5, 
    'DL': 5, 'HR': 5, 'PB': 5, 'UP': 6, 'RJ': 4, 'WB': 7, 'OR': 7, 'JH': 7, 
    'BH': 7, 'AS': 10, 'MN': 12
}

def reconcile_payments(invoice_df, summary_df):
    reconciled_rows = []
    unique_customers = invoice_df['Customer Name'].unique()
    
    for customer in unique_customers:
        # Get all invoices for this customer, oldest first
        cust_invs = invoice_df[invoice_df['Customer Name'] == customer].sort_values('Invoice Date')
        # Get ledger balance from summary
        ledger_bal = summary_df.loc[summary_df['customer_name'] == customer, 'closing_balance'].sum()
        
        remaining_bal = ledger_bal
        for _, row in cust_invs.iterrows():
            if remaining_bal <= 0:
                row['Effective Balance'] = 0.0
            elif remaining_bal >= row['Balance']:
                row['Effective Balance'] = float(row['Balance'])
                remaining_bal -= row['Balance']
            else:
                row['Effective Balance'] = float(remaining_bal)
                remaining_bal = 0
            reconciled_rows.append(row)
            
    return pd.DataFrame(reconciled_rows)

# --- UI ---
st.title("🛡️ B2B Reconciled Aging Dashboard")
current_date = date.today()
st.markdown(f"**Calculation Basis:** System Date ({current_date.strftime('%d %b %Y')})")

with st.sidebar:
    st.header("1. Upload Data")
    inv_file = st.file_uploader("Upload Invoice CSV", type="csv")
    sum_file = st.file_uploader("Upload Customer Balance Summary CSV", type="csv")
    st.divider()
    st.header("2. Global Settings")
    credit_days = st.number_input("Standard Credit Days", value=30)

if inv_file and sum_file:
    df_raw = pd.read_csv(inv_file)
    df_sum = pd.read_csv(sum_file)
    
    # 1. CONSOLIDATE DUPLICATE INVOICE ROWS (Group by Invoice Number)
    df_inv = df_raw.groupby('Invoice Number').agg({
        'Invoice Date': 'first',
        'Customer Name': 'first',
        'Invoice Status': 'first',
        'Balance': 'sum',
        'GST Treatment': 'first',
        'Place of Supply': 'first'
    }).reset_index()

    # 2. PRE-PROCESSING
    df_inv = df_inv[df_inv['GST Treatment'] == 'business_gst'].copy()
    df_inv['Invoice Date'] = pd.to_datetime(df_inv['Invoice Date'], errors='coerce')
    df_inv = df_inv.dropna(subset=['Invoice Date'])
    
    # Date Calculations
    df_inv['Transit Days'] = df_inv['Place of Supply'].map(POS_DELAY).fillna(5)
    df_inv['GRN Date'] = df_inv['Invoice Date'] + pd.to_timedelta(df_inv['Transit Days'], unit='D')
    df_inv['True Due Date'] = df_inv['GRN Date'] + pd.to_timedelta(credit_days, unit='D')
    
    # 3. FIFO RECONCILIATION
    df_reconciled = reconcile_payments(df_inv, df_sum)
    
    # 4. AGING CALCULATION
    today_ts = pd.Timestamp(current_date)
    df_reconciled['Aging Days'] = (today_ts - df_reconciled['True Due Date']).dt.days
    
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("3. View Filters")
    
    # Search Bar for Invoice Number
    search_query = st.sidebar.text_input("🔍 Search Invoice Number", placeholder="e.g. MH/25-26/...")

    # Multiple Customer Filter
    all_customers = sorted(df_reconciled['Customer Name'].unique().tolist())
    selected_custs = st.sidebar.multiselect("Filter by Customer(s)", options=all_customers)
    
    # Multiple Status Filter (Updated to Multiselect)
    all_statuses = sorted(df_reconciled['Invoice Status'].unique().tolist())
    selected_statuses = st.sidebar.multiselect("Filter by Status(es)", options=all_statuses)

    # --- APPLY FILTERS ---
    display_df = df_reconciled.copy()
    
    if search_query:
        display_df = display_df[display_df['Invoice Number'].str.contains(search_query, case=False, na=False)]
    
    if selected_custs:
        display_df = display_df[display_df['Customer Name'].isin(selected_custs)]
        
    if selected_statuses:
        display_df = display_df[display_df['Invoice Status'].isin(selected_statuses)]

    # --- METRICS ---
    m1, m2, m3 = st.columns(3)
    
    # Calculate Ledger Balance for selected context
    relevant_customers = display_df['Customer Name'].unique()
    total_ledger = df_sum[df_sum['customer_name'].isin(relevant_customers)]['closing_balance'].sum()
    
    m1.metric("Ledger Balance (Context)", f"₹{total_ledger:,.2f}")
    
    overdue_mask = (display_df['Effective Balance'] > 0) & (display_df['Aging Days'] > 0)
    overdue_amt = display_df[overdue_mask]['Effective Balance'].sum()
    m2.metric("Overdue Amount", f"₹{overdue_amt:,.2f}")
    
    avg_age = display_df[overdue_mask]['Aging Days'].mean() if not display_df[overdue_mask].empty else 0
    m3.metric("Avg. Aging Days", f"{int(avg_age)} Days")

    # --- TABLE VIEW ---
    st.subheader(f"Invoice Aging Table ({len(display_df)} Invoices Shown)")
    
    def style_rows(row):
        if row['Effective Balance'] > 0 and row['Aging Days'] > 0:
            return ['background-color: #ffe6e6'] * len(row) # Light Red for Overdue
        elif row['Effective Balance'] <= 0:
            return ['color: #999999'] * len(row) # Grey for Paid/Adjusted
        return [''] * len(row)

    final_cols = [
        'Invoice Number', 'Customer Name', 'Invoice Status', 'Invoice Date', 
        'GRN Date', 'True Due Date', 'Balance', 'Effective Balance', 'Aging Days'
    ]
    
    st.dataframe(
        display_df[final_cols].style.apply(style_rows, axis=1)
        .format({
            "Balance": "₹{:.2f}", "Effective Balance": "₹{:.2f}", 
            "Invoice Date": "{:%d-%m-%Y}", "GRN Date": "{:%d-%m-%Y}",
            "True Due Date": "{:%d-%m-%Y}", "Aging Days": "{:,.0f}"
        }),
        use_container_width=True
    )

    # --- CHART ---
    st.subheader("Overdue Distribution (Reconciled Balance)")
    bins = [-999, 0, 15, 30, 60, 9999]
    labels = ['Not Due', '1-15 Days', '16-30 Days', '31-60 Days', '>60 Days']
    display_df['Bucket'] = pd.cut(display_df['Aging Days'], bins=bins, labels=labels)
    chart_data = display_df[display_df['Effective Balance'] > 0].groupby('Bucket')['Effective Balance'].sum().reindex(labels)
    st.bar_chart(chart_data)

else:
    st.info("👋 Upload your CSV files to start the B2B reconciliation.")
