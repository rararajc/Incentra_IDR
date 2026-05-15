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

# --- 2. PAGE CONFIG ---
st.set_page_config(page_title="IncentraTax | Pro Batch Geocoder", layout="wide")

INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

# --- CSS FOR STYLING (NO STICKY HEADER TO PREVENT CUT-OFF) ---
st.markdown(f"""
    <style>
    /* Hide standard Streamlit header */
    header[data-testid="stHeader"] {{ display: none; }}

    /* Standard Button Styling */
    .stButton>button {{
        background-color: {INCENTRA_BLUE};
        color: white;
        border-radius: 4px;
        width: 100%;
        padding: 0.6rem;
        border: none;
    }}
    .stButton>button:hover {{
        background-color: #1a315f;
        color: white;
    }}
    
    h1, h2, h3 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    
    /* Center the logo container - Non-Sticky for layout stability */
    .logo-container {{
        display: flex;
        justify-content: center;
        padding: 20px 0;
        background-color: white;
        margin-bottom: 10px;
    }}
    .logo-container img {{
        max-width: 300px;
        height: auto;
    }}
    @media (max-width: 640px) {{
        .logo-container img {{ max-width: 180px; }}
    }}

    .footer {{
        text-align: center;
        padding: 20px;
        color: {INCENTRA_GRAY};
        font-size: 12px;
        margin-top: 50px;
        border-top: 1px solid #eee;
    }}
    </style>
    """, unsafe_allow_html=True)

# --- BRANDING: FLOWING LOGO ---
def get_base64_img(img_path):
    try: return base64.b64encode(Path(img_path).read_bytes()).decode()
    except: return None

LOGO_FILE = "Logo - Incentra (Transparent).png"
img_base64 = get_base64_img(LOGO_FILE)

if img_base64:
    st.markdown(f'<div class="logo-container"><img src="data:image/png;base64,{img_base64}"></div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="logo-container"><h2>INCENTRA SPECIALTY TAX</h2></div>', unsafe_allow_html=True)

# --- 3. DATA LAYERS LOADING ---
@st.cache_data
def load_all_geodata():
    LAYERS = {
        "tiers": "ga_county_tiers.shp",
        "military": "ga_military_zones.shp",
        "state_oz": "ga_state_opportunity_zones.shp",
        "ldct": "ga_ldct.shp",
        "fed_ez": "federal_empowerment_zones.shp"
    }
    data = {}
    for key, file in LAYERS.items():
        try: data[key] = gpd.read_file(file).to_crs("EPSG:4326")
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

def send_email(u_name, u_email, u_phone, u_company, excel_data, is_eligible):
    try:
        sender_email = st.secrets["email"]["address"]
        sender_password = st.secrets["email"]["password"]
        expert_recipient = "jchoi@incentratax.com"

        # Expert Email
        msg_expert = MIMEMultipart()
        msg_expert['Subject'] = f"Incentra Lead: {u_company} ({'High Potential' if is_eligible else 'Low Potential'})"
        msg_expert['From'] = sender_email
        msg_expert['To'] = expert_recipient
        msg_expert.attach(MIMEText(f"Lead Details:\n\nCompany: {u_company}\nContact: {u_name}\nEmail: {u_email}\nPhone: {u_phone}\nPotential Match: {is_eligible}", 'plain'))
        
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(excel_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="Incentra_Assessment.xlsx"')
        msg_expert.attach(part)

        # User Email
        msg_user = MIMEMultipart()
        msg_user['Subject'] = "Incentra Specialty Tax - Assessment Confirmation"
        msg_user['From'] = sender_email
        msg_user['To'] = u_email
        user_body = f"Dear {u_name},\n\nThank you for your submission. Our team is reviewing your details and will contact you within 48 hours." if is_eligible else f"Dear {u_name},\n\nThank you for using our tool. We have received your information for future review."
        msg_user.attach(MIMEText(user_body, 'plain'))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg_expert)
            server.send_message(msg_user)
        return True
    except: return False

# --- PAGE ROUTING ---

if st.session_state.page == 'Step 1':
    st.title("🏦 STEP 1: Tax Credit Finder")
    st.info("💡 **Instructions:** Upload your address list (Excel or CSV).")
    
    uploaded_file = st.file_uploader("Upload File", type=["csv", "xlsx"])

    if uploaded_file:
        try:
            # FORCE READ FOR MOBILE COMPATIBILITY
            file_bytes = io.BytesIO(uploaded_file.getvalue())
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(file_bytes)
            else:
                df = pd.read_excel(file_bytes, engine='openpyxl')
            
            address_col = st.selectbox("Select address column:", df.columns)
            if st.button("🚀 Run Batch Analysis"):
                with st.spinner("Analyzing location data..."):
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
                        st.success("Analysis Complete!")
        except Exception as e:
            st.error(f"Error processing file: {e}")

    if st.session_state.batch_results is not None:
        st.subheader("Results Preview")
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2: Quick Assessment ➡️", on_click=lambda: st.session_state.update({"page": "Step 2"}))

elif st.session_state.page == 'Step 2':
    st.title("📝 STEP 2: Quick Assessment")
    st.button("⬅️ Back to Step 1", on_click=lambda: st.session_state.update({"page": "Step 1"}))
    
    # Historical
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("1. Have you had investment or job creation in the past 5 years?", ["No", "Yes"], index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q
    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]: st.session_state.form_data["historical_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"1a. Description *", value=p.get('desc', ''), key=f"h1_{i}")
                p['addr'] = c1.text_input(f"1b. Address *", value=p.get('addr', ''), key=f"h2_{i}")
                p['type'] = c1.selectbox(f"1c. Type", ["office", "manufacturing", "warehouse", "other"], key=f"h3_{i}")
                p['inv'] = c2.text_input(f"1d. Investment Amount *", value=p.get('inv', ''), key=f"h4_{i}")
                p['inv_yr'] = c2.text_input(f"1e. Year(s)", value=p.get('inv_yr', ''), key=f"h5_{i}")
                p['jobs'] = c2.text_input(f"1f. Net New Jobs *", value=p.get('jobs', ''), key=f"h6_{i}")
                p['jobs_yr'] = c2.text_input(f"1g. Year(s)", value=p.get('jobs_yr', ''), key=f"h7_{i}")
                if st.button(f"🗑️ Delete Proj {i+1}", key=f"del_h_{i}"):
                    st.session_state.form_data["historical_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Historical", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    st.divider()

    # Future
    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Plans for investment/jobs in the next 3 years?", ["No", "Yes"], index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q
    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]: st.session_state.form_data["future_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Description *", value=p.get('desc', ''), key=f"f1_{i}")
                p['addr'] = c1.text_input(f"2b. Address *", value=p.get('addr', ''), key=f"f2_{i}")
                p['type'] = c1.selectbox(f"2c. Type", ["office", "manufacturing", "warehouse", "other"], key=f"f3_{i}")
                p['inv'] = c2.text_input(f"2d. Projected $ *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing", value=p.get('jobs_time', ''), key=f"f7_{i}")
                if st.button(f"🗑️ Delete Proj {i+1}", key=f"del_f_{i}"):
                    st.session_state.form_data["future_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Future", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    st.button("Next: STEP 3 Summary ➡️", on_click=lambda: st.session_state.update({"page": "Step 3"}))

elif st.session_state.page == 'Step 3':
    st.title("📋 STEP 3: Summary & Submission")
    col1, col2 = st.columns(2)
    col1.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}))
    col2.button("🔄 Start Over Fresh", on_click=reset_app)

    with st.form("final_submission"):
        u_company = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_email = st.text_input("Email *")
        u_phone = st.text_input("Phone *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if all([u_company, u_name, u_email, u_phone]):
                # Eligibility Logic
                has_fed_ez = False
                if st.session_state.batch_results is not None:
                    has_fed_ez = st.session_state.batch_results['Designations'].str.contains('FED_EZ', case=False).any()

                total_inv = 0.0
                total_jobs = 0
                all_projs = st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]
                for p in all_projs:
                    try:
                        total_inv += float(str(p.get('inv', '0')).replace('$', '').replace(',', ''))
                        total_jobs += int(float(str(p.get('jobs', '0')).replace(',', '')))
                    except: continue

                is_eligible = (total_inv >= 500000 or total_jobs >= 2) or has_fed_ez

                # Excel Creation
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    proj_list = []
                    for cat, key in [("Historical", "historical_projects"), ("Future", "future_projects")]:
                        for p in st.session_state.form_data[key]:
                            p_clean = p.copy()
                            p_clean['Category'] = cat
                            proj_list.append(p_clean)
                    pd.DataFrame(proj_list).to_excel(writer, sheet_name='Projects', index=False)
                    if st.session_state.batch_results is not None:
                        st.session_state.batch_results.to_excel(writer, sheet_name='Locations', index=False)
                
                if send_email(u_name, u_email, u_phone, u_company, output.getvalue(), is_eligible):
                    if is_eligible: st.balloons()
                    st.success("Submission successful! We will contact you shortly.")
            else:
                st.warning("Please fill out all required fields.")

st.markdown('<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
