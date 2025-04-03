"""
QuickBooks OAuth Callback Redirect Script

This file is part of the Embroidery Quoting Tool. Its purpose is to handle
legacy callback URLs that may still be pointing to the application root instead of the OAuth server.

When accessed at the /callback route, it will extract the QueryString parameters
and redirect to the OAuth server's callback endpoint with the same parameters.
"""

import os
import streamlit as st
from urllib.parse import urlencode

# Get the current query parameters
params = st.query_params

# Only proceed if we detect we're at a callback URL with authorization code
if 'code' in params and 'realmId' in params:
    # Extract all query parameters
    code = params.get('code', [''])[0]
    realm_id = params.get('realmId', [''])[0]
    state = params.get('state', [''])[0]
    
    # Construct the new URL for the OAuth server
    oauth_server_url = "http://localhost:8000/callback"
    
    # For deployment, use the Replit domain
    replit_domain = os.environ.get("REPLIT_DOMAINS", "")
    if replit_domain:
        replit_domain = replit_domain.split(',')[0].strip()
        oauth_server_url = f"https://{replit_domain}/callback"
    
    # Add the query parameters
    query_params = {
        'code': code,
        'realmId': realm_id
    }
    
    # Add state if present
    if state:
        query_params['state'] = state
    
    # Construct the full URL with query parameters
    redirect_url = f"{oauth_server_url}?{urlencode(query_params)}"
    
    # Display a message and redirect
    st.markdown("## QuickBooks Authentication")
    st.info("Redirecting to the OAuth server...")
    
    # JavaScript redirect
    st.markdown(f"""
    <script>
        window.location.href = "{redirect_url}";
    </script>
    """, unsafe_allow_html=True)
    
else:
    # Display an error if we're at /callback but without the expected parameters
    st.markdown("## QuickBooks Callback Error")
    st.error("Invalid callback request. Missing required parameters.")
    st.info("Please return to the application and try authenticating again.")
    
    # Add a button to return to the main application
    if st.button("Return to Application"):
        st.query_params.clear()
        st.rerun()