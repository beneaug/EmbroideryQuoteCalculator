"""
QuickBooks OAuth Backend Service

This service handles the OAuth flow for QuickBooks integration, providing a clean API endpoint
for the Streamlit application to use. It handles all the redirect logic and token management,
returning just the necessary data to Streamlit.
"""

import os
import time
import json
import secrets
from flask import Flask, request, redirect, jsonify, session, url_for
from flask_cors import CORS
import requests
from urllib.parse import urlencode

# Create Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configure session
app.secret_key = secrets.token_hex(16)
app.config['SESSION_TYPE'] = 'filesystem'

# OAuth settings
INTUIT_AUTH_ENDPOINT = 'https://appcenter.intuit.com/connect/oauth2'
INTUIT_TOKEN_ENDPOINT = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'

# Placeholder for the database connection
from database import update_setting, update_quickbooks_token, reset_quickbooks_auth, get_quickbooks_settings

# State cache for security verification
oauth_states = {}

@app.route('/api/status')
def api_status():
    """Check if the API is running"""
    return jsonify({
        'status': 'online',
        'version': '1.0',
        'timestamp': time.time()
    })

@app.route('/api/quickbooks/auth')
def quickbooks_auth():
    """Generate a QuickBooks authorization URL"""
    # Get parameters from query
    client_id = request.args.get('client_id')
    client_secret = request.args.get('client_secret')
    redirect_uri = request.args.get('redirect_uri')
    environment = request.args.get('environment', 'sandbox')
    
    # Validate required parameters
    if not client_id or not redirect_uri:
        return jsonify({
            'success': False,
            'error': 'Missing required parameters: client_id or redirect_uri'
        }), 400
    
    # Generate a state parameter for security
    state = secrets.token_hex(16)
    
    # Cache the state and parameters for verification when callback comes
    timestamp = time.time()
    oauth_states[state] = {
        'client_id': client_id, 
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'environment': environment,
        'timestamp': timestamp
    }
    
    # Clean up old states
    clean_old_states()
    
    # Build the OAuth URL with standard parameters
    # Use the redirect URI that's registered in the Intuit Developer Dashboard
    callback_url = "https://b1518f9f-8980-4a58-b73b-3dd813ffa3f5-00-ee9n49p8ejxm.picard.replit.dev/api/quickbooks/callback"
    
    params = {
        'client_id': client_id,
        'response_type': 'code',
        'scope': 'com.intuit.quickbooks.accounting',
        'redirect_uri': callback_url,
        'state': state
    }
    
    auth_url = f"{INTUIT_AUTH_ENDPOINT}?{urlencode(params)}"
    
    return jsonify({
        'success': True,
        'auth_url': auth_url,
        'state': state
    })

@app.route('/api/quickbooks/callback')
# Also support the callback directly at the root path in case the redirect doesn't include /api
@app.route('/quickbooks/callback')  
def quickbooks_callback():
    """Handle the OAuth callback from QuickBooks"""
    # Get the authorization code and state
    code = request.args.get('code')
    state = request.args.get('state')
    realm_id = request.args.get('realmId')
    
    # Validate state to prevent CSRF
    if not state or state not in oauth_states:
        return jsonify({
            'success': False,
            'error': 'Invalid or expired state parameter'
        }), 400
    
    # Get the stored parameters
    params = oauth_states[state]
    client_id = params['client_id']
    client_secret = params['client_secret']
    redirect_uri = params['redirect_uri']
    environment = params['environment']
    
    # Exchange the code for tokens
    token_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': "https://b1518f9f-8980-4a58-b73b-3dd813ffa3f5-00-ee9n49p8ejxm.picard.replit.dev/api/quickbooks/callback"
    }
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Create basic auth header
    auth = (client_id, client_secret)
    
    # Make token request
    try:
        response = requests.post(
            INTUIT_TOKEN_ENDPOINT,
            data=token_data,
            headers=headers,
            auth=auth
        )
        
        # Handle the response
        if response.status_code == 200:
            token_info = response.json()
            
            # Save tokens in the database
            update_setting("quickbooks_settings", "QB_CLIENT_ID", client_id)
            update_setting("quickbooks_settings", "QB_CLIENT_SECRET", client_secret)
            update_setting("quickbooks_settings", "QB_REALM_ID", realm_id)
            update_setting("quickbooks_settings", "QB_ENVIRONMENT", environment)
            
            # Calculate and save token expiration
            expires_at = time.time() + token_info['expires_in']
            
            # Save tokens with expiration
            update_quickbooks_token("QB_ACCESS_TOKEN", token_info['access_token'], expires_at)
            update_quickbooks_token("QB_REFRESH_TOKEN", token_info['refresh_token'])
            
            # Clean up the state
            del oauth_states[state]
            
            # Redirect back to the app with success status
            return redirect(f"{redirect_uri}?success=true&realm_id={realm_id}")
        else:
            # Handle error
            error_info = response.json() if response.text else {'error': 'Unknown error'}
            return redirect(f"{redirect_uri}?success=false&error={error_info.get('error', 'Unknown error')}")
            
    except Exception as e:
        # Handle any exceptions
        return redirect(f"{redirect_uri}?success=false&error={str(e)}")

@app.route('/api/quickbooks/refresh', methods=['POST'])
def quickbooks_refresh():
    """Refresh QuickBooks tokens"""
    # Get parameters from request
    client_id = request.json.get('client_id')
    client_secret = request.json.get('client_secret')
    refresh_token = request.json.get('refresh_token')
    
    # Validate required parameters
    if not client_id or not client_secret or not refresh_token:
        return jsonify({
            'success': False,
            'error': 'Missing required parameters'
        }), 400
    
    # Set up token refresh request
    token_data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    # Create basic auth header
    auth = (client_id, client_secret)
    
    # Make token request
    try:
        response = requests.post(
            INTUIT_TOKEN_ENDPOINT,
            data=token_data,
            headers=headers,
            auth=auth
        )
        
        # Handle the response
        if response.status_code == 200:
            token_info = response.json()
            
            # Calculate and save token expiration
            expires_at = time.time() + token_info['expires_in']
            
            # Save tokens with expiration
            update_quickbooks_token("QB_ACCESS_TOKEN", token_info['access_token'], expires_at)
            update_quickbooks_token("QB_REFRESH_TOKEN", token_info['refresh_token'])
            
            return jsonify({
                'success': True,
                'access_token': token_info['access_token'],
                'refresh_token': token_info['refresh_token'],
                'expires_in': token_info['expires_in'],
                'expires_at': expires_at
            })
        else:
            # Handle error
            error_info = response.json() if response.text else {'error': 'Unknown error'}
            return jsonify({
                'success': False,
                'error': error_info.get('error', 'Unknown error'),
                'error_description': error_info.get('error_description', '')
            }), response.status_code
            
    except Exception as e:
        # Handle any exceptions
        return jsonify({
            'success': False,
            'error': 'Exception',
            'error_description': str(e)
        }), 500

@app.route('/api/quickbooks/reset', methods=['POST'])
def quickbooks_reset():
    """Reset QuickBooks authentication"""
    try:
        success = reset_quickbooks_auth()
        return jsonify({
            'success': success,
            'message': 'QuickBooks authentication has been reset' if success else 'Failed to reset authentication'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def clean_old_states():
    """Clean up old state entries (older than 10 minutes)"""
    current_time = time.time()
    states_to_remove = []
    
    for state, data in oauth_states.items():
        if current_time - data['timestamp'] > 600:  # 10 minutes
            states_to_remove.append(state)
    
    for state in states_to_remove:
        del oauth_states[state]

if __name__ == '__main__':
    # Get the Replit URL from environment or use localhost
    host = '0.0.0.0'  # Listen on all interfaces
    port = 5001  # Different port from Streamlit
    
    # Print information about the server
    print(f"Starting OAuth server on port {port}")
    print(f"Make sure to update your QuickBooks redirect URI in the Developer Dashboard")
    
    # Start the server without debug mode for better stability
    try:
        app.run(host=host, port=port, debug=False)
    except Exception as e:
        print(f"Error starting OAuth server: {str(e)}")
        # Try again with different settings if it fails
        print("Trying alternative configuration...")
        app.run(host=host, port=port, debug=False, use_reloader=False)