import os
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import streamlit as st

# Get database connection string from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")

# Create database engine
engine = create_engine(DATABASE_URL)

def get_connection():
    """Get a database connection"""
    return engine.connect()

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
            "HOOPING_TIME_DEFAULT": {"value": 50, "description": "Default time to hoop an item (seconds)"}
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
    """Save a quote to the database"""
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