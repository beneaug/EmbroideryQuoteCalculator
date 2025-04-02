"""
Standalone QuickBooks integration app with Streamlit.

This app handles the QuickBooks OAuth flow and provides a simple UI
for connecting to QuickBooks and testing the integration.
"""

import os
import streamlit as st
import psycopg2
from urllib.parse import parse_qs, urlparse

# Import our custom QuickBooks client
from quickbooks_client import QuickBooksClient

# Page configuration
st.set_page_config(
    page_title="QuickBooks Integration",
    page_icon="📊",
    layout="wide"
)

# Initialize session state for QuickBooks client
if 'qb_client' not in st.session_state:
    st.session_state.qb_client = None

# App title
st.title("QuickBooks Integration")
st.write("Simple QuickBooks OAuth integration example")

def get_db_connection():
    """Get database connection from environment variables."""
    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
        return conn
    except Exception as e:
        st.error(f"Error connecting to database: {str(e)}")
        return None

def initialize_qb_client():
    """Initialize or get the QuickBooks client."""
    if st.session_state.qb_client is None:
        # Get database connection
        conn = get_db_connection()
        
        # Create QuickBooks client
        st.session_state.qb_client = QuickBooksClient(conn)
    
    return st.session_state.qb_client

def display_connection_status():
    """Display QuickBooks connection status."""
    qb_client = initialize_qb_client()
    
    # Check credentials
    if not qb_client.has_valid_credentials:
        st.error("⚠️ Missing QuickBooks API credentials")
        
        # Show which credentials are missing
        if not qb_client.client_id:
            st.error("Missing QB_CLIENT_ID in environment variables")
        if not qb_client.client_secret:
            st.error("Missing QB_CLIENT_SECRET in environment variables")
        if not qb_client.redirect_uri:
            st.error("Missing QB_REDIRECT_URI in environment variables")
        
        st.info("Please set these credentials in the Replit Secrets (Tools > Secrets)")
        return False
    
    # Check connection status
    is_connected = qb_client.is_connected()
    
    if is_connected:
        st.success("✅ Connected to QuickBooks")
        
        # Display connection info
        tokens = qb_client._get_tokens_from_db()
        if tokens:
            st.write("**Connection Details:**")
            if "QB_REALM_ID" in tokens:
                st.write(f"Company ID: {tokens['QB_REALM_ID']}")
            
            # Display access token expiration if available
            if "QB_ACCESS_TOKEN_EXPIRES_AT" in tokens:
                import time
                from datetime import datetime
                
                try:
                    expires_at = float(tokens["QB_ACCESS_TOKEN_EXPIRES_AT"])
                    expires_at_dt = datetime.fromtimestamp(expires_at)
                    now = datetime.now()
                    
                    if expires_at_dt > now:
                        minutes_left = int((expires_at_dt - now).total_seconds() / 60)
                        st.info(f"Access token expires in {minutes_left} minutes")
                    else:
                        st.warning("Access token expired - will be refreshed automatically on next API call")
                except Exception as e:
                    st.warning(f"Invalid token expiration format: {str(e)}")
        
        return True
    else:
        st.warning("⚠️ Not connected to QuickBooks")
        return False

def handle_callback():
    """Handle OAuth callback parameters."""
    # Get current URL parameters
    query_params = st.experimental_get_query_params()
    
    # Check for code and realmId parameters
    if "code" in query_params and "realmId" in query_params:
        st.info("Processing QuickBooks authorization...")
        
        code = query_params["code"][0]
        realm_id = query_params["realmId"][0]
        
        # Create client and exchange code for tokens
        qb_client = initialize_qb_client()
        success = qb_client.exchange_code_for_tokens(code, realm_id)
        
        # Clear the URL parameters
        st.experimental_set_query_params()
        
        if success:
            st.success("✅ Successfully connected to QuickBooks!")
            st.balloons()
        else:
            st.error("❌ Failed to connect to QuickBooks. Please try again.")
        
        st.info("Please wait while the page refreshes...")
        st.rerun()

def main():
    """Main application logic."""
    # Handle callback
    handle_callback()
    
    # Main layout
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Connection status
        st.subheader("Connection Status")
        is_connected = display_connection_status()
        
        # Connection actions
        st.subheader("Connection Actions")
        
        # Only show connect button if not connected
        if not is_connected:
            qb_client = initialize_qb_client()
            
            if qb_client.has_valid_credentials:
                if st.button("Connect to QuickBooks", type="primary"):
                    auth_url = qb_client.get_auth_url()
                    
                    if auth_url:
                        st.success("✅ Authorization URL generated")
                        st.info("You will be redirected to QuickBooks for authorization")
                        
                        # Show the authorize button
                        st.markdown(f"""
                            <a href="{auth_url}" target="_self" style="
                                display: inline-block;
                                background-color: #2ea44f;
                                color: white;
                                padding: 12px 24px;
                                text-decoration: none;
                                font-weight: bold;
                                border-radius: 6px;
                                margin-top: 10px;
                            ">
                                Authorize with QuickBooks
                            </a>
                        """, unsafe_allow_html=True)
                        
                        # Also add JavaScript redirect
                        st.markdown(f"""
                            <script>
                                setTimeout(function() {{
                                    window.top.location.href = "{auth_url}";
                                }}, 2000);
                            </script>
                        """, unsafe_allow_html=True)
                    else:
                        st.error("❌ Failed to generate authorization URL")
        
        # Always show reset button
        qb_client = initialize_qb_client()
        if st.button("Reset QuickBooks Connection", type="secondary"):
            success = qb_client.reset_connection()
            
            if success:
                st.success("✅ QuickBooks connection has been reset")
                st.info("Refreshing page...")
                st.rerun()
            else:
                st.error("❌ Failed to reset QuickBooks connection")
    
    with col2:
        # Help and information
        st.subheader("QuickBooks Setup Guide")
        
        st.markdown("""
        ### Required Credentials
        
        1. **Client ID** - from Intuit Developer Dashboard
        2. **Client Secret** - from Intuit Developer Dashboard
        3. **Redirect URI** - your app's callback URL
        
        ### Common Issues
        
        - **Redirect URI Mismatch**: The redirect URI must match EXACTLY
        - **Authorization Expiration**: Codes expire after 10 minutes
        - **One-time Use**: Authorization codes can only be used once
        
        ### Set Credentials in Replit
        
        1. Go to **Tools > Secrets**
        2. Add the following secrets:
           - `QB_CLIENT_ID`
           - `QB_CLIENT_SECRET`
           - `QB_REDIRECT_URI`
        """)

if __name__ == "__main__":
    main()