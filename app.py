import streamlit as st
import pandas as pd
from datetime import date, datetime

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
    
    # Get unique customers from the B2B invoice list
    unique_customers = invoice_df['Customer Name'].unique()
    
    for customer in unique_customers:
        # Get all invoices for this customer, oldest first
        cust_invs = invoice_df[invoice_df['Customer Name'] == customer].sort_values('Invoice Date')
        
        # Get ledger balance from summary (default to 0 if customer not found)
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
st.markdown(f"**System Date:** {date.today().strftime('%d %b %Y')}")

with st.sidebar:
    st.header("Upload Data")
    inv_file = st.file_uploader("1. Upload Invoice CSV", type="csv")
    sum_file = st.file_uploader("2. Upload Customer Balance Summary CSV", type="csv")
    
    st.divider()
    credit_days = st.number_input("Standard Credit Days", value=30)

if inv_file and sum_file:
    # Load Data
    df_inv = pd.read_csv(inv_file)
    df_sum = pd.read_csv(sum_file)
    
    # 1. CLEANING & FILTERING
    # Filter for Regular Businesses only
    df_inv = df_inv[df_inv['GST Treatment'] == 'business_gst'].copy()
    
    # Convert dates and handle errors
    df_inv['Invoice Date'] = pd.to_datetime(df_inv['Invoice Date'], errors='coerce')
    df_inv = df_inv.dropna(subset=['Invoice Date']) # Remove rows with invalid dates
    
    # 2. CALCULATION LOGIC
    # Transit Days + Credit Days
    df_inv['Transit Days'] = df_inv['Place of Supply'].map(POS_DELAY).fillna(5)
    
    # GRN Date = Invoice Date + Transit
    df_inv['GRN Date'] = df_inv['Invoice Date'] + pd.to_timedelta(df_inv['Transit Days'], unit='D')
    
    # True Due Date = GRN Date + Credit Days
    df_inv['True Due Date'] = df_inv['GRN Date'] + pd.to_timedelta(credit_days, unit='D')
    
    # 3. PAYMENT RECONCILIATION (FIFO)
    df_reconciled = reconcile_payments(df_inv, df_sum)
    
    # 4. AGING CALCULATION
    # Aging Days = System Date - True Due Date
    today = pd.Timestamp(date.today())
    df_reconciled['Aging Days'] = (today - df_reconciled['True Due Date']).dt.days
    
    # --- FILTERS ---
    customers = ["All Customers"] + sorted(df_reconciled['Customer Name'].unique().tolist())
    selected_cust = st.sidebar.selectbox("Filter by Customer", customers)
    
    display_df = df_reconciled.copy()
    if selected_cust != "All Customers":
        display_df = display_df[display_df['Customer Name'] == selected_cust]

    # --- METRICS ---
    m1, m2, m3 = st.columns(3)
    
    total_ledger = df_sum[df_sum['customer_name'].isin(df_inv['Customer Name'])]['closing_balance'].sum()
    if selected_cust != "All Customers":
        total_ledger = df_sum.loc[df_sum['customer_name'] == selected_cust, 'closing_balance'].sum()
        
    m1.metric("Ledger Balance", f"₹{total_ledger:,.2f}")
    
    # Only calculate metrics for invoices that actually have an effective balance
    overdue_only = display_df[(display_df['Effective Balance'] > 0) & (display_df['Aging Days'] > 0)]
    m2.metric("Overdue Amount", f"₹{overdue_only['Effective Balance'].sum():,.2f}")
    
    avg_age = overdue_only['Aging Days'].mean() if not overdue_only.empty else 0
    m3.metric("Avg. Aging Days", f"{int(avg_age)} Days")

    # --- TABLE VIEW ---
    st.subheader("Invoice Aging Table")
    
    # Highlight logic: Red for overdue balance, Green for cleared/current
    def style_aging(row):
        if row['Effective Balance'] > 0 and row['Aging Days'] > 0:
            return ['background-color: #ffe6e6'] * len(row) # Light Red
        elif row['Effective Balance'] <= 0:
            return ['color: #999999'] * len(row) # Grey out cleared invoices
        return [''] * len(row)

    final_cols = [
        'Invoice Number', 'Customer Name', 'Place of Supply', 
        'Invoice Date', 'GRN Date', 'True Due Date', 
        'Balance', 'Effective Balance', 'Aging Days'
    ]
    
    st.dataframe(
        display_df[final_cols].style.apply(style_aging, axis=1)
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
    st.subheader("Aging Bucket Distribution")
    bins = [-999, 0, 15, 30, 60, 9999]
    labels = ['Not Due', '1-15 Days', '16-30 Days', '31-60 Days', '>60 Days']
    display_df['Bucket'] = pd.cut(display_df['Aging Days'], bins=bins, labels=labels)
    
    # Only show buckets for invoices with a remaining balance
    chart_data = display_df[display_df['Effective Balance'] > 0].groupby('Bucket')['Effective Balance'].sum().reindex(labels)
    st.bar_chart(chart_data)

else:
    st.info("💡 Please upload both files to generate the B2B reconciled aging report.")
