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
    .stButton>button {{ width: 100%; border-radius: 4px; padding: 0.6rem; }}
    div.stForm [data-testid="stFormSubmitButton"] button {{
        background-color: {INCENTRA_BLUE} !important;
        color: white !important;
    }}
    h1, h2, h3 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    .footer {{ text-align: center; padding: 20px; color: {INCENTRA_GRAY}; font-size: 12px; margin-top: 50px; border-top: 1px solid #eee; }}
    .logo-container {{ display: flex; justify-content: center; padding: 10px; }}
    .logo-container img {{ max-width: 100%; height: auto; width: 280px; }}
    </style>
    """, unsafe_allow_html=True)

# --- BRANDING ---
LOGO_FILE = "Logo - Incentra (Transparent).png"
def get_base64_img(img_path):
    try: return base64.b64encode(Path(img_path).read_bytes()).decode()
    except: return None

img_base64 = get_base64_img(LOGO_FILE)
if img_base64:
    st.markdown(f'<div class="logo-container"><img src="data:image/png;base64,{img_base64}"></div>', unsafe_allow_html=True)

# --- 3. HELPERS & GEO ---
@st.cache_data
def load_geodata():
    # Placeholder for actual file loading logic from your environment
    layers = {"fed_ez": "federal_empowerment_zones.shp"}
    data = {}
    for k, v in layers.items():
        try: data[k] = gpd.read_file(v).to_crs("EPSG:4326")
        except: pass
    return data

geodata = load_geodata()

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
    try:
        response = requests.post(url, data={'benchmark': 'Public_AR_Current'}, files={'addressFile': ('batch.csv', output, 'text/csv')})
        res_df = pd.read_csv(io.StringIO(response.text), names=['id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lon_lat', 'tiger_id', 'side'], header=None)
        res_df[['lon', 'lat']] = res_df['lon_lat'].str.split(',', expand=True).astype(float)
        return res_df
    except: return None

# --- ROUTING ---

# STEP 1: ANALYSIS
if st.session_state.page == 'Step 1':
    st.title("Tax Credit Finder")
    st.subheader("STEP 1: Quick Location Analysis")
    
    # Example File Download
    example_df = pd.DataFrame({"Full Address": ["200 Piedmont Ave SE, Atlanta, GA 30334"]})
    st.download_button("📂 Download Example Format", example_df.to_csv(index=False).encode('utf-8'), "example_addresses.csv")
    
    uploaded_file = st.file_uploader("Upload Address List", type=["csv", "xlsx"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        address_col = st.selectbox("Select the address column:", df.columns)
        
        if st.button("🚀 Run Analysis"):
            with st.spinner("Analyzing locations..."):
                geo_res = census_batch_geocode(df, address_col)
                if geo_res is not None:
                    df['id'] = range(len(df))
                    merged = df.merge(geo_res[['id', 'match_status', 'lat', 'lon']], on='id')
                    merged['Valid Address'] = merged['match_status'].apply(lambda x: "Yes" if x == "Match" else "No")
                    merged['Designations'] = ""
                    
                    # Spatial Join for Fed EZ
                    clean_geo = merged.dropna(subset=['lat', 'lon']).copy()
                    if not clean_geo.empty and "fed_ez" in geodata:
                        gdf = gpd.GeoDataFrame(clean_geo, geometry=[Point(xy) for xy in zip(clean_geo.lon, clean_geo.lat)], crs="EPSG:4326")
                        joined = gpd.sjoin(gdf, geodata["fed_ez"], how="left", predicate="intersects")
                        for idx in joined[joined.index_right.notnull()].index:
                            merged.at[idx, 'Designations'] += "FEDERAL_EZ "
                    
                    st.session_state.batch_results = merged[[address_col, 'Valid Address', 'Designations']]
                    st.success("Analysis Complete!")

    if st.session_state.batch_results is not None:
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2 ➡️", on_click=lambda: st.session_state.update({"page": "Step 2"}))

# STEP 2: ASSESSMENT
elif st.session_state.page == 'Step 2':
    st.title("STEP 2: Quick Assessment")
    st.button("⬅️ Back to Step 1", on_click=lambda: st.session_state.update({"page": "Step 1"}))
    
    # Historical
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("Investment or job creation in the past 5 years?", ["No", "Yes"], 
                   index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q
    
    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]: st.session_state.form_data["historical_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            with st.container(border=True):
                st.markdown(f"**Historical Project #{i+1}**")
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"1a. Description *", value=p.get('desc', ''), key=f"h1_{i}")
                p['addr'] = c1.text_input(f"1b. Address *", value=p.get('addr', ''), key=f"h2_{i}")
                p['type'] = c1.selectbox(f"1c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], 
                                         index=["office", "manufacturing", "warehouse", "other"].index(p.get('type', 'office')), key=f"h3_{i}")
                if p['type'] == 'other':
                    p['other_type'] = c1.text_input("Please specify facility type *", value=p.get('other_type', ''), key=f"h3_other_{i}")
                
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
        if not st.session_state.form_data["future_projects"]: st.session_state.form_data["future_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            with st.container(border=True):
                st.markdown(f"**Future Project #{i+1}**")
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Description *", value=p.get('desc', ''), key=f"f1_{i}")
                p['addr'] = c1.text_input(f"2b. Potential Address *", value=p.get('addr', ''), key=f"f2_{i}")
                p['type'] = c1.selectbox(f"2c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], 
                                         index=["office", "manufacturing", "warehouse", "other"].index(p.get('type', 'office')), key=f"f3_{i}")
                if p['type'] == 'other':
                    p['other_type'] = c1.text_input("Please specify facility type *", value=p.get('other_type', ''), key=f"f3_other_{i}")
                
                p['inv'] = c2.text_input(f"2d. Projected Investment *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing *", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing *", value=p.get('jobs_time', ''), key=f"f7_{i}")
                
                if st.button(f"🗑️ Delete Project #{i+1}", key=f"del_f_{i}"):
                    st.session_state.form_data["future_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    if st.button("Next: STEP 3 Summary ➡️"):
        st.session_state.page = 'Step 3'
        st.rerun()

# STEP 3: SUMMARY
elif st.session_state.page == 'Step 3':
    st.title("STEP 3: Summary and Submit")
    st.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}))
    
    st.subheader("Summary")
    
    # Location Analysis Sub-sub
    st.markdown("#### Location Analysis")
    if st.session_state.batch_results is not None:
        total = len(st.session_state.batch_results)
        matches = len(st.session_state.batch_results[st.session_state.batch_results['Valid Address'] == 'Yes'])
        st.write(f"{total} locations were processed and {matches} potential matches were identified.")
    
    # Historical Projects Sub-sub
    st.markdown("#### Historical Projects")
    if st.session_state.form_data["historical_projects"]:
        for p in st.session_state.form_data["historical_projects"]:
            f_type = p.get('other_type') if p.get('type') == 'other' else p.get('type')
            st.write(f"Facility Type: {f_type} | Investment: {format_currency(p.get('inv'))} ({p.get('inv_yr','')}) | New Jobs: {p.get('jobs','')} ({p.get('jobs_yr','')})")
    else: st.write("No historical projects reported.")

    # Future Projects Sub-sub
    st.markdown("#### Future Projects")
    if st.session_state.form_data["future_projects"]:
        for p in st.session_state.form_data["future_projects"]:
            f_type = p.get('other_type') if p.get('type') == 'other' else p.get('type')
            st.write(f"Facility Type: {f_type} | Investment: {format_currency(p.get('inv'))} ({p.get('inv_time','')}) | New Jobs: {p.get('jobs','')} ({p.get('jobs_time','')})")
    else: st.write("No future projects reported.")

    with st.form("final_form"):
        st.subheader("Contact Information")
        u_comp = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_email = st.text_input("Email Address *")
        u_phone = st.text_input("Phone Number *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if all([u_comp, u_name, u_email, u_phone]):
                # Logic for Eligibility
                total_inv = 0.0
                total_jobs = 0
                for p in st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]:
                    try: 
                        total_inv += float(str(p.get('inv','0')).replace('$','').replace(',',''))
                        total_jobs += int(float(str(p.get('jobs','0')).replace(',','')))
                    except: pass
                
                has_fed_ez = False
                if st.session_state.batch_results is not None:
                    has_fed_ez = st.session_state.batch_results['Designations'].str.contains('FEDERAL_EZ').any()
                
                is_eligible = (total_inv >= 500000 or total_jobs >= 2 or has_fed_ez)
                
                if is_eligible:
                    st.success("High Potential Match! Our experts will contact you within 48 hours.")
                else:
                    st.info(f"Thank you {u_name}. Based on current criteria, there may not be immediate matches. We invite you to revisit when new projects arise.")
            else:
                st.error("Please complete all required contact fields.")

    st.button("🔄 Start Over Fresh", on_click=reset_app)

st.markdown(f'<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
