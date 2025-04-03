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
import requests
import time
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('qb_callback')

# Add a page title
st.set_page_config(page_title="QuickBooks OAuth Callback", layout="centered")

# Get the current query parameters
params = st.query_params

# Get Replit domain for this instance
replit_domain = os.environ.get("REPLIT_DOMAINS", "")
if replit_domain:
    replit_domain = replit_domain.split(',')[0].strip()
    
# Get the full URL from the URL parameter or query params
full_url = st.query_params.get("url", None)

# Function to directly handle the OAuth token exchange
def handle_token_exchange(code, realm_id):
    """
    Directly handle the token exchange with QuickBooks OAuth API
    without relying on the separate OAuth server
    """
    try:
        # Import database module for token storage
        import database
        
        # Get QuickBooks settings
        qb_settings = database.get_quickbooks_settings()
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        redirect_uri = qb_settings.get('QB_REDIRECT_URI', {}).get('value', '')
        
        # If no redirect URI in database, construct one
        if not redirect_uri and replit_domain:
            redirect_uri = f"https://{replit_domain}/callback"
            
        # Import the AuthClient
        try:
            from intuitlib.client import AuthClient
        except ImportError:
            st.error("Failed to import AuthClient from intuitlib. Please ensure it's installed.")
            return False, "Import Error"
            
        # Initialize the auth client
        try:
            auth_client = AuthClient(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                environment="sandbox"  # Use 'production' for live app
            )
            
            # Exchange the code for tokens
            logger.info(f"Exchanging authorization code for tokens... (code starts with {code[:5]})")
            auth_client.get_bearer_token(code, realm_id)
            logger.info("Token exchange successful!")
            
            # Save the tokens in the database
            logger.info("Saving tokens to database...")
            
            # Save realm ID
            database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
            
            # First, ensure the token records exist by using update_setting
            database.update_setting("quickbooks_settings", "QB_ACCESS_TOKEN", auth_client.access_token)
            database.update_setting("quickbooks_settings", "QB_REFRESH_TOKEN", auth_client.refresh_token)
            
            # Then update with the specialized token function that handles expiry
            token_expiry = time.time() + auth_client.expires_in
            token_result = database.update_quickbooks_token("QB_ACCESS_TOKEN", auth_client.access_token, token_expiry)
            refresh_result = database.update_quickbooks_token("QB_REFRESH_TOKEN", auth_client.refresh_token)
            
            # Verify tokens were saved correctly
            qb_settings = database.get_quickbooks_settings()
            access_token_saved = qb_settings.get('QB_ACCESS_TOKEN', {}).get('value', '')
            refresh_token_saved = qb_settings.get('QB_REFRESH_TOKEN', {}).get('value', '')
            
            if not access_token_saved or not refresh_token_saved:
                logger.warning("Token verification failed! Using alternative storage method...")
                # Direct SQL storage in emergency
                conn = database.get_connection()
                if conn:
                    from sqlalchemy import text
                    # Update access token
                    conn.execute(text("""
                        UPDATE quickbooks_settings 
                        SET value = :value, token_expires_at = :expires, updated_at = CURRENT_TIMESTAMP 
                        WHERE name = 'QB_ACCESS_TOKEN'
                    """), {"value": auth_client.access_token, "expires": token_expiry})
                    
                    # Update refresh token
                    conn.execute(text("""
                        UPDATE quickbooks_settings 
                        SET value = :value, updated_at = CURRENT_TIMESTAMP 
                        WHERE name = 'QB_REFRESH_TOKEN'
                    """), {"value": auth_client.refresh_token})
                    
                    conn.commit()
                    conn.close()
            
            return True, "Authentication successful"
            
        except Exception as auth_error:
            logger.error(f"Authentication error: {str(auth_error)}")
            return False, f"Authentication error: {str(auth_error)}"
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return False, f"Unexpected error: {str(e)}"

# Only proceed if we detect we're at a callback URL with authorization code
if 'code' in params and 'realmId' in params:
    # Extract all query parameters
    code = params.get('code')
    realm_id = params.get('realmId')
    state = params.get('state', '')
    
    # Display a message
    st.markdown("## QuickBooks Authentication")
    st.info("Processing authentication callback...")
    
    # Show the parameters (redacted for security)
    st.write(f"Received code: {code[:5]}...{code[-5:]}")
    st.write(f"Received realm ID: {realm_id}")
    
    # Display a spinner while processing
    with st.spinner("Exchanging authorization code for tokens..."):
        # Handle the token exchange directly in this script
        success, message = handle_token_exchange(code, realm_id)
    
    if success:
        st.success("Authentication successful! Tokens have been saved.")
        st.info("You can now return to the application.")
        
        # Add a button to return to the main application
        if st.button("Return to Application"):
            # Clear query parameters
            st.query_params.clear()
            # Redirect to the root
            st.rerun()
    else:
        st.error(f"Authentication failed: {message}")
        st.info("Please try again.")
        
        # Add a button to return to the main application
        if st.button("Return to Application"):
            st.query_params.clear()
            st.rerun()
            
else:
    # Display an error if we're at /callback but without the expected parameters
    st.markdown("## QuickBooks Callback Error")
    st.error("Invalid callback request. Missing required parameters.")
    st.info("Please return to the application and try authenticating again.")
    
    # Show the parameters we did receive
    st.write("Received parameters:")
    st.json(dict(st.query_params))
    
    # Add a button to return to the main application
    if st.button("Return to Application"):
        st.query_params.clear()
        st.rerun()