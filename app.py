import streamlit as st
import pandas as pd
from datetime import date, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="B2B Reconciled Aging", layout="wide")

# Hard-coded GRN Delay Days (Mumbai Origin)
POS_DELAY = {
    'MH': 2, 'GJ': 3, 'GA': 3, 'KA': 5, 'TN': 5, 'KL': 6, 'TS': 5, 'AP': 5, 
    'DL': 5, 'HR': 5, 'PB': 5, 'UP': 6, 'RJ': 4, 'WB': 7, 'OR': 7, 'JH': 7, 
    'BH': 7, 'AS': 10, 'MN': 12
}

def reconcile_payments(invoice_df, summary_df):
    """
    Allocates the Ledger Balance (from Summary) to individual invoices
    using First-In, First-Out (FIFO) logic.
    """
    reconciled_rows = []
    unique_customers = invoice_df['Customer Name'].unique()
    
    for customer in unique_customers:
        # Get customer's invoices sorted by date (oldest first)
        cust_invs = invoice_df[invoice_df['Customer Name'] == customer].sort_values('Invoice Date')
        
        # Get actual ledger balance (ground truth)
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

# --- UI HEADER ---
st.title("🛡️ B2B Reconciled Aging Dashboard")
current_date = date.today()
st.markdown(f"**Calculation Basis:** System Date ({current_date.strftime('%d-%m-%Y')}) | **Format:** Day-Month-Year")

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Data Upload")
    inv_file = st.file_uploader("Upload Invoice CSV", type="csv")
    sum_file = st.file_uploader("Upload Customer Balance Summary CSV", type="csv")
    
    st.divider()
    st.header("2. Settings")
    # Using ddmmyy logic for parsing
    credit_days = st.number_input("Standard Credit Days", value=30)
    
    st.divider()
    st.header("3. Filters")
    search_query = st.text_input("🔍 Search Invoice Number")

if inv_file and sum_file:
    # Read files
    df_raw = pd.read_csv(inv_file)
    df_sum = pd.read_csv(sum_file)
    
    # 1. CONSOLIDATION (Group multi-item invoices into one row)
    # We sum the 'Balance' to get the total invoice debt
    df_inv = df_raw.groupby('Invoice Number').agg({
        'Invoice Date': 'first',
        'Customer Name': 'first',
        'Invoice Status': 'first',
        'Balance': 'sum',
        'GST Treatment': 'first',
        'Place of Supply': 'first'
    }).reset_index()

    # 2. FILTER & DATE PARSING (DD/MM/YY)
    df_inv = df_inv[df_inv['GST Treatment'] == 'business_gst'].copy()
    
    # Strictly parse dd/mm/yy format
    df_inv['Invoice Date'] = pd.to_datetime(df_inv['Invoice Date'], format='%d/%m/%y', dayfirst=True, errors='coerce')
    df_inv = df_inv.dropna(subset=['Invoice Date'])
    
    # 3. DATE CALCULATIONS
    df_inv['Transit Days'] = df_inv['Place of Supply'].map(POS_DELAY).fillna(5)
    df_inv['GRN Date'] = df_inv['Invoice Date'] + pd.to_timedelta(df_inv['Transit Days'], unit='D')
    df_inv['True Due Date'] = df_inv['GRN Date'] + pd.to_timedelta(credit_days, unit='D')
    
    # 4. FIFO RECONCILIATION
    df_reconciled = reconcile_payments(df_inv, df_sum)
    
    # 5. AGING CALCULATION
    today_ts = pd.Timestamp(current_date)
    df_reconciled['Aging Days'] = (today_ts - df_reconciled['True Due Date']).dt.days
    
    # --- DYNAMIC MULTI-SELECT FILTERS ---
    all_custs = sorted(df_reconciled['Customer Name'].unique().tolist())
    selected_custs = st.sidebar.multiselect("Filter Customers", options=all_custs)
    
    all_stats = sorted(df_reconciled['Invoice Status'].unique().tolist())
    selected_stats = st.sidebar.multiselect("Filter Statuses", options=all_stats)

    # Apply all filters
    display_df = df_reconciled.copy()
    if search_query:
        display_df = display_df[display_df['Invoice Number'].str.contains(search_query, case=False, na=False)]
    if selected_custs:
        display_df = display_df[display_df['Customer Name'].isin(selected_custs)]
    if selected_stats:
        display_df = display_df[display_df['Invoice Status'].isin(selected_statuses)]

    # --- KPI METRICS ---
    m1, m2, m3 = st.columns(3)
    
    # Context-aware Ledger Balance
    rel_custs = display_df['Customer Name'].unique()
    total_ledger = df_sum[df_sum['customer_name'].isin(rel_custs)]['closing_balance'].sum()
    m1.metric("Ledger Balance (Context)", f"₹{total_ledger:,.2f}")
    
    overdue_mask = (display_df['Effective Balance'] > 0) & (display_df['Aging Days'] > 0)
    overdue_amt = display_df[overdue_mask]['Effective Balance'].sum()
    m2.metric("Overdue Amount", f"₹{overdue_amt:,.2f}")
    
    avg_age = display_df[overdue_mask]['Aging Days'].mean() if not display_df[overdue_mask].empty else 0
    m3.metric("Avg. Aging Days", f"{int(avg_age)}")

    # --- RESULTS TABLE ---
    st.subheader(f"Detailed Aging Report ({len(display_df)} Invoices)")
    
    def highlight_aging(row):
        # Red row if overdue and unpaid
        if row['Effective Balance'] > 0 and row['Aging Days'] > 0:
            return ['background-color: #ffe6e6'] * len(row)
        # Grey text if invoice is mathematically "paid" via Ledger Balance
        elif row['Effective Balance'] <= 0:
            return ['color: #b0b0b0'] * len(row)
        return [''] * len(row)

    final_cols = [
        'Invoice Number', 'Customer Name', 'Invoice Status', 'Invoice Date', 
        'GRN Date', 'True Due Date', 'Balance', 'Effective Balance', 'Aging Days'
    ]
    
    st.dataframe(
        display_df[final_cols].style.apply(highlight_aging, axis=1)
        .format({
            "Balance": "₹{:.2f}", "Effective Balance": "₹{:.2f}", 
            "Invoice Date": "{:%d-%m-%Y}", "GRN Date": "{:%d-%m-%Y}",
            "True Due Date": "{:%d-%m-%Y}", "Aging Days": "{:,.0f}"
        }),
        use_container_width=True
    )

    # --- AGING CHART ---
    st.subheader("Overdue Concentration")
    bins = [-999, 0, 15, 30, 60, 9999]
    labels = ['Current', '1-15 Days', '16-30 Days', '31-60 Days', '>60 Days']
    display_df['Bucket'] = pd.cut(display_df['Aging Days'], bins=bins, labels=labels)
    chart_data = display_df[display_df['Effective Balance'] > 0].groupby('Bucket')['Effective Balance'].sum().reindex(labels)
    st.bar_chart(chart_data)

else:
    st.info("💡 Please upload both files to view the B2B aging analysis.")
