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
import uuid

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
        if not st.session_state.form_data["historical_projects"]: 
            st.session_state.form_data["historical_projects"].append({"id": str(uuid.uuid4())})
        
        # Track items marked for deletion
        hist_to_remove = None
        
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            # Ensure every project has a unique permanent ID for widget keys
            if 'id' not in p:
                p['id'] = str(uuid.uuid4())
                
            p_id = p['id']
            
            with st.container(border=True):
                st.markdown(f"#### 🏛️ Historical Project {i+1}")
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"1a. Project Description *", value=p.get('desc', ''), key=f"h1_{p_id}")
                p['addr'] = c1.text_input(f"1b. Project Address *", value=p.get('addr', ''), key=f"h2_{p_id}")
                p['type'] = c1.selectbox(f"1c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], key=f"h3_{p_id}")
                if p['type'] == "other":
                    p['type_manual'] = c1.text_input(f"Specify Facility Type *", value=p.get('type_manual', ''), key=f"h_other_{p_id}")
                p['inv'] = c2.text_input(f"1d. Investment Amount ($USD) *", value=p.get('inv', ''), key=f"h4_{p_id}")
                p['inv_yr'] = c2.text_input(f"1e. Investment Year(s) *", value=p.get('inv_yr', ''), key=f"h5_{p_id}")
                p['jobs'] = c2.text_input(f"1f. Number of Net New Jobs Created *", value=p.get('jobs', ''), key=f"h6_{p_id}")
                p['jobs_yr'] = c2.text_input(f"1g. Job Creation Year(s) *", value=p.get('jobs_yr', ''), key=f"h7_{p_id}")
                
                if st.button(f"🗑️ Remove Project {i+1}", key=f"del_h_{p_id}"):
                    hist_to_remove = i

        if hist_to_remove is not None:
            st.session_state.form_data["historical_projects"].pop(hist_to_remove)
            st.rerun()
            
        if st.button("➕ Add Historical Project"):
            st.session_state.form_data["historical_projects"].append({"id": str(uuid.uuid4())})
            st.rerun()

    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Any future investment/hiring plans?", ["No", "Yes"], index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q
    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]: 
            st.session_state.form_data["future_projects"].append({"id": str(uuid.uuid4())})
        
        # Track items marked for deletion
        fut_to_remove = None
        
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            if 'id' not in p:
                p['id'] = str(uuid.uuid4())
                
            p_id = p['id']
            
            with st.container(border=True):
                st.markdown(f"#### 🚀 Future Project {i+1}")
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Project Description *", value=p.get('desc', ''), key=f"f1_{p_id}")
                p['addr'] = c1.text_input(f"2b. Project Address *", value=p.get('addr', ''), key=f"f2_{p_id}")
                p['type'] = c1.selectbox(f"2c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], key=f"f3_{p_id}")
                if p['type'] == "other":
                    p['type_manual'] = c1.text_input(f"Specify Facility Type *", value=p.get('type_manual', ''), key=f"f_other_{p_id}")
                p['inv'] = c2.text_input(f"2d. Projected Investment Amount ($USD) *", value=p.get('inv', ''), key=f"f4_{p_id}")
                p['inv_time'] = c2.text_input(f"2e. Investment Timing *", value=p.get('inv_time', ''), key=f"f5_{p_id}")
                p['jobs'] = c2.text_input(f"2f. Projected Number of Net New Jobs *", value=p.get('jobs', ''), key=f"f6_{p_id}")
                p['jobs_time'] = c2.text_input(f"2g. Job Creation Timing *", value=p.get('jobs_time', ''), key=f"f7_{p_id}")
                
                if st.button(f"🗑️ Remove Project {i+1}", key=f"del_f_{p_id}"):
                    fut_to_remove = i

        if fut_to_remove is not None:
            st.session_state.form_data["future_projects"].pop(fut_to_remove)
            st.rerun()
            
        if st.button("➕ Add Future Project"):
            st.session_state.form_data["future_projects"].append({"id": str(uuid.uuid4())})
            st.rerun()

    if st.button("Next: STEP 3 Summary ➡️"):
        if validate_step_2():
            st.session_state.page = 'Step 3'
            st.rerun()
        else:
            st.error("⚠️ Please fill out all required fields (*) for any projects you added.")

elif st.session_state.page == 'Step 3':
    st.title("📋 STEP 3: Summary & Submission")
    
    # Inject custom CSS for precise Step 3 layout overrides
    st.markdown(f"""
        <style>
        /* Create a highlighted row wrapper for the Submit row area inside the form */
        div.submit-row-highlight {{
            background-color: #f4f6f9 !important; /* Soft premium gray/blue tint */
            border-left: 5px solid {INCENTRA_BLUE} !important; /* Thick corporate blue accent edge */
            padding: 20px !important;
            border-radius: 6px !important;
            margin-top: 25px !important;
            margin-bottom: 15px !important;
            display: flex !important;
            justify-content: center !important; /* Forces row contents to center perfectly */
            align-items: center !important;
        }}
        
        /* Force the inner button element to center itself exactly */
        div.submit-row-highlight > div {{
            width: 100% !important;
            max-width: 320px !important; /* Constrains the button width so it doesn't stretch huge */
            margin: 0 auto !important;
        }}
        
        /* Force Form Submit Button to be Navy Blue with Bold Red Font and Heavy Highlights */
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] {{
            background-color: {INCENTRA_BLUE} !important;
            border: 2px solid #FF0000 !important;
            box-shadow: 0px 4px 15px rgba(255, 0, 0, 0.2) !important;
            transition: all 0.3s ease-in-out !important;
            width: 100% !important;
        }}
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] p {{
            color: #FF0000 !important; 
            font-weight: bold !important; 
            font-size: 18px !important;
            letter-spacing: 0.5px !important;
        }}
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"]:hover {{
            background-color: #162a53 !important;
            border-color: #FF3333 !important;
            transform: scale(1.03) !important; /* Slightly increased scale pop */
            box-shadow: 0px 6px 20px rgba(255, 0, 0, 0.4) !important;
        }}
        
        /* Transform 'Start Over Fresh' Button into a clean text link style aligned to the right */
        div[data-testid="stVerticalBlock"] > div:has(button[key="reset_btn_step3"]) button {{
            background-color: transparent !important;
            color: {INCENTRA_BLUE} !important;
            border: none !important;
            text-decoration: underline !important;
            text-align: right !important;
            box-shadow: none !important;
            padding: 0.6rem 0rem !important;
        }}
        div[data-testid="stVerticalBlock"] > div:has(button[key="reset_btn_step3"]) button:hover {{
            color: {INCENTRA_GRAY} !important;
            background-color: transparent !important;
        }}
        </style>
    """, unsafe_allow_html=True)
    
    # --- TOP SECTION: FULL WIDTH ASSESSMENT REVIEW ---
    st.subheader("📊 Assessment Review")
    
    # Location Analysis
    with st.container(border=True):
        st.markdown("#### 📍 Location Analysis")
        if st.session_state.batch_results is not None:
            total_locs = len(st.session_state.batch_results)
            
            potential_opps = len(st.session_state.batch_results[
                (st.session_state.batch_results['Valid Address'] == "Yes") & 
                (st.session_state.batch_results['Designations'].str.strip() != "")
            ])
            
            st.write(f"* **{total_locs}** locations processed and **{potential_opps}** locations may be in a special zone")
        else:
            st.caption("No address batch list was processed in Step 1.")

    # Historical Projects Summary
    with st.container(border=True):
        st.markdown("#### 🏛️ Historical Projects Summary")
        if st.session_state.form_data.get("hist_q") == "No" or not st.session_state.form_data.get("historical_projects"):
            st.write("*No historical projects reported*")
        else:
            for p in st.session_state.form_data["historical_projects"]:
                f_type = p.get('type_manual', '').strip() if p.get('type') == 'other' else p.get('type', '').title()
                f_type = f_type if f_type else "Not Specified"
                
                raw_inv = p.get('inv', '0').replace(',', '').strip()
                formatted_inv = f"{int(raw_inv):,}" if raw_inv.isdigit() else p.get('inv', '0')
                
                st.write(f"**{f_type}** | Investment: ${formatted_inv} ({p.get('inv_yr', 'N/A')}) | New Jobs: {p.get('jobs', '0')} ({p.get('jobs_yr', 'N/A')})")

    # Future Projects Summary
    with st.container(border=True):
        st.markdown("#### 🚀 Future Projects Summary")
        if st.session_state.form_data.get("fut_q") == "No" or not st.session_state.form_data.get("future_projects"):
            st.write("*No future projects reported*")
        else:
            for p in st.session_state.form_data["future_projects"]:
                f_type = p.get('type_manual', '').strip() if p.get('type') == 'other' else p.get('type', '').title()
                f_type = f_type if f_type else "Not Specified"
                
                raw_inv = p.get('inv', '0').replace(',', '').strip()
                formatted_inv = f"{int(raw_inv):,}" if raw_inv.isdigit() else p.get('inv', '0')
                
                st.write(f"**{f_type}** | Investment: ${formatted_inv} ({p.get('inv_time', 'N/A')}) | New Jobs: {p.get('jobs', '0')} ({p.get('jobs_time', 'N/A')})")
    
    st.divider()

    # --- BOTTOM SECTION: CONTACT FORM & NAVIGATION ---
    with st.form("final_form"):
        st.subheader("👤 Contact Information")
        
        c1, c2 = st.columns(2, gap="medium")
        u_comp = c1.text_input("Company Name *")
        u_name = c1.text_input("Contact Name *")
        u_email = c2.text_input("Email Address *")
        u_phone = c2.text_input("Phone Number *")
        
        # Open custom raw HTML container block to force exact row highlighting and flexbox centering
        st.markdown('<div class="submit-row-highlight"><div>', unsafe_allow_html=True)
        submit_clicked = st.form_submit_button("📧 Submit Assessment")
        st.markdown('</div></div>', unsafe_allow_html=True) # Clean up custom containers Safely
            
        if submit_clicked:
            if all([u_comp, u_name, u_email, u_phone]):
                st.balloons()
                st.success("Assessment submitted! We will contact you within 48 hours.")
            else:
                st.warning("Please fill out all contact fields.")

    # Lower Footer Row containing navigation tools
    st.write("") 
    col_back, col_spacer, col_reset = st.columns([1.5, 3, 1.5])
    col_back.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}), key="back_btn_step3")
    col_reset.button("🔄 Start Over Fresh", on_click=reset_app, key="reset_btn_step3")

st.markdown('<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
