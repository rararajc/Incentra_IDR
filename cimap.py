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
    h1, h2, h3, h4 {{ color: {INCENTRA_BLUE}; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    .footer {{ text-align: center; padding: 20px; color: {INCENTRA_GRAY}; font-size: 12px; margin-top: 50px; border-top: 1px solid #eee; }}
    .logo-container {{ display: flex; justify-content: center; padding: 10px; }}
    .logo-container img {{ max-width: 100%; height: auto; width: 280px; }}
    </style>
    """, unsafe_allow_html=True)

# --- 3. HELPERS ---
@st.cache_data
def load_geodata():
    # Placeholder for shapefile loading
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

def remove_project(category, index):
    st.session_state.form_data[category].pop(index)
    st.rerun()

def send_submission_emails(user_info, is_eligible):
    # Prepare project list for Excel
    all_projs = []
    for p in st.session_state.form_data["historical_projects"]:
        all_projs.append({
            "Historical/Future": "Historical", "Facility Type": p.get('type'), 
            "Specify Facility Type": p.get('other_type', 'N/A'), "Address": p.get('addr'),
            "Investment Amount": p.get('inv'), "Investment Year": p.get('inv_yr'),
            "Number of New Jobs": p.get('jobs'), "Job Creation Year": p.get('jobs_yr'),
            "Company Name": user_info['comp'], "Contact Name": user_info['name'],
            "Contact Email": user_info['email'], "Contact Number": user_info['phone']
        })
    for p in st.session_state.form_data["future_projects"]:
        all_projs.append({
            "Historical/Future": "Future", "Facility Type": p.get('type'), 
            "Specify Facility Type": p.get('other_type', 'N/A'), "Address": p.get('addr'),
            "Investment Amount": p.get('inv'), "Investment Year": p.get('inv_time'),
            "Number of New Jobs": p.get('jobs'), "Job Creation Year": p.get('jobs_time'),
            "Company Name": user_info['comp'], "Contact Name": user_info['name'],
            "Contact Email": user_info['email'], "Contact Number": user_info['phone']
        })
    
    df_proj = pd.DataFrame(all_projs)
    
    # Create Excel in Memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_proj.to_excel(writer, sheet_name='Project Assessment', index=False)
        if st.session_state.batch_results is not None:
            st.session_state.batch_results.to_excel(writer, sheet_name='Locations', index=False)
    excel_data = output.getvalue()

    # SMTP Setup
    # Note: Replace placeholders with real credentials
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = "your-app-email@gmail.com"
    sender_pass = "your-app-password"

    # Email to jchoi@incentratax.com
    msg_internal = MIMEMultipart()
    msg_internal['Subject'] = f"New Tax Assessment: {user_info['comp']}"
    msg_internal['To'] = "jchoi@incentratax.com"
    msg_internal.attach(MIMEText(f"A new assessment has been submitted by {user_info['name']}."))
    
    part = MIMEBase('application', "octet-stream")
    part.set_payload(excel_data)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="Assessment_Results.xlsx"')
    msg_internal.attach(part)

    # Email to User
    msg_user = MIMEMultipart()
    msg_user['Subject'] = "IncentraTax Assessment Received"
    msg_user['To'] = user_info['email']
    if is_eligible:
        body = f"Hello {user_info['name']},\n\nWe have received your assessment and are currently reviewing it. Our experts will be in touch within 48 hours."
    else:
        body = f"Hello {user_info['name']},\n\nThank you for your submission. Based on the current details, there may be no immediate opportunities. Please revisit us when new projects arise."
    msg_user.attach(MIMEText(body))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_pass)
        server.send_message(msg_internal)
        server.send_message(msg_user)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Email delivery failed: {e}")
        return False

# --- ROUTING ---

# STEP 1: ANALYSIS
if st.session_state.page == 'Step 1':
    st.title("Tax Credit Finder")
    st.subheader("STEP 1: Quick Location Analysis")
    
    uploaded_file = st.file_uploader("Upload Address List", type=["csv", "xlsx"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        address_col = st.selectbox("Select address column:", df.columns)
        
        if st.button("🚀 Run Analysis"):
            with st.spinner("Analyzing locations..."):
                # Simulation for logic flow
                df['Valid Address'] = "Yes"
                df['Designations'] = "Tier 1 Zone / Federal Empowerment Zone" # Replace with actual geo-join results
                st.session_state.batch_results = df[[address_col, 'Valid Address', 'Designations']]
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
                p['type'] = c1.selectbox(f"1c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], index=["office", "manufacturing", "warehouse", "other"].index(p.get('type', 'office')), key=f"h3_{i}")
                if p['type'] == 'other':
                    p['other_type'] = c1.text_input("Please specify facility type *", value=p.get('other_type', ''), key=f"h3_other_{i}")
                p['inv'] = c2.text_input(f"1d. Investment Amount *", value=p.get('inv', ''), key=f"h4_{i}")
                p['inv_yr'] = c2.text_input(f"1e. Year(s) *", value=p.get('inv_yr', ''), key=f"h5_{i}")
                p['jobs'] = c2.text_input(f"1f. Net New Jobs *", value=p.get('jobs', ''), key=f"h6_{i}")
                p['jobs_yr'] = c2.text_input(f"1g. Year(s) *", value=p.get('jobs_yr', ''), key=f"h7_{i}")
                st.button(f"🗑️ Delete Project #{i+1}", key=f"del_h_{i}", on_click=remove_project, args=("historical_projects", i))
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
                p['type'] = c1.selectbox(f"2c. Facility Type *", ["office", "manufacturing", "warehouse", "other"], index=["office", "manufacturing", "warehouse", "other"].index(p.get('type', 'office')), key=f"f3_{i}")
                if p['type'] == 'other':
                    p['other_type'] = c1.text_input("Please specify facility type *", value=p.get('other_type', ''), key=f"f3_other_{i}")
                p['inv'] = c2.text_input(f"2d. Projected Investment *", value=p.get('inv', ''), key=f"f4_{i}")
                p['inv_time'] = c2.text_input(f"2e. Timing *", value=p.get('inv_time', ''), key=f"f5_{i}")
                p['jobs'] = c2.text_input(f"2f. Projected Jobs *", value=p.get('jobs', ''), key=f"f6_{i}")
                p['jobs_time'] = c2.text_input(f"2g. Timing *", value=p.get('jobs_time', ''), key=f"f7_{i}")
                st.button(f"🗑️ Delete Project #{i+1}", key=f"del_f_{i}", on_click=remove_project, args=("future_projects", i))
        st.button("➕ Add Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    if st.button("Next: STEP 3 Summary ➡️"):
        # Simple validation: ensure required fields are not empty
        valid = True
        for proj_list in [st.session_state.form_data["historical_projects"], st.session_state.form_data["future_projects"]]:
            for p in proj_list:
                if not p.get('desc') or not p.get('addr') or not p.get('inv'): valid = False
        if valid:
            st.session_state.page = 'Step 3'
            st.rerun()
        else:
            st.error("Please complete all project fields marked with *.")

# STEP 3: SUMMARY
elif st.session_state.page == 'Step 3':
    st.title("STEP 3: Summary and Submit")
    st.button("⬅️ Back to Step 2", on_click=lambda: st.session_state.update({"page": "Step 2"}))
    
    st.subheader("Summary")
    st.markdown("#### Location Analysis")
    if st.session_state.batch_results is not None:
        total = len(st.session_state.batch_results)
        st.write(f"{total} locations processed.")

    st.markdown("#### Historical Projects")
    if st.session_state.form_data["historical_projects"]:
        for p in st.session_state.form_data["historical_projects"]:
            f_type = p.get('other_type') if p.get('type') == 'other' else p.get('type')
            st.write(f"Type: {f_type} | Investment: {format_currency(p.get('inv'))} | Jobs: {p.get('jobs')}")
    else: st.write("None.")

    st.markdown("#### Future Projects")
    if st.session_state.form_data["future_projects"]:
        for p in st.session_state.form_data["future_projects"]:
            f_type = p.get('other_type') if p.get('type') == 'other' else p.get('type')
            st.write(f"Type: {f_type} | Investment: {format_currency(p.get('inv'))} | Jobs: {p.get('jobs')}")
    else: st.write("None.")

    with st.form("final_form"):
        st.subheader("Contact Information")
        u_comp = st.text_input("Company Name *")
        u_name = st.text_input("Contact Name *")
        u_email = st.text_input("Email Address *")
        u_phone = st.text_input("Phone Number *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if all([u_comp, u_name, u_email, u_phone]):
                # Determine eligibility
                inv_total = 0.0
                job_total = 0
                for p in st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]:
                    try: 
                        inv_total += float(str(p.get('inv','0')).replace('$','').replace(',',''))
                        job_total += int(p.get('jobs','0'))
                    except: pass
                
                fed_ez = False
                if st.session_state.batch_results is not None:
                    fed_ez = st.session_state.batch_results['Designations'].str.contains('Federal Empowerment Zone').any()
                
                is_eligible = (inv_total >= 500000 or job_total >= 2 or fed_ez)
                
                u_info = {"comp": u_comp, "name": u_name, "email": u_email, "phone": u_phone}
                if send_submission_emails(u_info, is_eligible):
                    st.success("Submission complete! Check your email for confirmation.")
            else:
                st.error("Please fill all contact fields.")

    st.button("🔄 Start Over Fresh", on_click=reset_app)

st.markdown(f'<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
