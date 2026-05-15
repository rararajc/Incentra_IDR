import streamlit as st
import pandas as pd
import geopandas as gpd
import requests
import io
import smtplib
import base64
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from shapely.geometry import Point

# --- 1. INITIALIZE SESSION STATE ---
if 'page' not in st.session_state:
    st.session_state.page = 'Step 1'
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = None
if 'form_data' not in st.session_state:
    st.session_state.form_data = {
        "hist_q": "No",
        "historical_projects": [], 
        "fut_q": "No",
        "future_projects": []      
    }

def reset_app():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# --- 2. PAGE CONFIG & MOBILE STYLING ---
st.set_page_config(page_title="IncentraTax | Tax Credit Finder", layout="wide")

INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

st.markdown(f"""
    <style>
    /* Mobile-friendly Button Styling */
    .stButton>button {{
        width: 100%;
        border-radius: 4px;
        padding: 0.6rem;
    }}
    
    /* Navy Blue for Submit Buttons */
    div.stForm [data-testid="stFormSubmitButton"] button {{
        background-color: {INCENTRA_BLUE} !important;
        color: white !important;
        border: none !important;
    }}

    /* Global Title Styling */
    h1, h2, h3 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    
    /* Footer Styling */
    .footer {{ 
        text-align: center; 
        padding: 20px; 
        color: {INCENTRA_GRAY}; 
        font-size: 12px; 
        margin-top: 50px; 
        border-top: 1px solid #eee; 
    }}
    
    /* Logo adjustments for mobile */
    .logo-container {{ display: flex; justify-content: center; padding: 10px; }}
    .logo-container img {{ max-width: 100%; height: auto; width: 280px; }}
    </style>
    """, unsafe_allow_html=True)

# --- BRANDING (NON-STICKY) ---
def get_base64_img(img_path):
    try: return base64.b64encode(Path(img_path).read_bytes()).decode()
    except: return None

LOGO_FILE = "Logo - Incentra (Transparent).png"
img_base64 = get_base64_img(LOGO_FILE)
if img_base64:
    st.markdown(f'<div class="logo-container"><img src="data:image/png;base64,{img_base64}"></div>', unsafe_allow_html=True)

# --- 4. HELPERS ---
def format_currency(val):
    try:
        clean_val = str(val).replace('$','').replace(',','')
        return f"${float(clean_val):,.0f}"
    except: return str(val)

def census_batch_geocode(df, address_col):
    batch_df = pd.DataFrame({'id': range(len(df)), 'street': df[address_col], 'city': '', 'state': '', 'zip': ''})
    output = io.StringIO()
    batch_df.to_csv(output, index=False, header=False)
    output.seek(0)
    url = 'https://geocoding.geo.census.gov/geocoder/locations/addressbatch'
    files = {'addressFile': ('batch.csv', output, 'text/csv')}
    try:
        response = requests.post(url, data={'benchmark': 'Public_AR_Current'}, files=files)
        res_df = pd.read_csv(io.StringIO(response.text), names=['id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lon_lat', 'tiger_id', 'side'], header=None)
        return res_df
    except: return None

def validate_step_2():
    valid = True
    if st.session_state.form_data["hist_q"] == "Yes":
        for p in st.session_state.form_data["historical_projects"]:
            # Check 1a through 1g
            if not all([p.get('desc'), p.get('addr'), p.get('type'), p.get('inv'), p.get('inv_yr'), p.get('jobs'), p.get('jobs_yr')]): valid = False
    if st.session_state.form_data["fut_q"] == "Yes":
        for p in st.session_state.form_data["future_projects"]:
            # Check 2a through 2g
            if not all([p.get('desc'), p.get('addr'), p.get('type'), p.get('inv'), p.get('inv_time'), p.get('jobs'), p.get('jobs_time')]): valid = False
    return valid

# --- ROUTING ---

# STEP 1
if st.session_state.page == 'Step 1':
    st.title("Tax Credit Finder")
    st.subheader("STEP 1: Quick Location Analysis")
    
    st.info("💡 **Instructions:** Upload your address list (.csv or .xlsx) to identify potential tax credit zones.")
    
    uploaded_file = st.file_uploader("Upload Address List", type=["csv", "xlsx"])
    if uploaded_file:
        file_bytes = io.BytesIO(uploaded_file.getvalue())
        df = pd.read_csv(file_bytes) if uploaded_file.name.endswith('.csv') else pd.read_excel(file_bytes)
        address_col = st.selectbox("Select the address column:", df.columns)
        
        if st.button("🚀 Run Analysis"):
            with st.spinner("Analyzing locations..."):
                geo_res = census_batch_geocode(df, address_col)
                if geo_res is not None:
                    df['id'] = range(len(df))
                    merged = df.merge(geo_res[['id', 'match_status']], on='id')
                    merged['Valid Address'] = merged['match_status'].apply(lambda x: "Yes" if x == "Match" else "No")
                    # Simplified designations for this view
                    st.session_state.batch_results = merged[[address_col, 'Valid Address']]
                    st.success("Analysis Complete!")

    if st.session_state.batch_results is not None:
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2 ➡️", on_click=lambda: st.session_state.update({"page": "Step 2"}))

# STEP 2
elif st.session_state.page == 'Step 2':
    st.title("STEP 2: Quick Assessment")
    st.button("⬅️ Back to Step 1", on_click=lambda: st.session_state.update({"page": "Step 1"}))
    
    # Historical
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("Have you had investment or job creation in the past 5 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q
    
    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]: 
            st.session_state.form_data["historical_projects"].append({})
        
        # Loop with index-safe logic
        for i in range(len(st.session_state.form_data["historical_projects"])):
            p = st.session_state.form_data["historical_projects"][i]
            with st.container(border=True):
                st.markdown(f"**Historical Project #{i+1}**")
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"1a. Description *", value=p.get('desc', ''), key=f"h1_{i}")
                p['addr'] = c1.text_input(f"1b. Address *", value=p.get('addr', ''), key=f"h2_{i}")
                p['type'] = c1.selectbox(f"1c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], key=f"h3_{i}")
                p['inv'] = c2.text_input(f"1d. Investment Amount *", value=p.get('inv', ''), key=f"h4_{i}")
                p['inv_yr'] = c2.text_input(f"1e. Year(s) *", value=p.get('inv_yr', ''), key=f"h5_{i}")
                p['jobs'] = c2.text_input(f"1f. Net New Jobs *", value=p.get('jobs', ''), key=f"h6_{i}")
                p['jobs_yr'] = c2.text_input(f"1g. Year(s) *", value=p.get('jobs_yr', ''), key=f"h7_{i}")
                
                if st.button(f"🗑️ Delete Project #{i+1}", key=f"del_h_{i}"):
                    st.session_state.form_data["historical_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Historical Project", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    st.divider()
    # Future
    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("Plans for investment or job creation in the next 3 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q
    
    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]: 
            st.session_state.form_data["future_projects"].append({})
            
        for i in range(len(st.session_state.form_data["future_projects"])):
            p = st.session_state.form_data["future_projects"][i]
            with st.container(border=True):
                st.markdown(f"**Future Project #{i+1}**")
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Description *", value=p.get('desc', ''), key=f"f1_{i}")
                p['addr'] = c1.text_input(f"2b. Potential Address *", value=p.get('addr', ''), key=f"f2_{i}")
                p['type'] = c1.selectbox(f"2c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], key=f"f3_{i}")
                p['inv'] = c2.text_input(f"2d. Projected Investment *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing *", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing *", value=p.get('jobs_time', ''), key=f"f7_{i}")
                
                if st.button(f"🗑️ Delete Project #{i+1}", key=f"del_f_{i}"):
                    st.session_state.form_data["future_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    if st.button("Next: STEP 3 Summary ➡️"):
        if validate_step_2():
            st.session_state.page = 'Step 3'
            st.rerun()
        else:
            st.error("Please complete all required fields (marked with *) before moving to Step 3.")

# STEP 3
elif st.session_state.page == 'Step 3':
    st.title("STEP 3: Summary and Submit")
    st.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}))
    
    st.subheader("Summary")
    
    # Location Summary
    if st.session_state.batch_results is not None:
        total = len(st.session_state.batch_results)
        matches = len(st.session_state.batch_results[st.session_state.batch_results['Valid Address'] == 'Yes'])
        st.write(f"**Location Analysis:** {total} locations were processed and {matches} potential matches were identified.")
    
    # Historical Summary
    st.markdown("### Historical Projects")
    if st.session_state.form_data["historical_projects"]:
        for p in st.session_state.form_data["historical_projects"]:
            st.write(f"Facility Type: {p.get('type','')} | Investment: {format_currency(p.get('inv'))} ({p.get('inv_yr','')}) | New Jobs: {p.get('jobs','')} ({p.get('jobs_yr','')})")
    else:
        st.write("No historical projects reported.")

    # Future Summary
    st.markdown("### Future Projects")
    if st.session_state.form_data["future_projects"]:
        for p in st.session_state.form_data["future_projects"]:
            st.write(f"Facility Type: {p.get('type','')} | Investment: {format_currency(p.get('inv'))} ({p.get('inv_time','')}) | New Jobs: {p.get('jobs','')} ({p.get('jobs_time','')})")
    else:
        st.write("No future projects reported.")

    # Contact Form
    with st.form("final_form"):
        st.subheader("Contact Information")
        st.text_input("Company Name *")
        st.text_input("Contact Name *")
        st.text_input("Email Address *")
        st.text_input("Phone Number *")
        if st.form_submit_button("📧 Submit Assessment"):
            st.success("Your assessment has been submitted. Our experts will contact you within 48 hours.")

    # Start Over Button
    st.button("🔄 Start Over Fresh", on_click=reset_app)

st.markdown(f'<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
