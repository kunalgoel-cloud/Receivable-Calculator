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
    """
    Adjusts individual invoice balances based on the Ledger Closing Balance 
    using FIFO (First-In, First-Out) logic.
    """
    reconciled_rows = []
    unique_customers = invoice_df['Customer Name'].unique()
    
    for customer in unique_customers:
        cust_invs = invoice_df[invoice_df['Customer Name'] == customer].sort_values('Invoice Date')
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
st.markdown(f"**Calculation Basis:** System Date ({current_date.strftime('%d %b %Y')}) | Default 30-Day Credit")

with st.sidebar:
    st.header("1. Upload Data")
    inv_file = st.file_uploader("Upload Invoice CSV", type="csv")
    sum_file = st.file_uploader("Upload Customer Balance Summary CSV", type="csv")
    
    st.divider()
    st.header("2. Global Settings")
    credit_days = st.number_input("Standard Credit Days", value=30)

if inv_file and sum_file:
    # Load Data
    df_inv = pd.read_csv(inv_file)
    df_sum = pd.read_csv(sum_file)
    
    # 1. PRE-PROCESSING
    # Filter for Regular Businesses only
    df_inv = df_inv[df_inv['GST Treatment'] == 'business_gst'].copy()
    df_inv['Invoice Date'] = pd.to_datetime(df_inv['Invoice Date'], errors='coerce')
    df_inv = df_inv.dropna(subset=['Invoice Date'])
    
    # Calculate Dates
    df_inv['Transit Days'] = df_inv['Place of Supply'].map(POS_DELAY).fillna(5)
    df_inv['GRN Date'] = df_inv['Invoice Date'] + pd.to_timedelta(df_inv['Transit Days'], unit='D')
    df_inv['True Due Date'] = df_inv['GRN Date'] + pd.to_timedelta(credit_days, unit='D')
    
    # 2. FIFO RECONCILIATION
    df_reconciled = reconcile_payments(df_inv, df_sum)
    
    # 3. AGING CALCULATION (System Date - True Due Date)
    today_ts = pd.Timestamp(current_date)
    df_reconciled['Aging Days'] = (today_ts - df_reconciled['True Due Date']).dt.days
    
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("3. View Filters")
    
    # Customer Filter
    customers = ["All Customers"] + sorted(df_reconciled['Customer Name'].unique().tolist())
    selected_cust = st.sidebar.selectbox("Filter by Customer", customers)
    
    # Status Filter (Added back)
    statuses = ["All Statuses"] + sorted(df_reconciled['Invoice Status'].unique().tolist())
    selected_status = st.sidebar.selectbox("Filter by Invoice Status", statuses)

    # Apply Filters
    display_df = df_reconciled.copy()
    if selected_cust != "All Customers":
        display_df = display_df[display_df['Customer Name'] == selected_cust]
    if selected_status != "All Statuses":
        display_df = display_df[display_df['Invoice Status'] == selected_status]

    # --- METRICS ---
    m1, m2, m3 = st.columns(3)
    
    # Ledger Balance Metric
    relevant_customers = df_reconciled['Customer Name'].unique() if selected_cust == "All Customers" else [selected_cust]
    total_ledger = df_sum[df_sum['customer_name'].isin(relevant_customers)]['closing_balance'].sum()
    m1.metric("Ledger Balance", f"₹{total_ledger:,.2f}")
    
    # Overdue Metric (Only where balance exists and date is past)
    overdue_mask = (display_df['Effective Balance'] > 0) & (display_df['Aging Days'] > 0)
    overdue_amt = display_df[overdue_mask]['Effective Balance'].sum()
    m2.metric("Overdue Amount", f"₹{overdue_amt:,.2f}", delta_color="inverse")
    
    avg_age = display_df[overdue_mask]['Aging Days'].mean() if not display_df[overdue_mask].empty else 0
    m3.metric("Avg. Aging Days", f"{int(avg_age)} Days")

    # --- TABLE VIEW ---
    st.subheader("Invoice Aging Table")
    
    def style_rows(row):
        # Red if overdue and unpaid
        if row['Effective Balance'] > 0 and row['Aging Days'] > 0:
            return ['background-color: #ffe6e6'] * len(row)
        # Grey if cleared by Ledger
        elif row['Effective Balance'] <= 0:
            return ['color: #999999'] * len(row)
        return [''] * len(row)

    final_cols = [
        'Invoice Number', 'Customer Name', 'Invoice Status', 'Invoice Date', 
        'GRN Date', 'True Due Date', 'Balance', 'Effective Balance', 'Aging Days'
    ]
    
    st.dataframe(
        display_df[final_cols].style.apply(style_rows, axis=1)
        .format({
            "Balance": "₹{:.2f}", 
            "Effective Balance": "₹{:.2f}", 
            "Invoice Date": "{:%d-%m-%Y}",
            "GRN Date": "{:%d-%m-%Y}",
            "True Due Date": "{:%d-%m-%Y}",
            "Aging Days": "{:,.0f}"
        }),
        use_container_width=True
    )

    # --- CHART ---
    st.subheader("Reconciled Aging Distribution")
    bins = [-999, 0, 15, 30, 60, 9999]
    labels = ['Current', '1-15 Days', '16-30 Days', '31-60 Days', '>60 Days']
    display_df['Bucket'] = pd.cut(display_df['Aging Days'], bins=bins, labels=labels)
    chart_data = display_df[display_df['Effective Balance'] > 0].groupby('Bucket')['Effective Balance'].sum().reindex(labels)
    st.bar_chart(chart_data)

else:
    st.info("👋 Upload your **Invoice CSV** and **Balance Summary** to start the B2B reconciliation.")
