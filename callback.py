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

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - QB_CALLBACK: %(message)s')
logger = logging.getLogger('qb_callback')

# Add a page title
st.set_page_config(page_title="QuickBooks Authentication", layout="centered")

# Handle callback
if 'code' in st.query_params and 'realmId' in st.query_params:
    code = st.query_params['code']
    realm_id = st.query_params['realmId']

    st.title("QuickBooks Authentication")
    st.info("Processing your QuickBooks authorization...")

    try:
        # Get settings
        qb_settings = database.get_quickbooks_settings()
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')

        # Get Replit domain
        replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
        redirect_uri = f"https://{replit_domain}/callback" if replit_domain else "https://embroideryquotecalculator.juliewoodland.repl.co/callback"

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

        # Make token request
        response = requests.post(token_endpoint, data=data, headers=headers)

        if response.status_code == 200:
            # Parse response
            token_data = response.json()
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            token_expiry = time.time() + expires_in

            # Save tokens
            database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
            database.update_setting("quickbooks_settings", "QB_ACCESS_TOKEN", access_token)
            database.update_setting("quickbooks_settings", "QB_REFRESH_TOKEN", refresh_token)

            # Update token expiry using direct SQL for robustness.
            conn = database.get_connection()
            if conn:
                try:
                    from sqlalchemy import text
                    conn.execute(text("""
                        UPDATE quickbooks_settings 
                        SET value = :value, token_expires_at = :expires, updated_at = CURRENT_TIMESTAMP 
                        WHERE name = 'QB_ACCESS_TOKEN'
                    """), {"value": access_token, "expires": token_expiry})
                    conn.commit()
                except Exception as db_err:
                    logger.error(f"Database error updating access token expiry: {str(db_err)}")
                    logger.error(traceback.format_exc())
                finally:
                    conn.close()


            st.success("✅ Authentication successful!")
            st.info("You can now return to the main application.")

            # Clear parameters on return
            if st.button("Return to Application"):
                st.query_params.clear()
                st.rerun()
        else:
            error_msg = f"Token exchange failed: {response.status_code} - {response.text}"
            st.error(error_msg)
            logger.error(error_msg)

    except Exception as e:
        logger.error(f"Error in callback: {str(e)}")
        logger.error(traceback.format_exc())
        st.error(f"Authentication error: {str(e)}")
else:
    st.title("Invalid Callback")
    st.error("Missing required parameters")
    if st.button("Return to Application"):
        st.query_params.clear()
        st.rerun()