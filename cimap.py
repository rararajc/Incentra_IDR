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

# --- 2. PAGE CONFIG & BRANDING ---
st.set_page_config(page_title="IncentraTax | Pro Batch Geocoder", layout="wide")

# Brand Colors
INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

# --- 2.5 HELPER TO ENCODE LOCAL IMAGE ---
def get_base64_img(img_path):
    try:
        return base64.b64encode(Path(img_path).read_bytes()).decode()
    except Exception:
        return None

# Attempt to load the logo
LOGO_FILE = "Logo - Incentra (Transparent).png"
img_base64 = get_base64_img(LOGO_FILE)

# --- CSS FOR STICKY HEADER & STYLING ---
st.markdown(f"""
    <style>
    /* Ensure content starts below the fixed header */
    .block-container {{
        padding-top: 8rem;
    }}

    /* Hide standard Streamlit header to use our custom one */
    header[data-testid="stHeader"] {{
        display: none;
    }}

    .sticky-logo-container {{
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        background-color: white;
        z-index: 9999;
        padding: 15px 30px;
        border-bottom: 2px solid #f0f2f6;
        display: flex;
        align-items: center;
    }}

    .stButton>button {{
        background-color: {INCENTRA_BLUE};
        color: white;
        border-radius: 4px;
        border: none;
        padding: 0.5rem 1rem;
    }}
    .stButton>button:hover {{
        border: 1px solid {INCENTRA_GRAY};
        color: white;
        background-color: #1a315f;
    }}
    h1, h2, h3 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }}
    
    .footer {{
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: white;
        color: {INCENTRA_GRAY};
        text-align: center;
        padding: 10px;
        font-size: 12px;
        border-top: 1px solid #eee;
        z-index: 999;
    }}
    </style>
    """, unsafe_allow_html=True)

# --- BRANDING: STICKY LOGO ---
if img_base64:
    st.markdown(f"""
        <div class="sticky-logo-container">
            <img src="data:image/png;base64,{img_base64}" width="300">
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown(f"""
        <div class="sticky-logo-container">
            <h2 style="margin:0; color:{INCENTRA_BLUE};">INCENTRA SPECIALTY TAX</h2>
        </div>
        """, unsafe_allow_html=True)

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
        except:
            pass 
    return data

geodata = load_all_geodata()

# --- 4. HELPER FUNCTIONS ---
def census_batch_geocode(df, address_col):
    batch_df = pd.DataFrame({
        'id': range(len(df)),
        'street': df[address_col],
        'city': '', 'state': '', 'zip': ''
    })
    output = io.StringIO()
    batch_df.to_csv(output, index=False, header=False)
    output.seek(0)
    url = 'https://geocoding.geo.census.gov/geocoder/locations/addressbatch'
    payload = {'benchmark': 'Public_AR_Current'}
    files = {'addressFile': ('batch.csv', output, 'text/csv')}
    try:
        response = requests.post(url, data=payload, files=files)
        result_columns = ['id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lon_lat', 'tiger_id', 'side']
        res_df = pd.read_csv(io.StringIO(response.text), names=result_columns, header=None)
        res_df[['lon', 'lat']] = res_df['lon_lat'].str.split(',', expand=True).astype(float)
        return res_df
    except:
        return None

def go_to(page_name):
    st.session_state.page = page_name

def delete_project(list_name, index):
    st.session_state.form_data[list_name].pop(index)
    st.rerun()

def send_email(u_name, u_email, u_phone, u_company, excel_data, is_eligible):
    try:
        sender_email = st.secrets["email"]["address"]
        sender_password = st.secrets["email"]["password"]
        expert_recipient = "jchoi@incentratax.com"

        msg_expert = MIMEMultipart()
        msg_expert['Subject'] = f"Incentra Lead: {u_company} ({'High Potential' if is_eligible else 'Low Potential'})"
        msg_expert['From'] = sender_email
        msg_expert['To'] = expert_recipient
        
        expert_body = f"New Lead Information:\n\nCompany: {u_company}\nContact: {u_name}\nEmail: {u_email}\nPhone: {u_phone}\n\nReview Status: {'POTENTIAL MATCH' if is_eligible else 'NO IMMEDIATE MATCH'}\n\nSee attachment for details."
        msg_expert.attach(MIMEText(expert_body, 'plain'))

        part = MIMEBase('application', 'octet-stream')
        part.set_payload(excel_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="Incentra_Tax_Assessment.xlsx"')
        msg_expert.attach(part)

        msg_user = MIMEMultipart()
        msg_user['Subject'] = "Incentra Specialty Tax - Assessment Confirmation"
        msg_user['From'] = sender_email
        msg_user['To'] = u_email

        if is_eligible:
            user_body = f"Dear {u_name},\n\nThank you for submitting your assessment to Incentra Specialty Tax. Our experts are reviewing your details, and we will contact you within 48 hours to discuss potential tax credit opportunities.\n\nBest regards,\nIncentra Specialty Tax Team"
        else:
            user_body = f"Dear {u_name},\n\nThank you for using our assessment tool. Based on your current responses and location data, there may not be immediate tax credit opportunities available at this time. However, tax programs change frequently. We invite you to visit us again when you have a new investment project or hiring plan.\n\nBest regards,\nIncentra Specialty Tax Team"
        
        msg_user.attach(MIMEText(user_body, 'plain'))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg_expert)
            server.send_message(msg_user)
        return True
    except:
        return False

# --- PAGE ROUTING ---

# STEP 1: ADDRESS ANALYSIS
if st.session_state.page == 'Step 1':
    st.title("🏦 STEP 1: Tax Credit Finder")
    
    st.info("💡 **Instructions:** Please upload the list of addresses in an excel file to run the location analysis. Refer to the Example for the format.")

    example_data = pd.DataFrame({"Full Address": ["200 Piedmont Ave SE, Atlanta, GA 30334"]})
    st.download_button("📂 Download Example Format", example_data.to_csv(index=False).encode('utf-8'), "example.csv")
    
    uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        address_col = st.selectbox("Select address column:", df.columns)
        if st.button("🚀 Run Batch Analysis"):
            with st.spinner("Analyzing..."):
                geo_res = census_batch_geocode(df, address_col)
                if geo_res is not None:
                    df['id'] = range(len(df))
                    merged = df.merge(geo_res[['id', 'lat', 'lon', 'match_status']], on='id')
                    
                    # Update naming to "Valid Address" and "Yes/No"
                    merged['Valid Address'] = merged['match_status'].apply(lambda x: "Yes" if x == "Match" else "No")
                    
                    clean_df = merged.dropna(subset=['lat', 'lon']).copy()
                    geometry = [Point(xy) for xy in zip(clean_df.lon, clean_df.lat)]
                    gdf = gpd.GeoDataFrame(clean_df, geometry=geometry, crs="EPSG:4326")
                    
                    final_results = merged.copy()
                    final_results['Designations'] = ""
                    for key, layer_gdf in geodata.items():
                        joined = gpd.sjoin(gdf, layer_gdf, how="left", predicate="intersects")
                        matches = joined[joined.index_right.notnull()]
                        for idx in matches.index:
                            final_results.at[idx, 'Designations'] += f"{key.upper()} "
                    
                    st.session_state.batch_results = final_results[[address_col, 'Valid Address', 'Designations']]
                    st.success(f"Analysis Finished!")

    # Table persistence check
    if st.session_state.batch_results is not None:
        st.subheader("Analysis Results")
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2: Quick Assessment ➡️", on_click=go_to, args=('Step 2',))

# STEP 2: ASSESSMENT FORM
elif st.session_state.page == 'Step 2':
    st.title("📝 STEP 2: Quick Assessment")
    st.button("⬅️ Back to Step 1", on_click=go_to, args=('Step 1',))
    
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("1. Have you had investment or job creation in the past 5 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q

    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]:
            st.session_state.form_data["historical_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            with st.container(border=True):
                col_header, col_del = st.columns([5, 1])
                col_header.markdown(f"**Historical Project #{i+1}**")
                if col_del.button(f"🗑️ Delete Proj {i+1}", key=f"del_h_{i}"):
                    delete_project("historical_projects", i)
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"1a. Description *", value=p.get('desc', ''), key=f"h1_{i}")
                p['addr'] = c1.text_input(f"1b. Address *", value=p.get('addr', ''), key=f"h2_{i}")
                p['type'] = c1.selectbox(f"1c. Facility Type", ["office", "manufacturing", "warehouse", "other"], key=f"h3_{i}")
                if p.get('type') == "other":
                    p['type_manual'] = c1.text_input("Specify:", value=p.get('type_manual', ''), key=f"h_type_man_{i}")
                p['inv'] = c2.text_input(f"1d. Investment Amount *", value=p.get('inv', ''), key=f"h4_{i}")
                p['inv_yr'] = c2.text_input(f"1e. Year(s)", value=p.get('inv_yr', ''), key=f"h5_{i}")
                p['jobs'] = c2.text_input(f"1f. Net New Jobs *", value=p.get('jobs', ''), key=f"h6_{i}")
                p['jobs_yr'] = c2.text_input(f"1g. Year(s)", value=p.get('jobs_yr', ''), key=f"h7_{i}")
        st.button("➕ Add Another Historical Project", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    st.divider()
    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Do you have plans for investment or job creation in the next 3 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q

    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]:
            st.session_state.form_data["future_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            with st.container(border=True):
                col_header, col_del = st.columns([5, 1])
                col_header.markdown(f"**Future Project #{i+1}**")
                if col_del.button(f"🗑️ Delete Proj {i+1}", key=f"del_f_{i}"):
                    delete_project("future_projects", i)
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Description *", value=p.get('desc', ''), key=f"f1_{i}")
                p['addr'] = c1.text_input(f"2b. Potential Address *", value=p.get('addr', ''), key=f"f2_{i}")
                p['type'] = c1.selectbox(f"2c. Facility Type", ["office", "manufacturing", "warehouse", "other"], key=f"f3_{i}")
                if p.get('type') == "other":
                    p['type_manual'] = c1.text_input("Specify:", value=p.get('type_manual', ''), key=f"f_type_man_{i}")
                p['inv'] = c2.text_input(f"2d. Projected Investment *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing", value=p.get('jobs_time', ''), key=f"f7_{i}")
        st.button("➕ Add Another Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    st.markdown("---")
    st.button("Next: STEP 3 Summary of Information ➡️", on_click=go_to, args=('Step 3',))

# STEP 3: SUMMARY & SUBMISSION
elif st.session_state.page == 'Step 3':
    st.title("📋 STEP 3: Summary of Information")
    st.button("⬅️ Back to Assessment", on_click=go_to, args=('Step 2',))

    if st.session_state.batch_results is not None:
        total_locs = len(st.session_state.batch_results)
        matches = len(st.session_state.batch_results[st.session_state.batch_results['Designations'].str.strip() != ""])
        st.info(f"**Location Analysis:** {total_locs} locations were processed and {matches} matches were identified.")

    with st.form("final_send"):
        st.subheader("Consult an Expert")
        u_company = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_phone = st.text_input("Phone *")
        u_email = st.text_input("Email *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if u_name and u_email and u_phone and u_company:
                # Eligibility Logic
                has_fed_ez = False
                if st.session_state.batch_results is not None:
                    has_fed_ez = st.session_state.batch_results['Designations'].str.contains('FED_EZ', case=False).any()

                total_inv = 0.0
                total_jobs = 0
                all_projs = st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]
                for p in all_projs:
                    inv_val = str(p.get('inv', '0')).replace('$', '').replace(',', '')
                    job_val = str(p.get('jobs', '0')).replace(',', '')
                    try:
                        total_inv += float(inv_val)
                        total_jobs += int(float(job_val))
                    except ValueError: continue

                has_active_projects = (st.session_state.form_data["hist_q"] == "Yes" or st.session_state.form_data["fut_q"] == "Yes")
                meets_threshold = (total_inv >= 500000 or total_jobs >= 2)
                is_eligible = (has_active_projects and meets_threshold) or has_fed_ez

                # Excel Generation
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    proj_list = []
                    for cat, key in [("Historical", "historical_projects"), ("Future", "future_projects")]:
                        for p in st.session_state.form_data[key]:
                            proj_list.append({
                                "Project Status": cat, "Project Description": p.get('desc'),
                                "Facility Type": p.get('type_manual') if p.get('type') == 'other' else p.get('type'),
                                "Location": p.get('addr'), "Investment Amount": p.get('inv'),
                                "Investment Timing": p.get('inv_yr') if cat == "Historical" else p.get('inv_time'),
                                "Number of New Jobs": p.get('jobs'),
                                "Job Creation Timing": p.get('jobs_yr') if cat == "Historical" else p.get('jobs_time'),
                                "Business Name": u_company, "Contact Name": u_name, "Contact Phone": u_phone, "Contact Email": u_email
                            })
                    pd.DataFrame(proj_list).to_excel(writer, sheet_name='Projects', index=False)
                    if st.session_state.batch_results is not None:
                        st.session_state.batch_results.to_excel(writer, sheet_name='Locations', index=False)

                excel_out = output.getvalue()
                if send_email(u_name, u_email, u_phone, u_company, excel_out, is_eligible):
                    if is_eligible:
                        st.balloons()
                        st.success("Assessment submitted! We will contact you within 48 hours.")
                    else:
                        st.info("Information received. Based on current criteria, there may not be immediate matches, but we invite you to visit again when new projects arise.")
            else:
                st.warning("Please fill out all fields marked with *")

# --- FOOTER ---
st.markdown(f'<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)