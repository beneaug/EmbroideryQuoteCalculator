"""
QuickBooks OAuth Callback Server

This lightweight Flask server handles OAuth 2.0 callbacks from Intuit/QuickBooks.
It's designed to:
1. Process the callback once and only once
2. Exchange the authorization code for tokens
3. Store the tokens in the database
4. Redirect the user back to the main application

This approach isolates the token exchange process from Streamlit's re-execution model.
"""

import os
import time
import logging
from flask import Flask, request, redirect
from intuitlib.client import AuthClient
from intuitlib.exceptions import AuthClientError

# Import database functions to store tokens
import database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('qb_oauth_server')

# Initialize Flask app
app = Flask(__name__)

@app.route('/callback')
def oauth_callback():
    """
    Handle the OAuth 2.0 callback from Intuit/QuickBooks.
    This endpoint receives the authorization code and exchanges it for tokens.
    """
    # Check for error response
    if 'error' in request.args:
        error = request.args.get('error')
        error_description = request.args.get('error_description', 'Unknown error')
        logger.error(f"QuickBooks OAuth Error: {error} - {error_description}")
        return redirect(f"/?error={error}&error_description={error_description}")

    # Check for authorization code and realm ID
    if 'code' not in request.args or 'realmId' not in request.args:
        logger.error("Invalid callback: Missing code or realmId")
        return redirect("/?error=invalid_callback&error_description=Missing required parameters")

    # Get authorization code and realm ID
    auth_code = request.args.get('code')
    realm_id = request.args.get('realmId')
    
    # Optional: Validate state parameter if you're using it
    state = request.args.get('state')
    if state:
        logger.info(f"Received state parameter: {state}")
    
    # Log the callback 
    code_preview = auth_code[:5] + "..." if auth_code else "None"
    logger.info(f"Received QuickBooks callback with code {code_preview} and realm {realm_id}")
    
    try:
        # Get QuickBooks settings from database
        qb_settings = database.get_quickbooks_settings()
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        
        # Get redirect URI from environment or use the one from database
        replit_domain = os.environ.get("REPLIT_DOMAINS", "").split(',')[0].strip()
        if replit_domain:
            redirect_uri = f"https://{replit_domain}/callback"
        else:
            redirect_uri = qb_settings.get('QB_REDIRECT_URI', {}).get('value', '')
        
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')
        
        # Initialize the auth client
        auth_client = AuthClient(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            environment=environment
        )

        # Exchange the authorization code for tokens
        logger.info(f"Exchanging authorization code for tokens...")
        auth_client.get_bearer_token(auth_code, realm_id)
        
        # Log token details (without exposing sensitive info)
        logger.info(f"Token exchange successful!")
        logger.info(f"Access token received (first 5 chars): {auth_client.access_token[:5]}...")
        logger.info(f"Token expires in: {auth_client.expires_in} seconds")
        
        # Save the tokens in the database
        logger.info(f"Saving tokens to database...")
        database.update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
        token_expiry = time.time() + auth_client.expires_in
        database.update_quickbooks_token("QB_ACCESS_TOKEN", auth_client.access_token, token_expiry)
        database.update_quickbooks_token("QB_REFRESH_TOKEN", auth_client.refresh_token)
        
        # Redirect back to the main app with success message
        logger.info(f"Redirecting user back to main application...")
        return redirect("/?qb_auth_success=true")
        
    except AuthClientError as e:
        # Handle auth-specific errors
        logger.error(f"QuickBooks Authentication Error: {str(e)}")
        error_message = "invalid_grant" if "invalid_grant" in str(e) else "auth_error"
        return redirect(f"/?error={error_message}&error_description={str(e)}")
        
    except Exception as e:
        # Handle any other exceptions
        logger.error(f"Unexpected error during token exchange: {str(e)}", exc_info=True)
        return redirect(f"/?error=server_error&error_description={str(e)}")

# For local development only
if __name__ == '__main__':
    # For development only - Streamlit runs its own server in production
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)