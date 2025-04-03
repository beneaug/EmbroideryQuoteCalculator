
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

# Get query parameters 
params = st.query_params
logger.info(f"Received callback with params: {params}")

# Handle callback
if 'code' in params and 'realmId' in params:
    code = params['code']
    realm_id = params['realmId']

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
        response = requests.post(token_endpoint, data=data, headers=headers)
        logger.info(f"Token response status: {response.status_code}")

        if response.status_code == 200:
            # Parse response
            token_data = response.json()
            logger.info("Token exchange successful")
            
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            token_expiry = time.time() + expires_in

            # Save tokens
            logger.info("Saving tokens to database...")
            database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
            database.update_setting("quickbooks_settings", "QB_ACCESS_TOKEN", access_token)
            database.update_setting("quickbooks_settings", "QB_REFRESH_TOKEN", refresh_token)

            # Update token expiry
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
                    logger.info("Token expiry updated successfully")
                except Exception as db_err:
                    logger.error(f"Database error updating access token expiry: {str(db_err)}")
                    logger.error(traceback.format_exc())
                finally:
                    conn.close()

            st.success("✅ Authentication successful!")
            logger.info("Authentication completed successfully")
            st.info("You can now return to the main application.")

            # Add verification
            verify_settings = database.get_quickbooks_settings()
            saved_access = verify_settings.get('QB_ACCESS_TOKEN', {}).get('value', '')
            saved_refresh = verify_settings.get('QB_REFRESH_TOKEN', {}).get('value', '')
            logger.info(f"Verification - Access token saved: {bool(saved_access)}")
            logger.info(f"Verification - Refresh token saved: {bool(saved_refresh)}")

            # Clear parameters on return
            if st.button("Return to Application"):
                st.query_params.clear()
                st.rerun()
        else:
            error_msg = f"Token exchange failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            st.error(error_msg)

            # Show detailed error information
            with st.expander("Error Details"):
                st.code(response.text)

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
        
    if st.button("Return to Application"):
        st.query_params.clear()
        st.rerun()
