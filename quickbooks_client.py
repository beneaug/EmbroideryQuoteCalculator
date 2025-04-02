"""
Simple QuickBooks Integration Client

This is a minimalist implementation of QuickBooks OAuth integration
following the exact API of the Intuit SDK without added complexity.
"""

import os
import json
from datetime import datetime, timedelta

# Intuit SDK imports
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from intuitlib.exceptions import AuthClientError

# QuickBooks SDK import
from quickbooks.client import QuickBooks
from quickbooks.exceptions import AuthorizationException

class QuickBooksClient:
    """Simple QuickBooks client that handles OAuth and API access."""
    
    def __init__(self, db_connection=None):
        """Initialize the QuickBooks client with credentials from environment vars.
        
        Args:
            db_connection: Optional database connection for token storage
        """
        self.client_id = os.environ.get("QB_CLIENT_ID")
        self.client_secret = os.environ.get("QB_CLIENT_SECRET") 
        self.redirect_uri = os.environ.get("QB_REDIRECT_URI")
        self.environment = "sandbox"  # Always use sandbox for this application
        
        # Database connection for token storage
        self.db_connection = db_connection
        
        # Credentials status
        self.has_valid_credentials = bool(self.client_id and self.client_secret and self.redirect_uri)
    
    def get_auth_url(self):
        """Generate a QuickBooks authorization URL.
        
        Returns:
            str: The authorization URL or None if there's an error
        """
        # Check credentials
        if not self.has_valid_credentials:
            print("ERROR: Missing QuickBooks credentials in environment variables")
            return None
            
        try:
            # Create auth client using the official SDK
            auth_client = AuthClient(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                environment=self.environment
            )
            
            # Generate a unique state token for CSRF protection
            # Using the parameter name state_token from the SDK, not state
            import secrets
            state_token = secrets.token_hex(16)
            
            # Get authorization URL with accounting scope
            auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING], state_token=state_token)
            
            # Store the state token in the database if available
            if self.db_connection:
                self._save_state_token(state_token)
                
            return auth_url
            
        except AuthClientError as e:
            print(f"ERROR generating authorization URL: {str(e)}")
            return None
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return None

    def _save_state_token(self, state_token):
        """Save state token to database with timestamp."""
        if not self.db_connection:
            return
            
        try:
            cursor = self.db_connection.cursor()
            expires_at = datetime.now() + timedelta(minutes=10)
            
            # Check if table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quickbooks_states (
                    state_token TEXT PRIMARY KEY,
                    created_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            
            # Insert the state token
            cursor.execute(
                "INSERT INTO quickbooks_states (state_token, created_at, expires_at) VALUES (%s, %s, %s)",
                (state_token, datetime.now(), expires_at)
            )
            
            self.db_connection.commit()
        except Exception as e:
            print(f"Error saving state token: {str(e)}")

    def exchange_code_for_tokens(self, auth_code, realm_id):
        """Exchange authorization code for access tokens.
        
        Args:
            auth_code: Authorization code from callback
            realm_id: QuickBooks company ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.has_valid_credentials:
            print("ERROR: Missing QuickBooks credentials in environment variables")
            return False
            
        try:
            # Create auth client
            auth_client = AuthClient(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                environment=self.environment
            )
            
            # Exchange code for tokens
            auth_client.get_bearer_token(auth_code, realm_id=realm_id)
            
            # Store tokens if we have database connection
            if self.db_connection:
                self._save_tokens(
                    realm_id=realm_id,
                    access_token=auth_client.access_token,
                    refresh_token=auth_client.refresh_token,
                    access_token_expires_at=auth_client.access_token_expires_at,
                    refresh_token_expires_at=auth_client.refresh_token_expires_at
                )
                
            return True
            
        except AuthClientError as e:
            print(f"ERROR exchanging code for tokens: {str(e)}")
            return False
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return False
    
    def _save_tokens(self, realm_id, access_token, refresh_token, 
                    access_token_expires_at, refresh_token_expires_at):
        """Save tokens to database."""
        if not self.db_connection:
            return
            
        try:
            cursor = self.db_connection.cursor()
            
            # Create table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quickbooks_tokens (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP
                )
            """)
            
            # Store each token/value
            tokens = {
                "QB_REALM_ID": realm_id,
                "QB_ACCESS_TOKEN": access_token,
                "QB_REFRESH_TOKEN": refresh_token,
                "QB_ACCESS_TOKEN_EXPIRES_AT": access_token_expires_at,
                "QB_REFRESH_TOKEN_EXPIRES_AT": refresh_token_expires_at
            }
            
            for key, value in tokens.items():
                cursor.execute(
                    """
                    INSERT INTO quickbooks_tokens (key, value, updated_at) 
                    VALUES (%s, %s, %s) 
                    ON CONFLICT (key) DO UPDATE 
                    SET value = %s, updated_at = %s
                    """,
                    (key, str(value), datetime.now(), str(value), datetime.now())
                )
            
            self.db_connection.commit()
        except Exception as e:
            print(f"Error saving tokens: {str(e)}")
    
    def get_api_client(self):
        """Get a QuickBooks API client with current tokens.
        
        Returns:
            tuple: (client, error_message)
        """
        if not self.db_connection:
            return None, "No database connection"
            
        try:
            # Get tokens from database
            tokens = self._get_tokens_from_db()
            
            # Check if we have the necessary tokens
            if not tokens.get("QB_REALM_ID") or not tokens.get("QB_ACCESS_TOKEN"):
                return None, "Missing QuickBooks tokens"
            
            # Check if access token is expired
            if tokens.get("QB_ACCESS_TOKEN_EXPIRES_AT"):
                expires_at = float(tokens["QB_ACCESS_TOKEN_EXPIRES_AT"])
                if datetime.now().timestamp() > expires_at:
                    # Refresh the token
                    refresh_result = self._refresh_token(tokens["QB_REFRESH_TOKEN"], tokens["QB_REALM_ID"])
                    if not refresh_result:
                        return None, "Failed to refresh expired token"
                    
                    # Get updated tokens
                    tokens = self._get_tokens_from_db()
            
            # Create QuickBooks client
            client = QuickBooks(
                client_id=self.client_id,
                client_secret=self.client_secret,
                access_token=tokens["QB_ACCESS_TOKEN"],
                refresh_token=tokens["QB_REFRESH_TOKEN"],
                company_id=tokens["QB_REALM_ID"],
                callback_url=self.redirect_uri,
                environment=self.environment
            )
            
            # Set refresh token handler
            client.refresh_token_handler = self._handle_refresh_token
            
            return client, None
            
        except Exception as e:
            error_msg = f"Error getting QuickBooks client: {str(e)}"
            print(error_msg)
            return None, error_msg
    
    def _get_tokens_from_db(self):
        """Get all QuickBooks tokens from database."""
        tokens = {}
        
        if not self.db_connection:
            return tokens
            
        try:
            cursor = self.db_connection.cursor()
            
            # Check if table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'quickbooks_tokens'
                )
            """)
            
            if not cursor.fetchone()[0]:
                return tokens
            
            # Get all tokens
            cursor.execute("SELECT key, value FROM quickbooks_tokens")
            
            for row in cursor.fetchall():
                tokens[row[0]] = row[1]
                
            return tokens
            
        except Exception as e:
            print(f"Error getting tokens from database: {str(e)}")
            return tokens
    
    def _refresh_token(self, refresh_token, realm_id):
        """Refresh access token using refresh token.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create auth client
            auth_client = AuthClient(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                environment=self.environment
            )
            
            # Set the refresh token
            auth_client.refresh_token = refresh_token
            
            # Refresh the token
            auth_client.refresh(refresh_token=refresh_token)
            
            # Save the new tokens
            self._save_tokens(
                realm_id=realm_id,
                access_token=auth_client.access_token,
                refresh_token=auth_client.refresh_token,
                access_token_expires_at=auth_client.access_token_expires_at,
                refresh_token_expires_at=auth_client.refresh_token_expires_at
            )
            
            return True
            
        except Exception as e:
            print(f"Error refreshing token: {str(e)}")
            return False
    
    def _handle_refresh_token(self, refresh_token):
        """Callback for refreshing token in QuickBooks client.
        
        This is called automatically by the QuickBooks client when a token expires.
        """
        try:
            # Get realm ID from database
            tokens = self._get_tokens_from_db()
            realm_id = tokens.get("QB_REALM_ID")
            
            if not realm_id:
                print("ERROR: Missing realm ID for refresh token")
                return None
                
            # Refresh the token
            self._refresh_token(refresh_token, realm_id)
            
            # Return the new tokens
            tokens = self._get_tokens_from_db()
            return tokens.get("QB_ACCESS_TOKEN")
            
        except Exception as e:
            print(f"Error in refresh token handler: {str(e)}")
            return None
    
    def is_connected(self):
        """Check if we have valid QuickBooks connection.
        
        Returns:
            bool: True if connected, False otherwise
        """
        # Get tokens from database
        tokens = self._get_tokens_from_db()
        
        # Check for required tokens
        if not tokens.get("QB_REALM_ID") or not tokens.get("QB_ACCESS_TOKEN"):
            return False
            
        # Try a test API call
        client, error = self.get_api_client()
        if not client:
            return False
            
        try:
            # Test API connection with a simple call
            from quickbooks.objects.company import Company
            company_info = Company.all(qb=client)
            return bool(company_info)
        except Exception:
            return False
    
    def reset_connection(self):
        """Reset QuickBooks connection by removing all tokens.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.db_connection:
            return False
            
        try:
            cursor = self.db_connection.cursor()
            
            # Check if table exists and delete all tokens
            cursor.execute("""
                DELETE FROM quickbooks_tokens 
                WHERE key IN ('QB_REALM_ID', 'QB_ACCESS_TOKEN', 'QB_REFRESH_TOKEN',
                             'QB_ACCESS_TOKEN_EXPIRES_AT', 'QB_REFRESH_TOKEN_EXPIRES_AT')
            """)
            
            # Clean up state tokens
            cursor.execute("DELETE FROM quickbooks_states")
            
            self.db_connection.commit()
            return True
            
        except Exception as e:
            print(f"Error resetting QuickBooks connection: {str(e)}")
            return False