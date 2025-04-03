"""
Placeholder callback handler for embroidery application

This file previously contained QuickBooks OAuth callback handling.
That functionality has been removed as part of the QuickBooks integration removal.
"""
import os
import streamlit as st
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - CALLBACK: %(message)s')
logger = logging.getLogger('callback')

# Add a page title
st.set_page_config(page_title="Embroidery Calculator", layout="centered")

# Process query parameters immediately
params = st.query_params
logger.info(f"Received callback with params: {params}")

# Display a simple message
st.title("Embroidery Calculator")
st.info("External integrations have been disabled in this version.")

# Redirect back to main app after 3 seconds
replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
redirect_url = f"https://{replit_domain}"
st.markdown(f'<meta http-equiv="refresh" content="3;url={redirect_url}">', unsafe_allow_html=True)
st.write("Redirecting back to the main application...")

# For debugging purposes
with st.expander("Debug Information"):
    st.json(dict(params))