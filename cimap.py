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

# --- REMOVE INTERNAL STREAMLIT PADDING FOR EMBEDS ---
st.markdown("""
    <style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }
    </style>
""", unsafe_allow_html=True)

INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

# --- CSS FOR CLEAN LAYOUT (NO OVERLAP) ---
st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght=300;400;500;600&display=swap');
    
    header[data-testid="stHeader"] {{ display: none; }}
    
    html, body, [class*="css"]  {{
        font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif !important;
        background-color: transparent !important;
    }}
    
    .stApp {{
        background-color: transparent !important;
    }}
    
    div[data-testid="stGridBlock"] > div, 
    div[data-testid="stVerticalBlock"] > div,
    div[data-testid="stForm"] {{
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }}
    
    .stButton>button {{
        background-color: #1a1a1a !important;
        color: white !important;
        border-radius: 50px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        padding: 0.75rem 2rem !important;
        border: none !important;
        font-size: 13px !important;
        letter-spacing: 0.05em !important;
    }}
    
    h1, h2, h3, h4 {{ 
        color: #2c2c2c !important; 
        font-family: 'Inter', sans-serif !important;
        font-weight: 400 !important;
        letter-spacing: -0.02em !important;
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
    if st.session_state.form_data["hist_q"] == "Yes":
        if not st.session_state.form_data["historical_projects"]: return False
        for p in st.session_state.form_data["historical_projects"]:
            if not all([p.get('desc'), p.get('addr'), p.get('inv'), p.get('inv_yr'), p.get('jobs'), p.get('jobs_yr')]):
                return False
            if p.get('type') == "other" and not p.get('type_manual', '').strip():
                return False
    if st.session_state.form_data["fut_q"] == "Yes":
        if not st.session_state.form_data["future_projects"]: return False
        for p in st.session_state.form_data["future_projects"]:
            if not all([p.get('desc'), p.get('addr'), p.get('inv'), p.get('inv_time'), p.get('jobs'), p.get('jobs_time')]):
                return False
            if p.get('type') == "other" and not p.get('type_manual', '').strip():
                return False
    return True

def clean_numeric(val):
    """Helper to convert string values with commas/symbols into clean integers safely."""
    try:
        cleaned = "".join(c for c in str(val) if c.isdigit())
        return int(cleaned) if cleaned else 0
    except:
        return 0

def check_qualifying_opportunity():
    """Evaluates if any submitted projects cross thresholds or fall into the FED_EZ zone."""
    has_valid_project = False
    
    # Track zone eligibility from step 1
    in_federal_ez = False
    if st.session_state.batch_results is not None:
        if any("FED_EZ" in str(x) for x in st.session_state.batch_results['Designations']):
            in_federal_ez = True

    # Screen historical projects
    if st.session_state.form_data.get("hist_q") == "Yes":
        for p in st.session_state.form_data.get("historical_projects", []):
            has_valid_project = True
            inv = clean_numeric(p.get('inv', 0))
            jobs = clean_numeric(p.get('jobs', 0))
            if inv >= 500000 or jobs >= 2 or in_federal_ez:
                return True, "Let's explore further for potential opportunities."

    # Screen future projects
    if st.session_state.form_data.get("fut_q") == "Yes":
        for p in st.session_state.form_data.get("future_projects", []):
            has_valid_project = True
            inv = clean_numeric(p.get('inv', 0))
            jobs = clean_numeric(p.get('jobs', 0))
            if inv >= 500000 or jobs >= 2 or in_federal_ez:
                return True, "Let's explore further for potential opportunities."

    if not has_valid_project:
        return False, "No projects were submitted for review."

    return False, "Based on the information provided, there appears to be no viable opportunity."

def send_email_report(comp, name, email, phone, opportunity_status_text, is_qualifying):
    """Pulls credentials from st.secrets and emails evaluation summary along with an advanced Excel report."""
    try:
        SMTP_SERVER = st.secrets["smtp_server"]
        SMTP_PORT = int(st.secrets["smtp_port"])
        SENDER_EMAIL = st.secrets["sender_email"]
        SENDER_PASSWORD = st.secrets["sender_password"]
        RECIPIENT_EMAIL = "jchoi@incentratax.com"
    except KeyError as e:
        st.error(f"Missing configuration key in secrets file: {e}")
        return False

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = f"Incentra Web Portal Lead: {comp}"

    body = f"An assessment form has been generated via the online tax credit finder App.\n\n"
    body += f"--- CONTACT REGISTRATION ---\n"
    body += f"Company: {comp}\nContact Name: {name}\nEmail: {email}\nPhone: {phone}\n\n"
    body += f"--- AUTOMATED ASSESSMENT OUTCOME ---\n{opportunity_status_text}\n\n"
    
    msg.attach(MIMEText(body, 'plain'))

    # --- GENERATE COMPREHENSIVE MULTI-TAB EXCEL WORKBOOK ---
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        
        # Tab 1: Location Analysis (If address list was processed)
        if st.session_state.batch_results is not None:
            st.session_state.batch_results.to_sheet = "Location Analysis"
            st.session_state.batch_results.to_excel(writer, sheet_name="Location Analysis", index=False)
        else:
            # Fallback placeholder if they skipped uploading a batch file
            pd.DataFrame({"Notice": ["No batch file uploaded during Step 1."]}).to_excel(writer, sheet_name="Location Analysis", index=False)
        
        # Tab 2: Projects Overview (Consolidating form entries & contact cards)
        project_rows = []
        
        # Extract Historical data
        if st.session_state.form_data.get("hist_q") == "Yes":
            for p in st.session_state.form_data.get("historical_projects", []):
                project_rows.append({
                    "Historical/Future": "Historical",
                    "Description": p.get('desc', ''),
                    "Address": p.get('addr', ''),
                    "Facility Type": p.get('type', ''),
                    "Specify Facility Type": p.get('type_manual', ''),
                    "Investment": p.get('inv', ''),
                    "Investment Year": p.get('inv_yr', ''),
                    "New Jobs": p.get('jobs', ''),
                    "Job Creation Year": p.get('jobs_yr', ''),
                    "Company Name": comp,
                    "Contact Name": name,
                    "Email Address": email,
                    "Phone Number": phone
                })
                
        # Extract Future data
        if st.session_state.form_data.get("fut_q") == "Yes":
            for p in st.session_state.form_data.get("future_projects", []):
                project_rows.append({
                    "Historical/Future": "Future",
                    "Description": p.get('desc', ''),
                    "Address": p.get('addr', ''),
                    "Facility Type": p.get('type', ''),
                    "Specify Facility Type": p.get('type_manual', ''),
                    "Investment": p.get('inv', ''),
                    "Investment Year": p.get('inv_time', ''), # Maps to time window
                    "New Jobs": p.get('jobs', ''),
                    "Job Creation Year": p.get('jobs_time', ''), # Maps to time window
                    "Company Name": comp,
                    "Contact Name": name,
                    "Email Address": email,
                    "Phone Number": phone
                })
        
        # Create Dataframe out of records. If empty, ensure column structures remain intact.
        columns_structure = [
            "Historical/Future", "Description", "Address", "Facility Type", "Specify Facility Type",
            "Investment", "Investment Year", "New Jobs", "Job Creation Year", "Company Name",
            "Contact Name", "Email Address", "Phone Number"
        ]
        
        projects_df = pd.DataFrame(project_rows) if project_rows else pd.DataFrame(columns=columns_structure)
        projects_df.to_excel(writer, sheet_name="Projects Analysis", index=False)
        
    # Set Excel binary pointer back to beginning before reading
    excel_buffer.seek(0)
    
    # Attach workbook safely to mail instance
    filename = f"Incentra_Assessment_{comp.replace(' ', '_')}.xlsx"
    part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    part.set_payload(excel_buffer.getvalue())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f"attachment; filename= {filename}")
    msg.attach(part)

    # ----------------------------------------------------
    # EMAIL 2: DYNAMIC USER AUTO-RESPONDER (TO CLIENT USER)
    # ----------------------------------------------------
    user_msg = MIMEMultipart()
    user_msg['From'] = SENDER_EMAIL
    user_msg['To'] = email
    user_msg['Subject'] = f"Incentra Specialty Tax Assessment Receipt - {comp}"

    if is_qualifying:
        user_body = f"Hello {name},\n\n"
        user_body += f"Thank you for your submission. Our team is reviewing your information and will contact you within two business days.\n\n"
        user_body += f"Best regards,\nIncentra Specialty Tax Team"
    else:
        user_body = f"Hello {name},\n\n"
        user_body += f"Thank you for submission.\n\n"
        user_body += f"Based on the information provided, there appears to be no viable tax credit opportunity at this time.\n\n"
        user_body += f"We encourage you to revisit us again when you have new investment or hiring plans.\n\n"
        user_body += f"Best regards,\nIncentra Specialty Tax Team"

    user_msg.attach(MIMEText(user_body, 'plain'))
    
    # --- SMTP TRANSMISSION ENGINE ---
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        
        # Dispatch Internal payload packet to you
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        # Dispatch External verification receipt packet to the user
        server.sendmail(SENDER_EMAIL, email, user_msg.as_string())
        
        server.quit()
        return True
    except Exception as e:
        st.error(f"SMTP Handshake Failure: {e}")
        return False

# --- PAGE ROUTING ---

if st.session_state.page == 'Step 1':
    st.title("STEP 1: Quick Location Analysis")
    st.info("Instructions: Please upload your address list (Excel or CSV).")

    st.markdown("### Download Template")
    example_df = pd.DataFrame({
        "Full Address": [
            "200 Piedmont Ave SE, Atlanta, GA 30334",
            "1200 Glynn Ave, Brunswick, GA 31520",
            "100 Bull St, Savannah, GA 31401"
        ]
    })
    
    csv = example_df.to_csv(index=False).encode('utf-8')
    
    st.download_button(
        label="Download Example Address List (.csv)",
        data=csv,
        file_name="Incentra_Template.csv",
        mime="text/csv",
        help="Download this to see the correct format for your address list."
    )
    st.divider()
    
    uploaded_file = st.file_uploader("Upload File", type=["csv", "xlsx"])

    if uploaded_file:
        try:
            input_data = io.BytesIO(uploaded_file.getvalue())
            
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(input_data)
            else:
                df = pd.read_excel(input_data, engine='openpyxl')
            
            address_col = st.selectbox("Select address column:", df.columns)
            if st.button("Run Batch Analysis"):
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
        st.button("Next: STEP 2: Quick Assessment →", on_click=lambda: st.session_state.update({"page": "Step 2"}))

elif st.session_state.page == 'Step 2':
    st.title("STEP 2: Quick Assessment")
    st.button("← Back to Step 1", on_click=lambda: st.session_state.update({"page": "Step 1"}))
    
    st.subheader("Historical Projects (Past 5 Years)")
    h_q = st.radio("1. Any past investment/hiring?", ["No", "Yes"], index=0 if st.session_state.form_data["hist_q"] == "No" else 1)
    st.session_state.form_data["hist_q"] = h_q
    if h_q == "Yes":
        if not st.session_state.form_data["historical_projects"]: 
            st.session_state.form_data["historical_projects"].append({"id": str(uuid.uuid4())})
        
        hist_to_remove = None
        
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            if 'id' not in p:
                p['id'] = str(uuid.uuid4())
                
            p_id = p['id']
            
            with st.container(border=True):
                st.markdown(f"#### Historical Project {i+1}")
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
                
                if st.button(f"Remove Project {i+1}", key=f"del_h_{p_id}"):
                    hist_to_remove = i

        if hist_to_remove is not None:
            st.session_state.form_data["historical_projects"].pop(hist_to_remove)
            st.rerun()
            
        if st.button("Add Historical Project +"):
            st.session_state.form_data["historical_projects"].append({"id": str(uuid.uuid4())})
            st.rerun()

    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Any future investment/hiring plans?", ["No", "Yes"], index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q
    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]: 
            st.session_state.form_data["future_projects"].append({"id": str(uuid.uuid4())})
        
        fut_to_remove = None
        
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            if 'id' not in p:
                p['id'] = str(uuid.uuid4())
                
            p_id = p['id']
            
            with st.container(border=True):
                st.markdown(f"#### Future Project {i+1}")
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
                
                if st.button(f"Remove Project {i+1}", key=f"del_f_{p_id}"):
                    fut_to_remove = i

        if fut_to_remove is not None:
            st.session_state.form_data["future_projects"].pop(fut_to_remove)
            st.rerun()
            
        if st.button("Add Future Project +"):
            st.session_state.form_data["future_projects"].append({"id": str(uuid.uuid4())})
            st.rerun()

    if st.button("Next: STEP 3 Summary →"):
        if validate_step_2():
            st.session_state.page = 'Step 3'
            st.rerun()
        else:
            st.error("Please fill out all required fields (*) for any projects you added.")

elif st.session_state.page == 'Step 3':
    st.title("STEP 3: Summary & Submission")
    
    st.markdown(f"""
        <style>
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] {{
            background-color: #1a1a1a !important;
            border: none !important;
            transition: all 0.3s ease-in-out !important;
            width: 100% !important;
            border-radius: 50px !important;
        }}
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] p {{
            color: #ffffff !important; 
            font-weight: 500 !important; 
            font-size: 14px !important;
            letter-spacing: 0.05em !important;
        }}
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"]:hover {{
            background-color: #333333 !important;
            transform: scale(1.01) !important;
        }}
        
        div[data-testid="stVerticalBlock"] > div:has(button[key="reset_btn_step3"]) button {{
            background-color: transparent !important;
            color: #1a1a1a !important;
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
    
    st.subheader("Assessment Review")

    # --- INCENTIVE SYSTEM OPPORTUNITY LOGIC FLAG ---
    is_qualifying, evaluation_text = check_qualifying_opportunity()
    if is_qualifying:
        st.success(f"📈 Guidance Notice: {evaluation_text}")
    else:
        st.warning(f"⚠️ Guidance Notice: {evaluation_text}")
    
    with st.container(border=True):
        st.markdown("#### Location Analysis")
        if st.session_state.batch_results is not None:
            total_locs = len(st.session_state.batch_results)
            potential_opps = len(st.session_state.batch_results[
                (st.session_state.batch_results['Valid Address'] == "Yes") & 
                (st.session_state.batch_results['Designations'].str.strip() != "")
            ])
            st.write(f"* **{total_locs}** locations processed and **{potential_opps}** locations may be in a special zone")
        else:
            st.caption("No address batch list was processed in Step 1.")

    with st.container(border=True):
        st.markdown("#### Historical Projects Summary")
        if st.session_state.form_data.get("hist_q") == "No" or not st.session_state.form_data.get("historical_projects"):
            st.write("*No historical projects reported*")
        else:
            for p in st.session_state.form_data["historical_projects"]:
                f_type = p.get('type_manual', '').strip() if p.get('type') == 'other' else p.get('type', '').title()
                f_type = f_type if f_type else "Not Specified"
                raw_inv = p.get('inv', '0').replace(',', '').strip()
                formatted_inv = f"{int(raw_inv):,}" if raw_inv.isdigit() else p.get('inv', '0')
                st.write(f"**{f_type}** | Investment: ${formatted_inv} ({p.get('inv_yr', 'N/A')}) | New Jobs: {p.get('jobs', '0')} ({p.get('jobs_yr', 'N/A')})")

    with st.container(border=True):
        st.markdown("#### Future Projects Summary")
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
        st.subheader("Contact Information")
        
        c1, c2 = st.columns(2, gap="medium")
        u_comp = c1.text_input("Company Name *")
        u_name = c1.text_input("Contact Name *")
        u_email = c2.text_input("Email Address *")
        u_phone = c2.text_input("Phone Number *")
        
        st.write("") 
        
        col_btn_l, col_btn_m, col_btn_r = st.columns([1.5, 1, 1.5])
        with col_btn_m:
            submit_clicked = st.form_submit_button("Submit Assessment")
            
        if submit_clicked:
            if all([u_comp, u_name, u_email, u_phone]):
                with st.spinner("Transmitting assessment report safely..."):
                    email_sent = send_email_report(u_comp, u_name, u_email, u_phone, evaluation_text, is_qualifying)
                
                if email_sent:
                    st.balloons()
                    st.success("Assessment submitted! We will contact you within two business days.")
                else:
                    st.error("Form data recorded locally, but secure mail delivery timed out.")
            else:
                st.warning("Please fill out all contact fields.")

    st.write("") 
    col_back, col_spacer, col_reset = st.columns([1.5, 3, 1.5])
    col_back.button("← Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}), key="back_btn_step3")
    col_reset.button("Start Over", on_click=reset_app, key="reset_btn_step3")

st.markdown('<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
