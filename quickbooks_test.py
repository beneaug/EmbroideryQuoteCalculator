"""
Simple test script for the QuickBooks integration.

This script tests the basic functionality of the QuickBooks client.
"""

import os
import psycopg2
from quickbooks_client import QuickBooksClient

def get_db_connection():
    """Get database connection from environment variables."""
    try:
        conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
        return conn
    except Exception as e:
        print(f"Error connecting to database: {str(e)}")
        return None

def test_auth_url_generation():
    """Test generating an authorization URL."""
    print("\n--- Testing Authorization URL Generation ---")
    
    # Get database connection
    conn = get_db_connection()
    
    # Create QuickBooks client
    qb_client = QuickBooksClient(conn)
    
    # Check credentials
    if not qb_client.has_valid_credentials:
        print("ERROR: Missing QuickBooks credentials in environment variables")
        print(f"Client ID: {qb_client.client_id and 'Set' or 'Not set'}")
        print(f"Client Secret: {qb_client.client_secret and 'Set' or 'Not set'}")
        print(f"Redirect URI: {qb_client.redirect_uri or 'Not set'}")
        return
    
    # Generate authorization URL
    auth_url = qb_client.get_auth_url()
    
    if auth_url:
        print(f"✅ Successfully generated authorization URL")
        print(f"URL: {auth_url}")
    else:
        print("❌ Failed to generate authorization URL")

def test_connection_status():
    """Test checking connection status."""
    print("\n--- Testing Connection Status ---")
    
    # Get database connection
    conn = get_db_connection()
    
    # Create QuickBooks client
    qb_client = QuickBooksClient(conn)
    
    # Check connection status
    is_connected = qb_client.is_connected()
    
    if is_connected:
        print("✅ QuickBooks is connected")
    else:
        print("❌ QuickBooks is not connected")
    
    # Get tokens
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT key, value FROM quickbooks_tokens")
            tokens = cursor.fetchall()
            
            if tokens:
                print("\nStored tokens:")
                for key, value in tokens:
                    if key == "QB_ACCESS_TOKEN" or key == "QB_REFRESH_TOKEN":
                        masked_value = value[:10] + "..." if value else "None"
                        print(f"  {key}: {masked_value}")
                    else:
                        print(f"  {key}: {value}")
            else:
                print("\nNo tokens stored in the database")
                
        except Exception as e:
            print(f"Error retrieving tokens: {str(e)}")

def main():
    """Run all tests."""
    print("=== QuickBooks Integration Test ===")
    
    # Print environment info
    print("\nEnvironment variables:")
    client_id = os.environ.get("QB_CLIENT_ID")
    client_secret = os.environ.get("QB_CLIENT_SECRET")
    redirect_uri = os.environ.get("QB_REDIRECT_URI")
    
    print(f"QB_CLIENT_ID: {client_id and (client_id[:5] + '...') or 'Not set'}")
    print(f"QB_CLIENT_SECRET: {client_secret and 'Set' or 'Not set'}")
    print(f"QB_REDIRECT_URI: {redirect_uri or 'Not set'}")
    
    # Run tests
    test_auth_url_generation()
    test_connection_status()

if __name__ == "__main__":
    main()