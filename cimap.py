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
import xlsxwriter

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
    st.session_state.page = 'Step 1'
    st.session_state.batch_results = None
    st.session_state.form_data = {
        "hist_q": "No",
        "historical_projects": [], 
        "fut_q": "No",
        "future_projects": []      
    }
    st.rerun()

# --- 2. PAGE CONFIG & BRANDING ---
st.set_page_config(page_title="IncentraTax | Pro Batch Geocoder", layout="wide")

INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

def get_base64_img(img_path):
    try:
        return base64.b64encode(Path(img_path).read_bytes()).decode()
    except Exception:
        return None

LOGO_FILE = "Logo - Incentra (Transparent).png"
img_base64 = get_base64_img(LOGO_FILE)

# --- CSS FOR RESPONSIVE STICKY HEADER ---
st.markdown(f"""
    <style>
    .block-container {{
        padding-top: 7rem;
    }}
    @media (max-width: 640px) {{
        .block-container {{ padding-top: 5.5rem; }}
    }}

    header[data-testid="stHeader"] {{ display: none; }}

    .sticky-logo-container {{
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        background-color: white;
        z-index: 9999;
        padding: 10px 20px;
        border-bottom: 2px solid #f0f2f6;
        display: flex;
        justify-content: center;
    }}

    .sticky-logo-container img {{
        max-width: 280px;
        height: auto;
    }}
    @media (max-width: 640px) {{
        .sticky-logo-container img {{ max-width: 160px; }}
    }}

    .stButton>button {{
        background-color: {INCENTRA_BLUE};
        color: white;
        border-radius: 4px;
        width: 100%;
        padding: 0.6rem;
    }}
    h1, h2, h3 {{ color: {INCENTRA_BLUE}; }}
    
    .footer {{
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: white;
        color: {INCENTRA_GRAY};
        text-align: center;
        padding: 10px;
        font-size: 11px;
        border-top: 1px solid #eee;
        z-index: 999;
    }}
    </style>
    """, unsafe_allow_html=True)

if img_base64:
    st.markdown(f'<div class="sticky-logo-container"><img src="data:image/png;base64,{img_base64}"></div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="sticky-logo-container"><h2 style="margin:0;">INCENTRA SPECIALTY TAX</h2></div>', unsafe_allow_html=True)

# --- 3. DATA LAYERS LOADING ---
LAYERS = {
    "tiers": "ga_county_tiers.shp",
    "military": "ga_military_zones.shp",
    "state_oz": "ga_state_opportunity_zones.shp",
    "ldct": "ga_ldct.shp",
    "fed_ez": "federal_empowerment_zones.shp"
}

@st.cache_data
def load_all_geodata():
    data = {}
    for key, file in LAYERS.items():
        try:
            data[key] = gpd.read_file(file).to_crs("EPSG:4326")
        except: pass 
    return data

geodata = load_all_geodata()

# --- 4. HELPER FUNCTIONS ---
def census_batch_geocode(df, address_col):
    batch_df = pd.DataFrame({'id': range(len(df)), 'street': df[address_col], 'city': '', 'state': '', 'zip': ''})
    output = io.StringIO()
    batch_df.to_csv(output, index=False, header=False)
    output.seek(0)
    url = 'https://geocoding.geo.census.gov/geocoder/locations/addressbatch'
    payload = {'benchmark': 'Public_AR_Current'}
    files = {'addressFile': ('batch.csv', output, 'text/csv')}
    try:
        response = requests.post(url, data=payload, files=files)
        res_df = pd.read_csv(io.StringIO(response.text), names=['id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lon_lat', 'tiger_id', 'side'], header=None)
        res_df[['lon', 'lat']] = res_df['lon_lat'].str.split(',', expand=True).astype(float)
        return res_df
    except: return None

def go_to(page_name):
    st.session_state.page = page_name

def validate_step_2():
    # Validate Historical
    if st.session_state.form_data["hist_q"] == "Yes":
        for p in st.session_state.form_data["historical_projects"]:
            required = ['desc', 'addr', 'type', 'inv', 'inv_yr', 'jobs', 'jobs_yr']
            if not all(p.get(k) for k in required):
                return False
    # Validate Future
    if st.session_state.form_data["fut_q"] == "Yes":
        for p in st.session_state.form_data["future_projects"]:
            required = ['desc', 'addr', 'type', 'inv', 'inv_time', 'jobs', 'jobs_time']
            if not all(p.get(k) for k in required):
                return False
    return True

def send_email(u_name, u_email, u_phone, u_company, excel_data, is_eligible):
    try:
        sender_email = st.secrets["email"]["address"]
        sender_password = st.secrets["email"]["password"]
        expert_recipient = "jchoi@incentratax.com"

        msg_expert = MIMEMultipart()
        msg_expert['Subject'] = f"Incentra Lead: {u_company} ({'High Potential' if is_eligible else 'Low Potential'})"
        msg_expert['From'] = sender_email
        msg_expert['To'] = expert_recipient
        msg_expert.attach(MIMEText(f"Lead Info:\n\nCompany: {u_company}\nName: {u_name}\nEmail: {u_email}\nPhone: {u_phone}", 'plain'))

        part = MIMEBase('application', 'octet-stream')
        part.set_payload(excel_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="Incentra_Assessment.xlsx"')
        msg_expert.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg_expert)
        return True
    except: return False

# --- PAGE ROUTING ---

# STEP 1: ADDRESS ANALYSIS
if st.session_state.page == 'Step 1':
    st.title("🏦 STEP 1: Tax Credit Finder")
    st.info("💡 **Instructions:** Upload an Excel file of addresses to run the location analysis.")

    example_data = pd.DataFrame({"Full Address": ["200 Piedmont Ave SE, Atlanta, GA 30334"]})
    st.download_button("📂 Download Example Format", example_data.to_csv(index=False).encode('utf-8'), "example.csv")
    
    uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(io.BytesIO(uploaded_file.read()), engine='openpyxl')
            
            address_col = st.selectbox("Select address column:", df.columns)
            if st.button("🚀 Run Batch Analysis"):
                with st.spinner("Analyzing..."):
                    geo_res = census_batch_geocode(df, address_col)
                    if geo_res is not None:
                        df['id'] = range(len(df))
                        merged = df.merge(geo_res[['id', 'lat', 'lon', 'match_status']], on='id')
                        merged['Valid Address'] = merged['match_status'].apply(lambda x: "Yes" if x == "Match" else "No")
                        clean_df = merged.dropna(subset=['lat', 'lon']).copy()
                        gdf = gpd.GeoDataFrame(clean_df, geometry=[Point(xy) for xy in zip(clean_df.lon, clean_df.lat)], crs="EPSG:4326")
                        
                        final_results = merged.copy()
                        final_results['Designations'] = ""
                        for key, layer_gdf in geodata.items():
                            joined = gpd.sjoin(gdf, layer_gdf, how="left", predicate="intersects")
                            matches = joined[joined.index_right.notnull()]
                            for idx in matches.index:
                                final_results.at[idx, 'Designations'] += f"{key.upper()} "
                        
                        st.session_state.batch_results = final_results[[address_col, 'Valid Address', 'Designations']]
                        st.success("Analysis Finished!")
        except:
            st.error("Error reading file. Please use a standard Excel or CSV file.")

    if st.session_state.batch_results is not None:
        st.subheader("Analysis Results")
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2: Quick Assessment ➡️", on_click=go_to, args=('Step 2',))

# STEP 2: ASSESSMENT FORM
elif st.session_state.page == 'Step 2':
    st.title("📝 STEP 2: Quick Assessment")
    st.button("⬅️ Back to Step 1", on_click=go_to, args=('Step 1',))
    
    # Historical Section
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("1. Have you had investment or job creation in the past 5 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q

    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]:
            st.session_state.form_data["historical_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
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
                if st.button(f"🗑️ Remove Project {i+1}", key=f"del_h_{i}"):
                    st.session_state.form_data["historical_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Historical Project", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    st.divider()

    # Future Section
    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Do you have plans for investment or job creation in the next 3 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q

    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]:
            st.session_state.form_data["future_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
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
                if st.button(f"🗑️ Remove Project {i+1}", key=f"del_f_{i}"):
                    st.session_state.form_data["future_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    st.markdown("---")
    if st.button("Next: STEP 3 Summary of Information ➡️"):
        if validate_step_2():
            go_to('Step 3')
            st.rerun()
        else:
            st.error("⚠️ Please complete all required fields (*) for each project added before proceeding.")

# STEP 3: SUMMARY & SUBMISSION
elif st.session_state.page == 'Step 3':
    st.title("📋 STEP 3: Summary of Information")
    
    col_nav1, col_nav2 = st.columns(2)
    col_nav1.button("⬅️ Back to Step 2", on_click=go_to, args=('Step 2',))
    col_nav2.button("🔄 Start Over Fresh", on_click=reset_app)

    if st.session_state.batch_results is not None:
        matches = len(st.session_state.batch_results[st.session_state.batch_results['Designations'].str.strip() != ""])
        st.info(f"**Location Analysis:** {len(st.session_state.batch_results)} locations analyzed, {matches} matches identified.")

    with st.form("final_send"):
        st.subheader("Consult an Expert")
        u_company = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_phone = st.text_input("Phone *")
        u_email = st.text_input("Email *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if u_name and u_email and u_phone and u_company:
                # Basic Eligibility Logic
                total_inv = 0.0
                all_projs = st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]
                for p in all_projs:
                    try: total_inv += float(str(p.get('inv', '0')).replace('$', '').replace(',', ''))
                    except: pass
                
                is_eligible = (total_inv >= 500000 or matches > 0)
                
                # Excel Build
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    proj_list = []
                    for cat, key in [("Historical", "historical_projects"), ("Future", "future_projects")]:
                        for p in st.session_state.form_data[key]:
                            p_data = p.copy()
                            p_data['Status'] = cat
                            proj_list.append(p_data)
                    pd.DataFrame(proj_list).to_excel(writer, sheet_name='Projects', index=False)
                    if st.session_state.batch_results is not None:
                        st.session_state.batch_results.to_excel(writer, sheet_name='Locations', index=False)
                
                if send_email(u_name, u_email, u_phone, u_company, output.getvalue(), is_eligible):
                    st.balloons()
                    st.success("Success! Our experts will contact you within 48 hours.")
            else:
                st.warning("Please fill out your contact information.")

st.markdown(f'<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
