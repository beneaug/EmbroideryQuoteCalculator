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