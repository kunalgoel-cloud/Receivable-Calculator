import streamlit as st
import pandas as pd
from datetime import date, timedelta

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="B2B GRN Aging Dashboard", layout="wide")

# Hard-coded GRN Delay Days based on Place of Supply (Shipping from Mumbai)
POS_DELAY_MAPPING = {
    'MH': 2,   # Maharashtra
    'GJ': 3,   # Gujarat
    'GA': 3,   # Goa
    'KA': 5,   # Karnataka
    'TN': 5,   # Tamil Nadu
    'KL': 6,   # Kerala
    'TS': 5,   # Telangana
    'AP': 5,   # Andhra Pradesh
    'DL': 5,   # Delhi
    'HR': 5,   # Haryana
    'PB': 5,   # Punjab
    'UP': 6,   # Uttar Pradesh
    'RJ': 4,   # Rajasthan
    'WB': 7,   # West Bengal
    'OR': 7,   # Odisha
    'JH': 7,   # Jharkhand
    'BH': 7,   # Bihar
    'AS': 10,  # Assam (NE)
    'MN': 12,  # Manipur (NE)
}
DEFAULT_DELAY = 5 # Fallback for any POS not explicitly listed

def calculate_grn_date(row):
    delay = POS_DELAY_MAPPING.get(row['Place of Supply'], DEFAULT_DELAY)
    return row['Invoice Date'] + timedelta(days=delay)

# --- UI HEADER ---
st.title("📊 B2B Receivables: GRN-Based Aging")
st.markdown("""
**Logic:** Filters for `business_gst` only. 
Aging is calculated as: `Today - (Invoice Date + Shipping Transit Days)`.
""")

# --- FILE UPLOAD ---
uploaded_file = st.file_uploader("Upload Zoho Books Invoice CSV", type="csv")

if uploaded_file:
    # Load data
    df = pd.read_csv(uploaded_file)
    
    # 1. FILTER: Only Regular Businesses
    df = df[df['GST Treatment'] == 'business_gst'].copy()
    
    if df.empty:
        st.error("No 'business_gst' records found in the uploaded file.")
    else:
        # 2. PRE-PROCESSING
        df['Invoice Date'] = pd.to_datetime(df['Invoice Date'])
        
        # Apply the hard-coded GRN logic
        df['GRN Date'] = df.apply(calculate_grn_date, axis=1)
        
        # Calculate Aging (Today - GRN Date)
        today = pd.to_datetime(date.today())
        df['Aging Days (GRN)'] = (today - df['GRN Date']).dt.days
        
        # 3. SIDEBAR FILTERS
        st.sidebar.header("Dashboard Filters")
        
        # Customer Filter
        customers = ["All Customers"] + sorted(df['Customer Name'].unique().tolist())
        selected_cust = st.sidebar.selectbox("Filter by Customer", customers)
        
        # Status Filter
        status_list = ["All Statuses"] + sorted(df['Invoice Status'].unique().tolist())
        selected_status = st.sidebar.selectbox("Filter by Status", status_list)

        # Apply Filters
        filtered_df = df.copy()
        if selected_cust != "All Customers":
            filtered_df = filtered_df[filtered_df['Customer Name'] == selected_cust]
        if selected_status != "All Statuses":
            filtered_df = filtered_df[filtered_df['Invoice Status'] == selected_status]

        # 4. KEY METRICS
        total_outstanding = filtered_df['Balance'].sum()
        avg_aging = filtered_df[filtered_df['Balance'] > 0]['Aging Days (GRN)'].mean()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total B2B Receivable", f"₹{total_outstanding:,.2f}")
        m2.metric("Avg. Days from GRN", f"{avg_aging:.1f} Days" if not pd.isna(avg_aging) else "0 Days")
        m3.metric("Active Invoices", len(filtered_df[filtered_df['Balance'] > 0]))

        # 5. AGING TABLE
        st.subheader("Invoice Breakdown (True Aging)")
        
        # Formatting for display
        display_df = filtered_df[[
            'Invoice Number', 'Customer Name', 'Place of Supply', 
            'Invoice Date', 'GRN Date', 'Balance', 'Aging Days (GRN)', 'Invoice Status'
        ]].copy()

        # Visual formatting: Red text for invoices older than 30 days
        def color_aging(val):
            color = 'red' if val > 30 else 'white'
            return f'color: {color}'

        st.dataframe(
            display_df.style.applymap(color_aging, subset=['Aging Days (GRN)'])
            .format({
                "Balance": "₹{:,.2f}", 
                "Invoice Date": "{:%d %b %Y}", 
                "GRN Date": "{:%d %b %Y}"
            }),
            use_container_width=True
        )

        # 6. AGING BUCKETS CHART
        st.subheader("Aging Concentration")
        bins = [-999, 0, 15, 30, 60, 90, 9999]
        labels = ['Not Delivered Yet', '0-15 Days', '16-30 Days', '31-60 Days', '61-90 Days', '>90 Days']
        filtered_df['Bucket'] = pd.cut(filtered_df['Aging Days (GRN)'], bins=bins, labels=labels)
        
        bucket_data = filtered_df.groupby('Bucket')['Balance'].sum().reindex(labels)
        st.bar_chart(bucket_data)

else:
    st.info("👋 Welcome! Please upload your 'Invoice.csv' from Zoho Books to see the B2B GRN analysis.")
