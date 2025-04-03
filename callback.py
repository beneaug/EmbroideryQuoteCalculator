"""
QuickBooks OAuth Callback Handler for token exchange
"""
import os
import streamlit as st
import requests
import time
import logging
import traceback
import database
from urllib.parse import urlencode

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - QB_CALLBACK: %(message)s')
logger = logging.getLogger('qb_callback')

# Add a page title
st.set_page_config(page_title="QuickBooks Authentication", layout="centered")

# Process query parameters immediately
params = st.query_params
logger.info(f"Received callback with params: {params}")

# Function to directly exchange authorization code for tokens using REST API
def direct_token_exchange(code, realm_id):
    """
    Exchange authorization code for tokens using direct API call
    and save using the dedicated database function.
    """
    try:
        # Get QuickBooks settings from database
        qb_settings = database.get_quickbooks_settings()
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')

        # Get Replit domain
        replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
        redirect_uri = f"https://{replit_domain}/callback"
        logger.info(f"Using redirect URI: {redirect_uri}")

        # Token exchange endpoint
        token_endpoint = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        
        # Prepare request data
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri
        }

        # Create auth header
        import base64
        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        logger.info("Making token exchange request...")
        logger.info(f"Request details - URI: {redirect_uri}, Code: {code[:10]}...")
        
        # Send the request with properly encoded form data
        response = requests.post(token_endpoint, data=urlencode(data), headers=headers)
        logger.info(f"Token response status: {response.status_code}")
        
        # Only log the first part of the response to avoid logging sensitive data
        resp_text = response.text[:100] + "..." if len(response.text) > 100 else response.text
        logger.info(f"Token response: {resp_text}")

        if response.status_code == 200:
            # Parse response
            token_data = response.json()
            logger.info("Token exchange successful")

            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            token_expiry = time.time() + expires_in

            # Log token details (partially masked)
            if access_token:
                logger.info(f"Access token received (first 5 chars): {access_token[:5]}...")
                logger.info(f"Token expires in: {expires_in} seconds (at epoch {token_expiry})")
            if refresh_token:
                logger.info(f"Refresh token received (first 5 chars): {refresh_token[:5]}...")

            # Save tokens with explicit database calls
            logger.info("Saving tokens to database...")
            
            # Save tokens and verify the results
            access_saved = database.update_quickbooks_token('QB_ACCESS_TOKEN', access_token, token_expiry)
            refresh_saved = database.update_quickbooks_token('QB_REFRESH_TOKEN', refresh_token)
            realm_saved = database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
            
            logger.info(f"Database save results: Access={access_saved}, Refresh={refresh_saved}, Realm={realm_saved}")
            
            if access_saved and refresh_saved and realm_saved:
                logger.info("Tokens and Realm ID successfully saved and verified.")
                return True, "Authentication successful"
            else:
                errors = []
                if not access_saved: errors.append("Access Token")
                if not refresh_saved: errors.append("Refresh Token")
                if not realm_saved: errors.append("Realm ID")
                error_detail = f"Token/Realm saving failed for: {', '.join(errors)}"
                logger.error(error_detail)
                return False, error_detail

        else:
            error_msg = f"Token exchange failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg

    except Exception as e:
        error_msg = f"Unexpected error in token exchange: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return False, error_msg

# Handle callback
if 'code' in params and 'realmId' in params:
    code = params['code']  # Get the code
    realm_id = params['realmId']  # Get the realm ID
    state = params.get('state', '')

    st.title("QuickBooks Authentication")
    st.info("Processing your QuickBooks authorization...")
    logger.info(f"Processing auth code for realm {realm_id}")

    # Immediately exchange code for tokens using direct API call
    success, message = direct_token_exchange(code, realm_id)
    
    if success:
        st.success("✅ Authentication successful!")
        
        # Get Replit domain for redirect
        replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
        success_url = f"https://{replit_domain}?qb_auth_success=true&realm_id={realm_id}"
        
        # Redirect back to main app with success param
        st.markdown(f"""
        <meta http-equiv="refresh" content="2;url={success_url}">
        """, unsafe_allow_html=True)
        st.info("You will be redirected back to the main application...")
    else:
        st.error(f"❌ Authentication failed: {message}")
        
        # Get Replit domain for redirect
        replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
        error_url = f"https://{replit_domain}?qb_auth_error=true&error={message}"
        
        # Redirect back with error
        st.markdown(f"""
        <meta http-equiv="refresh" content="5;url={error_url}">
        """, unsafe_allow_html=True)
        st.warning("You will be redirected back to the main application...")
        
        # Show technical details for debugging
        with st.expander("Technical Details"):
            st.code(message)
else:
    logger.warning("Callback received without required parameters")
    st.title("Invalid Callback")
    st.error("Missing required parameters")

    # Show what parameters were received
    with st.expander("Debug Information"):
        st.json(dict(params))

    # Redirect back to main app
    replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
    error_url = f"https://{replit_domain}?qb_auth_error=true&error=Missing+required+parameters"
    st.markdown(f'<meta http-equiv="refresh" content="5;url={error_url}">', unsafe_allow_html=True)