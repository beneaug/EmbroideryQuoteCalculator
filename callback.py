"""
QuickBooks OAuth Callback Handler

This file handles OAuth 2.0 callbacks from Intuit/QuickBooks.
It directly exchanges the authorization code for tokens using REST API
and saves them to the database.
"""

import os
import streamlit as st
import requests
import time
import json
import logging
import traceback
from urllib.parse import urlencode

# Configure detailed logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - QB_CALLBACK: %(message)s')
logger = logging.getLogger('qb_callback')

# Add a page title
st.set_page_config(page_title="QuickBooks Authentication", layout="centered")

# Get the current query parameters
params = st.query_params

# Get Replit domain for this instance
replit_domain = os.environ.get("REPLIT_DOMAINS", "")
if replit_domain:
    replit_domain = replit_domain.split(',')[0].strip()

# Function to directly exchange authorization code for tokens using REST API
def direct_token_exchange(code, realm_id):
    """
    Exchange authorization code for tokens using direct API call
    without relying on the intuitlib package
    """
    try:
        # Import database module for token storage
        import database
        
        # Get QuickBooks settings from database
        qb_settings = database.get_quickbooks_settings()
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')
        
        # Construct redirect URI
        redirect_uri = f"https://{replit_domain}/callback" if replit_domain else "https://embroideryquotecalculator.juliewoodland.repl.co/callback"
        
        # Log the settings we're using
        logger.info(f"Using client_id: {client_id[:5]}...")
        logger.info(f"Realm ID: {realm_id}")
        logger.info(f"Redirect URI: {redirect_uri}")
        logger.info(f"Environment: {environment}")
        
        # Determine token endpoint based on environment
        token_endpoint = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        if environment == "sandbox":
            logger.info("Using sandbox environment for token exchange")
        
        # Prepare request parameters
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri
        }
        
        # Add authorization header
        import base64
        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Log what we're about to do
        logger.info(f"Making token exchange request to: {token_endpoint}")
        
        # Make the request to exchange code for tokens
        response = requests.post(token_endpoint, 
                                data=data, 
                                headers=headers)
        
        # Check for successful response
        if response.status_code == 200:
            # Parse the response
            token_data = response.json()
            logger.info("Token exchange successful!")
            
            # Extract tokens
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)  # Default to 1 hour
            
            # Calculate expiry time
            token_expiry = time.time() + expires_in
            
            # Log token details (partially masked)
            if access_token:
                logger.info(f"Access token received (first 5 chars): {access_token[:5]}...")
                logger.info(f"Token expires in: {expires_in} seconds")
            if refresh_token:
                logger.info(f"Refresh token received (first 5 chars): {refresh_token[:5]}...")
            
            # Save tokens to database
            logger.info("Saving tokens to database...")
            
            # First save using update_setting to ensure records exist
            database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
            database.update_setting("quickbooks_settings", "QB_ACCESS_TOKEN", access_token)
            database.update_setting("quickbooks_settings", "QB_REFRESH_TOKEN", refresh_token)
            
            # Save with direct SQL to ensure proper storage
            conn = None
            try:
                conn = database.get_connection()
                if conn:
                    from sqlalchemy import text
                    
                    # Save access token with expiry
                    conn.execute(text("""
                        UPDATE quickbooks_settings 
                        SET value = :value, token_expires_at = :expires, updated_at = CURRENT_TIMESTAMP 
                        WHERE name = 'QB_ACCESS_TOKEN'
                    """), {"value": access_token, "expires": token_expiry})
                    
                    # Save refresh token
                    conn.execute(text("""
                        UPDATE quickbooks_settings 
                        SET value = :value, updated_at = CURRENT_TIMESTAMP 
                        WHERE name = 'QB_REFRESH_TOKEN'
                    """), {"value": refresh_token})
                    
                    # Save realm ID
                    conn.execute(text("""
                        UPDATE quickbooks_settings 
                        SET value = :value, updated_at = CURRENT_TIMESTAMP 
                        WHERE name = 'QB_REALM_ID'
                    """), {"value": realm_id})
                    
                    # Explicitly commit
                    conn.commit()
                    logger.info("Tokens saved to database with direct SQL")
            except Exception as db_err:
                logger.error(f"Database error: {str(db_err)}")
                logger.error(traceback.format_exc())
                if conn:
                    conn.rollback()
                return False, f"Database error: {str(db_err)}"
            finally:
                if conn:
                    conn.close()
            
            # Verify tokens were saved
            qb_settings = database.get_quickbooks_settings()
            access_token_saved = qb_settings.get('QB_ACCESS_TOKEN', {}).get('value', '')
            refresh_token_saved = qb_settings.get('QB_REFRESH_TOKEN', {}).get('value', '')
            
            logger.info(f"Verification - Access token saved: {bool(access_token_saved)}")
            logger.info(f"Verification - Refresh token saved: {bool(refresh_token_saved)}")
            
            if access_token_saved and refresh_token_saved:
                return True, "Authentication successful"
            else:
                return False, "Token verification failed - tokens weren't saved properly"
        else:
            # Log error response
            error_msg = f"Token exchange failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except Exception as e:
        # Log and return any exceptions
        error_msg = f"Unexpected error in token exchange: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return False, error_msg

# Main callback handler logic
if 'code' in params and 'realmId' in params:
    # Extract parameters from the callback URL
    code = params.get('code')
    realm_id = params.get('realmId')
    state = params.get('state', '')
    
    # Log the received parameters
    logger.info(f"Received OAuth callback with code {code[:5]}... and realm {realm_id}")
    
    # Display a message to the user
    st.title("QuickBooks Authentication")
    st.info("Processing your QuickBooks authorization...")
    
    # Show basic information (partially masked for security)
    st.write(f"Authorization code received: {code[:5]}...{code[-5:] if len(code) > 10 else '...'}")
    st.write(f"Company ID: {realm_id}")
    
    # Exchange authorization code for tokens
    with st.spinner("Exchanging authorization code for tokens..."):
        success, message = direct_token_exchange(code, realm_id)
    
    if success:
        # Show success message
        st.success("✅ Authentication successful!")
        st.balloons()
        st.info("Your QuickBooks connection has been established. You can now return to the main application.")
        
        # Add debug information in an expander
        with st.expander("Technical Details"):
            st.write("The authorization code was successfully exchanged for access and refresh tokens.")
            st.write("These tokens have been securely saved to the database.")
            st.write("Your application can now communicate with the QuickBooks API.")
        
        # Button to return to main app
        if st.button("Return to Application", type="primary"):
            st.query_params.clear()
            st.rerun()
    else:
        # Show error message
        st.error(f"❌ Authentication failed: {message}")
        
        # Provide more information in an expander
        with st.expander("Error Details and Troubleshooting"):
            st.write("""
            ### Common reasons for token exchange failures:
            
            1. **Authorization code already used or expired**
               - Each code can only be used once
               - Codes expire after 10 minutes
               
            2. **Redirect URI mismatch**
               - The URI must exactly match what's registered in your QuickBooks app
               
            3. **API limits or connectivity issues**
               - Temporary QuickBooks API issues
               - Network connectivity problems
            """)
            
            # Show specific error details
            st.write(f"**Error message:** {message}")
        
        # Button to try again
        if st.button("Try Again", type="primary"):
            st.query_params.clear()
            st.rerun()
            
else:
    # Handle case where required parameters are missing
    st.title("QuickBooks Authorization")
    st.error("Invalid callback request - Missing required parameters")
    
    # Show what parameters we received
    st.write("Parameters received:")
    st.json(dict(params))
    
    # Provide help info
    st.info("""
    This page is part of the QuickBooks authorization process.
    You should reach this page after authorizing access to your QuickBooks account.
    
    If you're seeing this message, the authorization process may have been interrupted.
    """)
    
    # Button to return to main application
    if st.button("Return to Application", type="primary"):
        st.query_params.clear()
        st.rerun()