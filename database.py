import os
import time
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
import streamlit as st

# Get database connection string from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")

# Create database engine with connection pooling and retry settings
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Check if connection is alive
    pool_recycle=3600,   # Recycle connections after 1 hour
    connect_args={
        'connect_timeout': 10,  # Connection timeout in seconds
        'keepalives': 1,        # Enable keepalives
        'keepalives_idle': 30,  # Keepalive idle time
        'keepalives_interval': 10, # Keepalive interval
        'keepalives_count': 5   # Keepalive count
    }
)

def get_connection():
    """Get a database connection with retry mechanism"""
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            return engine.connect()
        except OperationalError as e:
            if "SSL connection has been closed unexpectedly" in str(e) and attempt < max_retries - 1:
                # Log the error and retry
                st.warning(f"Database connection dropped. Retrying ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
                # Increase delay for next retry
                retry_delay *= 2
            else:
                # Last attempt failed or different error, re-raise with a message
                st.error(f"Failed to connect to database after {max_retries} attempts: {str(e)}")
                raise

def get_material_settings():
    """Get all material settings from the database"""
    try:
        with get_connection() as conn:
            query = "SELECT name, value, description FROM material_settings ORDER BY id"
            result = conn.execute(text(query))
            settings = {row[0]: {"value": row[1], "description": row[2]} for row in result}
            return settings
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        # Return default values as fallback
        return {
            "POLYNEON_5500YD_PRICE": {"value": 9.69, "description": "Price for 5500 yard Polyneon thread spool"},
            "POLYNEON_1100YD_PRICE": {"value": 3.19, "description": "Price for 1100 yard Polyneon thread spool"},
            "BOBBIN_144_PRICE": {"value": 35.85, "description": "Price for a pack of 144 bobbins"},
            "BOBBIN_YARDS": {"value": 124, "description": "Yards of thread per bobbin"},
            "FOAM_SHEET_PRICE": {"value": 2.45, "description": "Price per foam sheet"},
            "STABILIZER_PRICE_PER_PIECE": {"value": 0.18, "description": "Price per piece of stabilizer backing"}
        }

def get_machine_settings():
    """Get all machine settings from the database"""
    try:
        with get_connection() as conn:
            query = "SELECT name, value, description FROM machine_settings ORDER BY id"
            result = conn.execute(text(query))
            settings = {row[0]: {"value": row[1], "description": row[2]} for row in result}
            return settings
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        # Return default values as fallback
        return {
            "DEFAULT_STITCH_SPEED_40WT": {"value": 750, "description": "Default stitch speed for 40wt thread (rpm)"},
            "DEFAULT_STITCH_SPEED_60WT": {"value": 400, "description": "Default stitch speed for 60wt thread (rpm)"},
            "DEFAULT_MAX_HEADS": {"value": 15, "description": "Default maximum machine heads"},
            "DEFAULT_COLOREEL_MAX_HEADS": {"value": 2, "description": "Default maximum machine heads when using Coloreel"},
            "HOOPING_TIME_DEFAULT": {"value": 50, "description": "Default time to hoop an item (seconds)"},
            "DEFAULT_PRODUCTIVITY_RATE": {"value": 1.0, "description": "Default productivity rate (1.0 = 100% efficiency)"},
            "DEFAULT_COMPLEX_PRODUCTIVITY_RATE": {"value": 0.8, "description": "Productivity rate for complex production (0.8 = 80% efficiency)"},
            "DEFAULT_COLOREEL_PRODUCTIVITY_RATE": {"value": 0.75, "description": "Productivity rate when using Coloreel (0.75 = 75% efficiency)"},
            "DEFAULT_DIGITIZING_FEE": {"value": 25.0, "description": "Default digitizing fee for complex designs ($)"}
        }

def get_labor_settings():
    """Get all labor settings from the database"""
    try:
        with get_connection() as conn:
            query = "SELECT name, value, description FROM labor_settings ORDER BY id"
            result = conn.execute(text(query))
            settings = {row[0]: {"value": row[1], "description": row[2]} for row in result}
            return settings
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        # Return default values as fallback
        return {
            "HOURLY_LABOR_RATE": {"value": 25, "description": "Hourly labor rate ($/hour)"}
        }

def get_labor_workers():
    """Get all labor workers from the database"""
    try:
        with get_connection() as conn:
            query = "SELECT id, name, hourly_rate, is_active FROM labor_workers ORDER BY name"
            result = conn.execute(text(query))
            workers = [dict(zip(["id", "name", "hourly_rate", "is_active"], row)) for row in result]
            return workers
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        return []

def add_labor_worker(name, hourly_rate, is_active=True):
    """Add a new labor worker to the database"""
    try:
        with get_connection() as conn:
            query = """
            INSERT INTO labor_workers (name, hourly_rate, is_active) 
            VALUES (:name, :hourly_rate, :is_active)
            RETURNING id
            """
            result = conn.execute(text(query), {
                "name": name, 
                "hourly_rate": hourly_rate, 
                "is_active": is_active
            })
            worker_id = result.fetchone()[0]
            conn.commit()
            return worker_id
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        return None

def update_labor_worker(worker_id, name=None, hourly_rate=None, is_active=None):
    """Update a labor worker in the database"""
    try:
        with get_connection() as conn:
            # Build the query dynamically based on which fields are provided
            update_parts = []
            params = {"id": worker_id}
            
            if name is not None:
                update_parts.append("name = :name")
                params["name"] = name
            
            if hourly_rate is not None:
                update_parts.append("hourly_rate = :hourly_rate")
                params["hourly_rate"] = hourly_rate
            
            if is_active is not None:
                update_parts.append("is_active = :is_active")
                params["is_active"] = is_active
            
            # If no fields were provided, return
            if not update_parts:
                return False
            
            # Add the updated_at timestamp
            update_parts.append("updated_at = CURRENT_TIMESTAMP")
            
            # Construct the final query
            query = f"""
            UPDATE labor_workers 
            SET {", ".join(update_parts)}
            WHERE id = :id
            """
            
            conn.execute(text(query), params)
            conn.commit()
            return True
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        return False

def delete_labor_worker(worker_id):
    """Delete a labor worker from the database"""
    try:
        with get_connection() as conn:
            query = "DELETE FROM labor_workers WHERE id = :id"
            conn.execute(text(query), {"id": worker_id})
            conn.commit()
            return True
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        return False

def update_setting(table, name, value):
    """Update a setting in the database"""
    try:
        with get_connection() as conn:
            query = f"""
            UPDATE {table} 
            SET value = :value, 
                updated_at = CURRENT_TIMESTAMP 
            WHERE name = :name
            """
            conn.execute(text(query), {"value": value, "name": name})
            conn.commit()
            return True
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        return False

def save_quote(quote_data):
    """Save a quote to the database with retry mechanism"""
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            with get_connection() as conn:
                query = """
                INSERT INTO quotes 
                (job_name, customer_name, stitch_count, color_count, quantity, 
                 width_inches, height_inches, total_cost, price_per_piece)
                VALUES 
                (:job_name, :customer_name, :stitch_count, :color_count, :quantity,
                 :width_inches, :height_inches, :total_cost, :price_per_piece)
                RETURNING id
                """
                result = conn.execute(text(query), quote_data)
                quote_id = result.fetchone()[0]
                conn.commit()
                return quote_id
        except OperationalError as e:
            if "SSL connection has been closed unexpectedly" in str(e) and attempt < max_retries - 1:
                # Log the error and retry
                st.warning(f"Database connection dropped while saving quote. Retrying ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
                # Increase delay for next retry
                retry_delay *= 2
            else:
                # Last attempt failed or different error
                st.error(f"Database error: {str(e)}")
                return None
        except SQLAlchemyError as e:
            st.error(f"Database error: {str(e)}")
            return None

def get_recent_quotes(limit=10):
    """Get recent quotes from the database"""
    try:
        with get_connection() as conn:
            query = f"""
            SELECT id, job_name, customer_name, stitch_count, quantity, 
                   total_cost, price_per_piece, created_at
            FROM quotes
            ORDER BY created_at DESC
            LIMIT {limit}
            """
            result = conn.execute(text(query))
            quotes = [dict(zip(result.keys(), row)) for row in result]
            return quotes
    except SQLAlchemyError as e:
        st.error(f"Database error: {str(e)}")
        return []

def create_quickbooks_table_if_missing():
    """Creates the QuickBooks settings table if it doesn't exist"""
    try:
        with get_connection() as conn:
            # Check if table exists
            check_query = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'quickbooks_settings'
            );
            """
            exists = conn.execute(text(check_query)).scalar()
            
            if not exists:
                print("Creating QuickBooks settings table...")
                
                # Create the table
                create_query = """
                CREATE TABLE quickbooks_settings (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    value TEXT,
                    description TEXT,
                    token_expires_at FLOAT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
                conn.execute(text(create_query))
                
                # Initialize with empty settings
                init_query = """
                INSERT INTO quickbooks_settings 
                (name, value, description) VALUES 
                ('QB_ACCESS_TOKEN', '', 'QuickBooks API Access Token'),
                ('QB_REFRESH_TOKEN', '', 'QuickBooks API Refresh Token'),
                ('QB_REALM_ID', '', 'QuickBooks Company/Realm ID'),
                ('QB_CLIENT_ID', '', 'QuickBooks API Client ID'),
                ('QB_CLIENT_SECRET', '', 'QuickBooks API Client Secret'),
                ('QB_ENVIRONMENT', 'sandbox', 'QuickBooks Environment (sandbox or production)')
                ON CONFLICT (name) DO NOTHING;
                """
                conn.execute(text(init_query))
                conn.commit()
                print("QuickBooks settings table created and initialized")
                return True
            
            return True
    except SQLAlchemyError as e:
        error_msg = f"Error creating QuickBooks table: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        return False

def get_quickbooks_settings():
    """Get all QuickBooks integration settings from the database"""
    try:
        # Ensure the table exists
        table_created = create_quickbooks_table_if_missing()
        if not table_created:
            print("Failed to create/verify QuickBooks settings table")
            return {}
        
        with get_connection() as conn:
            query = """
            SELECT name, value, description, token_expires_at 
            FROM quickbooks_settings 
            ORDER BY id
            """
            result = conn.execute(text(query))
            
            # Convert to dictionary with settings as keys
            settings = {}
            for row in result:
                settings[row[0]] = {
                    'value': row[1],
                    'description': row[2],
                    'expires_at': row[3]
                }
            
            # Debug output
            for name, setting in settings.items():
                value_preview = ""
                if setting['value']:
                    if len(setting['value']) > 10 and name.endswith("_TOKEN"):
                        value_preview = f"{setting['value'][:5]}...{setting['value'][-5:]}"
                    else:
                        value_preview = setting['value']
                print(f"Setting {name}: {value_preview}")
            
            return settings
    except SQLAlchemyError as e:
        error_msg = f"Database error getting QuickBooks settings: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        # Return empty dictionary as fallback
        return {}
        
def update_quickbooks_token(token_type, token_value, token_expires_at=None):
    """Update a QuickBooks token in the database with enhanced error handling"""
    # Print debug information (sanitized)
    value_preview = f"{token_value[:10]}..." if token_value and len(token_value) > 10 else "None"
    print(f"Updating QuickBooks token: {token_type}, Value: {value_preview}, Expires: {token_expires_at}")
    
    try:
        with get_connection() as conn:
            # First check if the row exists
            check_query = "SELECT COUNT(*) FROM quickbooks_settings WHERE name = :name"
            result = conn.execute(text(check_query), {"name": token_type})
            count = result.scalar()
            
            if count == 0:
                print(f"No record found for {token_type}, will insert instead of update")
                # Insert a new row if it doesn't exist
                insert_query = """
                INSERT INTO quickbooks_settings 
                (name, value, description, token_expires_at, created_at, updated_at)
                VALUES 
                (:name, :value, :description, :token_expires_at, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
                
                description = f"QuickBooks API {token_type.replace('QB_', '')}"
                
                params = {
                    "name": token_type,
                    "value": token_value,
                    "description": description,
                    "token_expires_at": token_expires_at
                }
                
                conn.execute(text(insert_query), params)
            else:
                # Update existing row
                if token_expires_at:
                    query = """
                    UPDATE quickbooks_settings 
                    SET value = :value, 
                        token_expires_at = :token_expires_at,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE name = :name
                    """
                    print(f"Executing update with expiration: {token_type}")
                    conn.execute(text(query), {
                        "value": token_value,
                        "name": token_type,
                        "token_expires_at": token_expires_at
                    })
                else:
                    query = """
                    UPDATE quickbooks_settings 
                    SET value = :value, 
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE name = :name
                    """
                    print(f"Executing update without expiration: {token_type}")
                    conn.execute(text(query), {
                        "value": token_value,
                        "name": token_type
                    })
            
            # Explicitly commit the transaction
            conn.commit()
            print(f"Token {token_type} saved successfully")
            
            # Verify the token was actually saved
            verify_query = "SELECT value FROM quickbooks_settings WHERE name = :name"
            verify_result = conn.execute(text(verify_query), {"name": token_type})
            saved_value = verify_result.scalar()
            saved_preview = f"{saved_value[:10]}..." if saved_value and len(saved_value) > 10 else "None"
            print(f"Verification - {token_type} value in database: {saved_preview}")
            
            return True
    except SQLAlchemyError as e:
        error_msg = f"Database error saving {token_type}: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        return False

def reset_quickbooks_auth():
    """Reset QuickBooks authentication tokens"""
    try:
        print("Resetting QuickBooks authentication tokens...")
        with get_connection() as conn:
            # Reset the access token
            query = """
            UPDATE quickbooks_settings 
            SET value = '', token_expires_at = NULL, updated_at = CURRENT_TIMESTAMP 
            WHERE name = 'QB_ACCESS_TOKEN' OR name = 'QB_REFRESH_TOKEN'
            """
            conn.execute(text(query))
            conn.commit()
            print("QuickBooks tokens have been reset")
            return True
    except SQLAlchemyError as e:
        error_msg = f"Database error resetting QuickBooks auth: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        return False

def get_quickbooks_auth_status():
    """Check if QuickBooks authorization is valid and not expired with enhanced debugging"""
    try:
        print("Checking QuickBooks authentication status...")
        
        # Get connection
        conn = get_connection()
        if not conn:
            print("Failed to get database connection")
            return False, "Database connection failed"
            
        try:
            # Check for access token
            access_query = """
            SELECT value, token_expires_at 
            FROM quickbooks_settings 
            WHERE name = 'QB_ACCESS_TOKEN'
            """
            access_result = conn.execute(text(access_query))
            access_row = access_result.fetchone()
            
            # Check for refresh token
            refresh_query = """
            SELECT value 
            FROM quickbooks_settings 
            WHERE name = 'QB_REFRESH_TOKEN'
            """
            refresh_result = conn.execute(text(refresh_query))
            refresh_row = refresh_result.fetchone()
            
            # Debug output
            has_access_token = access_row is not None and access_row[0] is not None and access_row[0] != ""
            has_refresh_token = refresh_row is not None and refresh_row[0] is not None and refresh_row[0] != ""
            
            print(f"Access token present: {has_access_token}")
            print(f"Refresh token present: {has_refresh_token}")
            
            if access_row and access_row[1]:
                expiration = access_row[1]
                current_time = time.time()
                time_left = expiration - current_time
                print(f"Token expiration: {time.ctime(expiration)}")
                print(f"Current time: {time.ctime(current_time)}")
                print(f"Time left: {time_left:.2f} seconds ({time_left/60:.2f} minutes)")
            
            # Make decisions based on token presence and expiration
            if not has_access_token:
                return False, "No access token found"
                
            if not has_refresh_token:
                return False, "No refresh token found"
            
            # Check if access token is expired
            if access_row[1] and access_row[1] < time.time():
                seconds_expired = time.time() - access_row[1]
                # Even if token is expired, still consider authenticated since we can refresh
                # as long as we have the refresh token
                print(f"Token expired {seconds_expired:.0f} seconds ago, but we have refresh token")
                if has_refresh_token:
                    return True, "Token expired but can be refreshed"
                return False, f"Token expired {seconds_expired:.0f} seconds ago"
                
            return True, "Authenticated and token valid"
            
        finally:
            # Make sure to close connection
            conn.close()
            
    except SQLAlchemyError as e:
        error_msg = f"Database error checking auth status: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        return False, error_msg