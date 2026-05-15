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
    # Clear all state and return to Step 1
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state.page = 'Step 1'
    st.session_state.batch_results = None
    st.session_state.form_data = {
        "hist_q": "No",
        "historical_projects": [], 
        "fut_q": "No",
        "future_projects": []      
    }
    st.rerun()

# --- 2. PAGE CONFIG ---
st.set_page_config(page_title="IncentraTax | Pro Batch Geocoder", layout="wide")

INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

# --- CSS FOR CLEAN LAYOUT (NO OVERLAP) ---
st.markdown(f"""
    <style>
    header[data-testid="stHeader"] {{ display: none; }}
    
    .stButton>button {{
        background-color: {INCENTRA_BLUE};
        color: white;
        border-radius: 4px;
        width: 100%;
        padding: 0.6rem;
        border: none;
    }}
    
    h1, h2, h3 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    
    .logo-container {{
        display: flex;
        justify-content: center;
        padding: 20px 0;
        background-color: white;
    }}
    .logo-container img {{
        max-width: 280px;
        height: auto;
    }}
    @media (max-width: 640px) {{
        .logo-container img {{ max-width: 160px; }}
    }}

    .footer {{
        text-align: center;
        padding: 20px;
        color: {INCENTRA_GRAY};
        font-size: 12px;
        border-top: 1px solid #eee;
        margin-top: 50px;
    }}
    </style>
    """, unsafe_allow_html=True)

# --- BRANDING ---
def get_base64_img(img_path):
    try: return base64.b64encode(Path(img_path).read_bytes()).decode()
    except: return None

LOGO_FILE = "Logo - Incentra (Transparent).png"
img_base64 = get_base64_img(LOGO_FILE)

if img_base64:
    st.markdown(f'<div class="logo-container"><img src="data:image/png;base64,{img_base64}"></div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="logo-container"><h2>INCENTRA SPECIALTY TAX</h2></div>', unsafe_allow_html=True)

# --- 3. DATA LAYERS ---
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

# --- 4. HELPERS ---
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

def validate_step_2():
    # Strict validation for 1a-1g
    if st.session_state.form_data["hist_q"] == "Yes":
        if not st.session_state.form_data["historical_projects"]: return False
        for p in st.session_state.form_data["historical_projects"]:
            if not all([p.get('desc'), p.get('addr'), p.get('inv'), p.get('inv_yr'), p.get('jobs'), p.get('jobs_yr')]):
                return False
            if p.get('type') == "other" and not p.get('type_manual', '').strip():
                return False
    # Strict validation for 2a-2g
    if st.session_state.form_data["fut_q"] == "Yes":
        if not st.session_state.form_data["future_projects"]: return False
        for p in st.session_state.form_data["future_projects"]:
            if not all([p.get('desc'), p.get('addr'), p.get('inv'), p.get('inv_time'), p.get('jobs'), p.get('jobs_time')]):
                return False
            if p.get('type') == "other" and not p.get('type_manual', '').strip():
                return False
    return True

# --- PAGE ROUTING ---

if st.session_state.page == 'Step 1':
    st.title("🏦 STEP 1: Tax Credit Finder")
    st.info("💡 **Instructions:** Please upload your address list (Excel or CSV).")

    # --- EXAMPLE FILE SECTION ---
    st.markdown("### 📥 Download Template")
    example_df = pd.DataFrame({
        "Full Address": [
            "200 Piedmont Ave SE, Atlanta, GA 30334",
            "1200 Glynn Ave, Brunswick, GA 31520",
            "100 Bull St, Savannah, GA 31401"
        ]
    })
    
    # Convert dataframe to CSV for the download button
    csv = example_df.to_csv(index=False).encode('utf-8')
    
    st.download_button(
        label="📂 Download Example Address List (.csv)",
        data=csv,
        file_name="Incentra_Template.csv",
        mime="text/csv",
        help="Download this to see the correct format for your address list."
    )
    st.divider()
    
    uploaded_file = st.file_uploader("Upload File", type=["csv", "xlsx"])

    if uploaded_file:
        try:
            # FIX: Convert the uploaded file into a persistent Byte stream for mobile compatibility
            input_data = io.BytesIO(uploaded_file.getvalue())
            
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(input_data)
            else:
                # Explicitly use openpyxl for Excel files on mobile
                df = pd.read_excel(input_data, engine='openpyxl')
            
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
                        st.success("Analysis Complete!")
        except Exception as e:
            st.error(f"File Error: {e}. If using Excel, please ensure it is a standard .xlsx file.")

    if st.session_state.batch_results is not None:
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2: Quick Assessment ➡️", on_click=lambda: st.session_state.update({"page": "Step 2"}))

elif st.session_state.page == 'Step 2':
    st.title("📝 STEP 2: Quick Assessment")
    st.button("⬅️ Back to Step 1", on_click=lambda: st.session_state.update({"page": "Step 1"}))
    
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("1. Any past investment/hiring?", ["No", "Yes"], index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q
    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]: st.session_state.form_data["historical_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"1a. Description *", value=p.get('desc', ''), key=f"h1_{i}")
                p['addr'] = c1.text_input(f"1b. Address *", value=p.get('addr', ''), key=f"h2_{i}")
                p['type'] = c1.selectbox(f"1c. Type *", ["office", "manufacturing", "warehouse", "other"], key=f"h3_{i}")
                if p['type'] == "other":
                    p['type_manual'] = c1.text_input(f"Specify Facility Type *", value=p.get('type_manual', ''), key=f"h_other_{i}")
                p['inv'] = c2.text_input(f"1d. Investment $ *", value=p.get('inv', ''), key=f"h4_{i}")
                p['inv_yr'] = c2.text_input(f"1e. Year(s) *", value=p.get('inv_yr', ''), key=f"h5_{i}")
                p['jobs'] = c2.text_input(f"1f. New Jobs *", value=p.get('jobs', ''), key=f"h6_{i}")
                p['jobs_yr'] = c2.text_input(f"1g. Year(s) *", value=p.get('jobs_yr', ''), key=f"h7_{i}")
                if st.button(f"🗑️ Remove Proj {i+1}", key=f"del_h_{i}"):
                    st.session_state.form_data["historical_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Historical", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    st.divider()

    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Any future investment/hiring plans?", ["No", "Yes"], index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q
    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]: st.session_state.form_data["future_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Description *", value=p.get('desc', ''), key=f"f1_{i}")
                p['addr'] = c1.text_input(f"2b. Address *", value=p.get('addr', ''), key=f"f2_{i}")
                p['type'] = c1.selectbox(f"2c. Type *", ["office", "manufacturing", "warehouse", "other"], key=f"f3_{i}")
                if p['type'] == "other":
                    p['type_manual'] = c1.text_input(f"Specify Facility Type *", value=p.get('type_manual', ''), key=f"f_other_{i}")
                p['inv'] = c2.text_input(f"2d. Projected $ *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing *", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing *", value=p.get('jobs_time', ''), key=f"f7_{i}")
                if st.button(f"🗑️ Remove Proj {i+1}", key=f"del_f_{i}"):
                    st.session_state.form_data["future_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Future", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    if st.button("Next: STEP 3 Summary ➡️"):
        if validate_step_2():
            st.session_state.page = 'Step 3'
            st.rerun()
        else:
            st.error("⚠️ Please fill out all required fields (*) for any projects you added.")

elif st.session_state.page == 'Step 3':
    st.title("📋 STEP 3: Summary & Submission")
    col_a, col_b = st.columns(2)
    col_a.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}))
    col_b.button("🔄 Start Over Fresh", on_click=reset_app)

    with st.form("final_form"):
        st.subheader("Contact Information")
        u_comp = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_email = st.text_input("Email Address *")
        u_phone = st.text_input("Phone Number *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if all([u_comp, u_name, u_email, u_phone]):
                st.balloons()
                st.success("Assessment submitted! We will contact you within 48 hours.")
            else:
                st.warning("Please fill out all contact fields.")

st.markdown('<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
