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

# --- 2. PAGE CONFIG & STYLING ---
st.set_page_config(page_title="IncentraTax | Pro Batch Geocoder", layout="wide")

INCENTRA_BLUE = "#213D77"
INCENTRA_GRAY = "#818285"

st.markdown(f"""
    <style>
    header[data-testid="stHeader"] {{ display: none; }}
    
    /* Submit Assessment / Primary Buttons */
    .stButton>button {{
        background-color: {INCENTRA_BLUE};
        color: white;
        border-radius: 4px;
        width: 100%;
        padding: 0.6rem;
        border: none;
    }}
    
    /* Start Over Fresh Button - White Background */
    div[data-testid="stVerticalBlock"] > div:last-child .stButton>button {{
        background-color: white !important;
        color: {INCENTRA_GRAY} !important;
        border: 1px solid #ddd !important;
    }}

    h1, h2, h3 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    .logo-container {{ display: flex; justify-content: center; padding: 20px 0; margin-bottom: 10px; }}
    .logo-container img {{ max-width: 300px; height: auto; }}
    @media (max-width: 640px) {{ .logo-container img {{ max-width: 180px; }} }}
    .footer {{ text-align: center; padding: 20px; color: {INCENTRA_GRAY}; font-size: 12px; margin-top: 50px; border-top: 1px solid #eee; }}
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

# --- 4. HELPERS ---
def format_currency(val):
    try:
        clean_val = str(val).replace('$','').replace(',','')
        return f"${float(clean_val):,.2f}"
    except:
        return str(val)

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
    valid = True
    if st.session_state.form_data["hist_q"] == "Yes":
        for p in st.session_state.form_data["historical_projects"]:
            if not all([p.get('desc'), p.get('addr'), p.get('type'), p.get('inv'), p.get('inv_yr'), p.get('jobs'), p.get('jobs_yr')]): valid = False
            if p.get('type') == 'other' and not p.get('type_manual'): valid = False
    if st.session_state.form_data["fut_q"] == "Yes":
        for p in st.session_state.form_data["future_projects"]:
            if not all([p.get('desc'), p.get('addr'), p.get('type'), p.get('inv'), p.get('inv_time'), p.get('jobs'), p.get('jobs_time')]): valid = False
            if p.get('type') == 'other' and not p.get('type_manual'): valid = False
    return valid

def send_email(u_name, u_email, u_phone, u_company, excel_data, is_eligible):
    try:
        sender_email = st.secrets["email"]["address"]
        sender_password = st.secrets["email"]["password"]
        expert_recipient = "jchoi@incentratax.com"
        
        msg_expert = MIMEMultipart()
        msg_expert['Subject'] = f"New Lead: {u_company}"
        msg_expert.attach(MIMEText(f"Contact: {u_name}\nPhone: {u_phone}\nEmail: {u_email}\nEligible: {is_eligible}", 'plain'))
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(excel_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="Incentra_Assessment.xlsx"')
        msg_expert.attach(part)

        msg_user = MIMEMultipart()
        msg_user['Subject'] = "Incentra Assessment Confirmation"
        msg_user['To'] = u_email
        if is_eligible:
            body = f"Dear {u_name},\n\nThank you for your submission. Our experts are reviewing your details and will contact you within 48 hours to discuss potential tax credit opportunities."
        else:
            body = f"Dear {u_name},\n\nThank you for using our assessment tool. Based on the current criteria, there may be no immediate tax credit opportunities available at this time. However, tax programs change frequently. We invite you to visit us again when you have a new investment project or hiring plan."
        msg_user.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg_expert)
            server.send_message(msg_user)
        return True
    except: return False

# --- ROUTING ---
if st.session_state.page == 'Step 1':
    st.title("🏦 STEP 1: Tax Credit Finder")
    
    st.info("💡 **Instructions:** Upload your address list below. Use the template provided if you're unsure of the format.")
    example_df = pd.DataFrame({"Full Address": ["200 Piedmont Ave SE, Atlanta, GA 30334", "100 Test Lane, Savannah, GA 31401"]})
    example_buffer = io.BytesIO()
    with pd.ExcelWriter(example_buffer, engine='xlsxwriter') as writer:
        example_df.to_excel(writer, index=False, sheet_name='Template')
    st.download_button(label="📂 Download Address List Example (.xlsx)", data=example_buffer.getvalue(), file_name="Incentra_Address_Template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    uploaded_file = st.file_uploader("Upload Your File (Excel or CSV)", type=["csv", "xlsx"])
    if uploaded_file:
        try:
            file_bytes = io.BytesIO(uploaded_file.getvalue())
            df = pd.read_csv(file_bytes) if uploaded_file.name.endswith('.csv') else pd.read_excel(file_bytes, engine='openpyxl')
            address_col = st.selectbox("Select the address column:", df.columns)
            if st.button("🚀 Run Batch Analysis"):
                with st.spinner("Analyzing locations..."):
                    geo_res = census_batch_geocode(df, address_col)
                    if geo_res is not None:
                        # Processing logic (same as previous)
                        df['id'] = range(len(df))
                        merged = df.merge(geo_res[['id', 'lat', 'lon', 'match_status']], on='id')
                        merged['Valid Address'] = merged['match_status'].apply(lambda x: "Yes" if x == "Match" else "No")
                        st.session_state.batch_results = merged[[address_col, 'Valid Address']] # Simple version for summary
                        st.session_state.full_geo_results = merged # Persistent for email
                        st.success("Location Analysis Complete!")
        except Exception as e: st.error(f"Error: {e}")

    if st.session_state.batch_results is not None:
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2 Quick Assessment ➡️", on_click=lambda: st.session_state.update({"page": "Step 2"}))

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
                p['type'] = c1.selectbox(f"1c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], key=f"h3_{i}")
                if p['type'] == 'other': p['type_manual'] = c1.text_input("Specify Facility Type *", value=p.get('type_manual',''), key=f"h3m_{i}")
                p['inv'] = c2.text_input(f"1d. Investment Amount *", value=p.get('inv', ''), key=f"h4_{i}")
                p['inv_yr'] = c2.text_input(f"1e. Investment Year(s) *", value=p.get('inv_yr', ''), key=f"h5_{i}")
                p['jobs'] = c2.text_input(f"1f. Net New Jobs *", value=p.get('jobs', ''), key=f"h6_{i}")
                p['jobs_yr'] = c2.text_input(f"1g. Job Creation Year(s) *", value=p.get('jobs_yr', ''), key=f"h7_{i}")
                if st.button(f"🗑️ Delete Historical Project {i+1}", key=f"del_h_{i}"):
                    st.session_state.form_data["historical_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Historical Project", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    st.divider()
    # Future
    st.subheader("Future Projects (Next 3 Years)")
    f_q = st.radio("2. Do you have plans for investment or job creation in the next 3 years?", ["No", "Yes"], index=0 if st.session_state.form_data["fut_q"] == "No" else 1)
    st.session_state.form_data["fut_q"] = f_q
    if f_q == "Yes":
        if not st.session_state.form_data["future_projects"]: st.session_state.form_data["future_projects"].append({})
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"2a. Description *", value=p.get('desc', ''), key=f"f1_{i}")
                p['addr'] = c1.text_input(f"2b. Potential Address *", value=p.get('addr', ''), key=f"f2_{i}")
                p['type'] = c1.selectbox(f"2c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], key=f"f3_{i}")
                if p['type'] == 'other': p['type_manual'] = c1.text_input("Specify Facility Type *", value=p.get('type_manual',''), key=f"f3m_{i}")
                p['inv'] = c2.text_input(f"2d. Projected Investment Amount *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing of the Investment *", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Number of New Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing of the Job Creation *", value=p.get('jobs_time', ''), key=f"f7_{i}")
                if st.button(f"🗑️ Delete Future Project {i+1}", key=f"del_f_{i}"):
                    st.session_state.form_data["future_projects"].pop(i)
                    st.rerun()
        st.button("➕ Add Another Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    if st.button("Next: STEP 3 Summary & Submit ➡️"):
        if validate_step_2(): st.session_state.page = 'Step 3'; st.rerun()
        else: st.error("⚠️ Please fill out all required fields marked with *")

elif st.session_state.page == 'Step 3':
    st.title("📋 STEP 3: Summary & Submit")
    st.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}))
    
    # --- DATA SUMMARIES ---
    with st.container(border=True):
        st.subheader("📍 Location Analysis Summary")
        if st.session_state.batch_results is not None:
            total_locs = len(st.session_state.batch_results)
            valid_locs = len(st.session_state.batch_results[st.session_state.batch_results['Valid Address'] == 'Yes'])
            st.write(f"**Total Locations Ran:** {total_locs}")
            st.write(f"**Potential Address Matches Identified:** {valid_locs}")
        else:
            st.write("No location file was uploaded.")

    with st.container(border=True):
        st.subheader("📜 Historical Projects Summary")
        if st.session_state.form_data["historical_projects"]:
            for i, p in enumerate(st.session_state.form_data["historical_projects"]):
                st.markdown(f"**Project #{i+1}**")
                st.write(f"- Description: {p.get('desc')}")
                st.write(f"- Facility Type: {p.get('type')} { '('+p.get('type_manual')+')' if p.get('type')=='other' else ''}")
                st.write(f"- Investment ({p.get('inv_yr')}): {format_currency(p.get('inv'))}")
                st.write(f"- New Jobs ({p.get('jobs_yr')}): {p.get('jobs')}")
        else:
            st.write("No historical projects reported.")

    with st.container(border=True):
        st.subheader("🚀 Future Projects Summary")
        if st.session_state.form_data["future_projects"]:
            for i, p in enumerate(st.session_state.form_data["future_projects"]):
                st.markdown(f"**Project #{i+1}**")
                st.write(f"- Description: {p.get('desc')}")
                st.write(f"- Facility Type: {p.get('type')} { '('+p.get('type_manual')+')' if p.get('type')=='other' else ''}")
                st.write(f"- Investment ({p.get('inv_time')}): {format_currency(p.get('inv'))}")
                st.write(f"- New Jobs ({p.get('jobs_time')}): {p.get('jobs')}")
        else:
            st.write("No future projects reported.")

    # --- FINAL SUBMISSION FORM ---
    with st.form("final_form"):
        st.subheader("Contact Information")
        u_comp = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_email = st.text_input("Email Address *")
        u_phone = st.text_input("Phone Number *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if all([u_comp, u_name, u_email, u_phone]):
                # Logic for Eligibility calculation (simplified for example)
                total_inv = 0.0
                total_jobs = 0
                for p in st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]:
                    try:
                        total_inv += float(str(p.get('inv', '0')).replace('$','').replace(',',''))
                        total_jobs += int(float(str(p.get('jobs', '0')).replace(',','')))
                    except: continue
                
                is_eligible = (total_inv >= 500000 or total_jobs >= 2)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    pd.DataFrame(st.session_state.form_data["historical_projects"]).to_excel(writer, sheet_name='Historical')
                    pd.DataFrame(st.session_state.form_data["future_projects"]).to_excel(writer, sheet_name='Future')

                if send_email(u_name, u_email, u_phone, u_comp, output.getvalue(), is_eligible):
                    st.success("✅ Assessment submitted successfully!")
                    if is_eligible: st.balloons()
            else:
                st.warning("Please fill out all contact fields.")

    st.button("🔄 Start Over Fresh", on_click=reset_app)

st.markdown('<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
