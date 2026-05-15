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
    </style>
    """, unsafe_allow_html=True)

# --- 3. HELPERS & EMAIL ---

def delete_project(list_key, index):
    st.session_state.form_data[list_key].pop(index)
    st.rerun()

def send_emails(user_info, is_eligible):
    # Prepare Excel Data
    proj_data = []
    for p in st.session_state.form_data["historical_projects"]:
        proj_data.append({"Category": "Historical", "Facility Type": p.get('type'), "Specify Type": p.get('other_type',''), "Address": p.get('addr'), "Investment": p.get('inv'), "Year": p.get('inv_yr'), "Jobs": p.get('jobs'), "Job Year": p.get('jobs_yr')})
    for p in st.session_state.form_data["future_projects"]:
        proj_data.append({"Category": "Future", "Facility Type": p.get('type'), "Specify Type": p.get('other_type',''), "Address": p.get('addr'), "Investment": p.get('inv'), "Year": p.get('inv_time'), "Jobs": p.get('jobs'), "Job Year": p.get('jobs_time')})
    
    df_projects = pd.DataFrame(proj_data)
    df_contact = pd.DataFrame([user_info])
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_projects.to_excel(writer, sheet_name='Projects', index=False)
        if st.session_state.batch_results is not None:
            st.session_state.batch_results.to_excel(writer, sheet_name='Locations', index=False)
        df_contact.to_excel(writer, sheet_name='ContactInfo', index=False)
    excel_data = output.getvalue()

    # SMTP Configuration (Placeholders - ensure these are set in your environment)
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = "your-email@gmail.com" 
    sender_password = "your-app-password"

    # 1. Internal Notification to jchoi@incentratax.com
    msg_int = MIMEMultipart()
    msg_int['Subject'] = f"New Assessment Lead: {user_info['Company Name']}"
    msg_int['From'] = sender_email
    msg_int['To'] = "jchoi@incentratax.com"
    msg_int.attach(MIMEText(f"New lead submitted.\nEligible: {is_eligible}\nSee attached report."))
    
    part = MIMEBase('application', "octet-stream")
    part.set_payload(excel_data)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="Assessment_Results.xlsx"')
    msg_int.attach(part)

    # 2. User Confirmation
    msg_user = MIMEMultipart()
    msg_user['Subject'] = "IncentraTax Assessment Received"
    msg_user['From'] = sender_email
    msg_user['To'] = user_info['Contact Email']
    
    if is_eligible:
        body = f"Hello {user_info['Contact Name']},\n\nWe have received your assessment. Our experts are reviewing your data and will be in touch within 48 hours."
    else:
        body = f"Hello {user_info['Contact Name']},\n\nThank you for submitting your assessment. Based on our immediate analysis, there may not be any active opportunities at this time. We recommend revisiting when new projects arise."
    msg_user.attach(MIMEText(body))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg_int)
        server.send_message(msg_user)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Error sending email: {e}")
        return False

# --- ROUTING ---

# STEP 1
if st.session_state.page == 'Step 1':
    st.title("Tax Credit Finder")
    st.subheader("STEP 1: Quick Location Analysis")
    
    uploaded_file = st.file_uploader("Upload Address List", type=["csv", "xlsx"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        address_col = st.selectbox("Select address column:", df.columns)
        
        if st.button("🚀 Run Analysis"):
            with st.spinner("Geocoding and analyzing..."):
                # Simulating a match result for demonstration logic
                df['Valid Address'] = "Yes"
                # Logic to show specific designation and Tier
                df['Designation'] = "Federal Empowerment Zone / Tier 1" 
                st.session_state.batch_results = df
                st.success("Analysis Complete!")

    if st.session_state.batch_results is not None:
        st.dataframe(st.session_state.batch_results, use_container_width=True)
        st.button("Next: STEP 2 ➡️", on_click=lambda: st.session_state.update({"page": "Step 2"}))

# STEP 2
elif st.session_state.page == 'Step 2':
    st.title("STEP 2: Project Assessment")
    
    # Validation helper
    def is_step2_complete():
        if st.session_state.form_data["hist_q"] == "Yes":
            for p in st.session_state.form_data["historical_projects"]:
                if not all([p.get('desc'), p.get('addr'), p.get('inv'), p.get('jobs')]): return False
        if st.session_state.form_data["fut_q"] == "Yes":
            for p in st.session_state.form_data["future_projects"]:
                if not all([p.get('desc'), p.get('addr'), p.get('inv'), p.get('jobs')]): return False
        return True

    # Historical Section
    st.subheader("Historical Projects")
    h_q = st.radio("Investment in past 5 years?", ["No", "Yes"], key="hq_radio")
    st.session_state.form_data["hist_q"] = h_q
    
    if h_q == "Yes":
        for i, p in enumerate(st.session_state.form_data["historical_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"Description *", value=p.get('desc',''), key=f"hd_{i}")
                p['addr'] = c1.text_input(f"Address *", value=p.get('addr',''), key=f"ha_{i}")
                p['type'] = c1.selectbox("Type", ["office", "manufacturing", "warehouse", "other"], key=f"ht_{i}")
                if p['type'] == 'other': p['other_type'] = c1.text_input("Specify Type *", key=f"hot_{i}")
                p['inv'] = c2.text_input(f"Investment $ *", value=p.get('inv',''), key=f"hi_{i}")
                p['jobs'] = c2.text_input(f"New Jobs *", value=p.get('jobs',''), key=f"hj_{i}")
                st.button(f"🗑️ Remove Project {i+1}", key=f"hdel_{i}", on_click=delete_project, args=("historical_projects", i))
        st.button("➕ Add Historical Project", on_click=lambda: st.session_state.form_data["historical_projects"].append({}))

    # Future Section
    st.divider()
    st.subheader("Future Projects")
    f_q = st.radio("Investment in next 3 years?", ["No", "Yes"], key="fq_radio")
    st.session_state.form_data["fut_q"] = f_q
    
    if f_q == "Yes":
        for i, p in enumerate(st.session_state.form_data["future_projects"]):
            with st.container(border=True):
                c1, c2 = st.columns(2)
                p['desc'] = c1.text_input(f"Description *", value=p.get('desc',''), key=f"fd_{i}")
                p['addr'] = c1.text_input(f"Address *", value=p.get('addr',''), key=f"fa_{i}")
                p['type'] = c1.selectbox("Type", ["office", "manufacturing", "warehouse", "other"], key=f"ft_{i}")
                if p['type'] == 'other': p['other_type'] = c1.text_input("Specify Type *", key=f"fot_{i}")
                p['inv'] = c2.text_input(f"Projected $ *", value=p.get('inv',''), key=f"fi_{i}")
                p['jobs'] = c2.text_input(f"Projected Jobs *", value=p.get('jobs',''), key=f"fj_{i}")
                st.button(f"🗑️ Remove Project {i+1}", key=f"fdel_{i}", on_click=delete_project, args=("future_projects", i))
        st.button("➕ Add Future Project", on_click=lambda: st.session_state.form_data["future_projects"].append({}))

    if st.button("Next: STEP 3 Summary ➡️"):
        if is_step2_complete():
            st.session_state.page = 'Step 3'
            st.rerun()
        else:
            st.error("Please fill in all required fields (*) for your projects.")

# STEP 3
elif st.session_state.page == 'Step 3':
    st.title("STEP 3: Summary and Submit")
    
    st.subheader("Summary")
    st.markdown("#### Location Analysis")
    if st.session_state.batch_results is not None:
        st.write(f"Analyzed {len(st.session_state.batch_results)} addresses.")
    
    st.markdown("#### Project Overview")
    st.write(f"Historical: {len(st.session_state.form_data['historical_projects'])} | Future: {len(st.session_state.form_data['future_projects'])}")

    with st.form("final_submission"):
        st.subheader("Contact Information")
        c_name = st.text_input("Company Name *")
        p_name = st.text_input("Contact Name *")
        p_email = st.text_input("Contact Email *")
        p_phone = st.text_input("Contact Number *")
        
        if st.form_submit_button("📧 Submit Assessment"):
            if all([c_name, p_name, p_email, p_phone]):
                # Determine Eligibility
                total_inv = 0
                total_jobs = 0
                # Extract numbers for logic
                for p in st.session_state.form_data["historical_projects"] + st.session_state.form_data["future_projects"]:
                    try: 
                        total_inv += float(str(p.get('inv','0')).replace('$','').replace(',',''))
                        total_jobs += int(p.get('jobs','0'))
                    except: pass
                
                # Eligibility Logic
                has_ez = False
                if st.session_state.batch_results is not None:
                    has_ez = st.session_state.batch_results['Designation'].str.contains("Federal Empowerment Zone").any()
                
                eligible = (total_inv >= 500000 or total_jobs >= 2 or has_ez)
                
                user_contact = {
                    "Company Name": c_name, "Contact Name": p_name, 
                    "Contact Email": p_email, "Contact Number": p_phone
                }
                
                if send_emails(user_contact, eligible):
                    if eligible:
                        st.success("Submission Successful! We will contact you within 48 hours.")
                    else:
                        st.info("Submission Received. No immediate opportunities found, but we will notify you if things change.")
            else:
                st.error("Please provide all contact details.")

st.markdown('<div class="footer">© 2026 Incentra Specialty Tax. All rights reserved.</div>', unsafe_allow_html=True)
