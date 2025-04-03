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

# Get query parameters 
params = st.experimental_get_query_params()
logger.info(f"Received callback with params: {params}")

# Handle callback
if 'code' in params and 'realmId' in params:
    code = params['code'][0]  # Get first value since query params are lists
    realm_id = params['realmId'][0]
    state = params.get('state', [''])[0]

    st.title("QuickBooks Authentication")
    st.info("Processing your QuickBooks authorization...")
    logger.info(f"Processing auth code for realm {realm_id}")

    try:
        # Get settings
        qb_settings = database.get_quickbooks_settings()
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')

        # Get Replit domain
        replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
        redirect_uri = f"https://{replit_domain}/callback"
        logger.info(f"Using redirect URI: {redirect_uri}")

        # Exchange code for tokens
        token_endpoint = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

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
        response = requests.post(token_endpoint, data=urlencode(data), headers=headers)
        logger.info(f"Token response status: {response.status_code}")
        logger.info(f"Token response: {response.text}")

        if response.status_code == 200:
            # Parse response
            token_data = response.json()
            logger.info("Token exchange successful")

            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            token_expiry = time.time() + expires_in

            # Save tokens with explicit database calls
            logger.info("Saving tokens to database...")
            try:
                database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
                database.update_quickbooks_token('QB_ACCESS_TOKEN', access_token, token_expiry)
                database.update_quickbooks_token('QB_REFRESH_TOKEN', refresh_token)
                logger.info("Tokens saved successfully")

                # Redirect back to main app with success
                success_url = f"https://{replit_domain}?qb_auth_success=true&realm_id={realm_id}"
                st.success("✅ Authentication successful!")
                st.markdown(f'<meta http-equiv="refresh" content="2;url={success_url}">', unsafe_allow_html=True)
                st.info("You will be redirected back to the main application...")

            except Exception as save_error:
                logger.error(f"Error saving tokens: {str(save_error)}")
                st.error(f"Failed to save authentication tokens: {str(save_error)}")

        else:
            error_msg = f"Token exchange failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            st.error(error_msg)

            # Redirect back with error
            error_url = f"https://{replit_domain}?qb_auth_error=true&error={error_msg}"
            st.markdown(f'<meta http-equiv="refresh" content="5;url={error_url}">', unsafe_allow_html=True)

    except Exception as e:
        logger.error(f"Error in callback: {str(e)}")
        logger.error(traceback.format_exc())
        st.error(f"Authentication error: {str(e)}")

        # Show technical details for debugging
        with st.expander("Technical Details"):
            st.code(traceback.format_exc())
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