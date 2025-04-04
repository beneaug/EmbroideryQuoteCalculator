import streamlit as st
import pyembroidery
import pandas as pd
import numpy as np
import io
import base64
import json
from PIL import Image, ImageDraw
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as ReportLabImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import tempfile
import os
import math
import time
import datetime
import requests
import urllib.parse
import database

# Disable QuickBooks functionality
QUICKBOOKS_AVAILABLE = False

# Set page config
st.set_page_config(
    page_title="Embroidery Quoting Tool",
    page_icon="🧵",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Load settings from database
material_settings = database.get_material_settings()
machine_settings = database.get_machine_settings()
labor_settings = database.get_labor_settings()

# Set constants from database with fallback defaults
POLYNEON_5500YD_PRICE = material_settings.get("POLYNEON_5500YD_PRICE", {}).get("value", 9.69)
POLYNEON_1100YD_PRICE = material_settings.get("POLYNEON_1100YD_PRICE", {}).get("value", 3.19)
BOBBIN_144_PRICE = material_settings.get("BOBBIN_144_PRICE", {}).get("value", 35.85)
BOBBIN_YARDS = material_settings.get("BOBBIN_YARDS", {}).get("value", 124)
FOAM_SHEET_PRICE = material_settings.get("FOAM_SHEET_PRICE", {}).get("value", 2.45)
FOAM_SHEET_SIZE = (18, 12)  # inches
STABILIZER_PRICE_PER_PIECE = material_settings.get("STABILIZER_PRICE_PER_PIECE", {}).get("value", 0.18)

DEFAULT_STITCH_SPEED_40WT = machine_settings.get("DEFAULT_STITCH_SPEED_40WT", {}).get("value", 750)  # rpm
DEFAULT_STITCH_SPEED_60WT = machine_settings.get("DEFAULT_STITCH_SPEED_60WT", {}).get("value", 400)  # rpm
DEFAULT_MAX_HEADS = machine_settings.get("DEFAULT_MAX_HEADS", {}).get("value", 15)
DEFAULT_COLOREEL_MAX_HEADS = machine_settings.get("DEFAULT_COLOREEL_MAX_HEADS", {}).get("value", 2)
HOOPING_TIME_DEFAULT = machine_settings.get("HOOPING_TIME_DEFAULT", {}).get("value", 50)  # seconds
DEFAULT_PRODUCTIVITY_RATE = machine_settings.get("DEFAULT_PRODUCTIVITY_RATE", {}).get("value", 1.0)
DEFAULT_COMPLEX_PRODUCTIVITY_RATE = machine_settings.get("DEFAULT_COMPLEX_PRODUCTIVITY_RATE", {}).get("value", 0.8)
DEFAULT_COLOREEL_PRODUCTIVITY_RATE = machine_settings.get("DEFAULT_COLOREEL_PRODUCTIVITY_RATE", {}).get("value", 0.75)
DEFAULT_DIGITIZING_FEE = machine_settings.get("DEFAULT_DIGITIZING_FEE", {}).get("value", 25.0)
# Buffer time settings (new)
DEFAULT_BUFFER_MINUTES = machine_settings.get("DEFAULT_BUFFER_MINUTES", {}).get("value", 4.0)  # minutes
DEFAULT_BUFFER_PERCENTAGE = machine_settings.get("DEFAULT_BUFFER_PERCENTAGE", {}).get("value", 5.0)  # % of cycle time

HOURLY_LABOR_RATE = labor_settings.get("HOURLY_LABOR_RATE", {}).get("value", 25)

# Initialize session state variables
if 'history' not in st.session_state:
    st.session_state.history = []
if 'design_info' not in st.session_state:
    st.session_state.design_info = None

# Utility Functions
def parse_embroidery_file(uploaded_file):
    """Parse embroidery file and extract key information"""
    # Save the uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_filename = tmp_file.name
    
    try:
        # Parse the file using pyembroidery
        pattern = pyembroidery.read(tmp_filename)
        
        # Extract useful information
        stitch_count = len(pattern.stitches)
        
        # Count color changes
        color_changes = 0
        for stitch in pattern.stitches:
            if stitch[2] == pyembroidery.COLOR_CHANGE:
                color_changes += 1
        
        # Get bounding box for design dimensions
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        for stitch in pattern.stitches:
            x, y = stitch[0], stitch[1]
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
        
        # Convert to inches and mm (pyembroidery units are 0.1mm)
        width_mm = (max_x - min_x) / 10
        height_mm = (max_y - min_y) / 10
        width_inches = width_mm / 25.4
        height_inches = height_mm / 25.4
        
        # Calculate design area
        design_area_sq_mm = width_mm * height_mm
        
        # Estimate thread consumption 
        # Industry standard for top thread: ~4.8 meters per 1000 stitches
        thread_length_meters = stitch_count * 0.0048
        thread_length_yards = thread_length_meters * 1.09361
        
        # Estimate bobbin thread consumption (typically about 1/3 of top thread)
        bobbin_length_meters = thread_length_meters / 3
        bobbin_length_yards = bobbin_length_meters * 1.09361
        
        # Calculate stitch density (stitches per square mm)
        stitch_density = stitch_count / design_area_sq_mm if design_area_sq_mm > 0 else 0
        
        # Calculate complexity score (0-100) based on stitch count, density, and color changes
        complexity_base = min(stitch_count / 30000, 1) * 40  # Up to 40 points for stitch count
        complexity_density = min(stitch_density * 100, 1) * 30  # Up to 30 points for density
        complexity_colors = min(color_changes / 10, 1) * 20  # Up to 20 points for color complexity
        complexity_size = min(max(width_mm, height_mm) / 200, 1) * 10  # Up to 10 points for size
        
        complexity_score = complexity_base + complexity_density + complexity_colors + complexity_size
        complexity_score = min(max(complexity_score, 0), 100)  # Clamp between 0-100
        
        # Return pattern for rendering and extracted data
        result = {
            "pattern": pattern,
            "stitch_count": stitch_count,
            "color_changes": max(1, color_changes + 1),  # +1 for initial color, minimum 1
            "width_mm": width_mm,
            "height_mm": height_mm,
            "width_inches": width_inches,
            "height_inches": height_inches,
            "thread_length_yards": thread_length_yards,
            "thread_length_meters": thread_length_meters,
            "bobbin_length_yards": bobbin_length_yards,
            "bobbin_length_meters": bobbin_length_meters,
            "complexity_score": complexity_score,
            "stitch_density": stitch_density
        }
        
        os.unlink(tmp_filename)
        return result
    
    except Exception as e:
        if os.path.exists(tmp_filename):
            os.unlink(tmp_filename)
        st.error(f"Error parsing embroidery file: {str(e)}")
        return None

def render_design_preview(pattern, width=400, height=400, use_foam=False):
    """Render a visual preview of the embroidery design at 1:1 scale"""
    # Get design dimensions
    stitches = pattern.stitches
    min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
    
    for stitch in stitches:
        x, y = stitch[0], stitch[1]
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
    
    design_width = max_x - min_x
    design_height = max_y - min_y
    
    # pyembroidery units are 0.1mm, convert to pixels (assuming 96 DPI)
    # 1 inch = 25.4mm = 96 pixels
    # So 0.1mm = 96 / 254 pixels
    pixels_per_unit = 96.0 / 254.0
    
    # Calculate the exact pixel dimensions needed for 1:1 scale
    pixel_width = int(design_width * pixels_per_unit) + 80  # Add padding
    pixel_height = int(design_height * pixels_per_unit) + 80  # Add padding
    
    # Ensure minimum dimensions
    pixel_width = max(pixel_width, width)
    pixel_height = max(pixel_height, height)
    
    # Create an image with the correct dimensions for 1:1 scale and match app background
    # Use the #fff9f0 cream color to match app background
    img = Image.new('RGB', (pixel_width, pixel_height), color='#fff9f0')
    draw = ImageDraw.Draw(img)
    
    # Draw design boundary if foam is used (add 0.5 inches around the design)
    if use_foam:
        # Convert 0.5 inches to pyembroidery units (0.1mm)
        foam_margin = int(0.5 * 25.4 * 10)  # 0.5 inches in 0.1mm units
        
        # Calculate boundary with foam margin
        boundary_min_x = min_x - foam_margin
        boundary_min_y = min_y - foam_margin
        boundary_max_x = max_x + foam_margin
        boundary_max_y = max_y + foam_margin
        
        # Calculate pixel coordinates for the foam boundary
        boundary_x1 = (boundary_min_x - min_x) * pixels_per_unit + pixel_width // 2 - (design_width * pixels_per_unit) // 2
        boundary_y1 = (boundary_min_y - min_y) * pixels_per_unit + pixel_height // 2 - (design_height * pixels_per_unit) // 2
        boundary_x2 = (boundary_max_x - min_x) * pixels_per_unit + pixel_width // 2 - (design_width * pixels_per_unit) // 2
        boundary_y2 = (boundary_max_y - min_y) * pixels_per_unit + pixel_height // 2 - (design_height * pixels_per_unit) // 2
        
        # Convert to tuple for the rectangle function
        boundary_coords = tuple([boundary_x1, boundary_y1, boundary_x2, boundary_y2])
        # Use orange outline for foam to match app's theme
        draw.rectangle(boundary_coords, outline='#f3770c', width=2)
    
    # Center the design in the image
    offset_x = pixel_width // 2 - (design_width * pixels_per_unit) // 2
    offset_y = pixel_height // 2 - (design_height * pixels_per_unit) // 2
    
    # Draw stitches
    current_color = (0, 0, 0)  # Default color is black
    last_x, last_y = None, None
    
    for stitch in stitches:
        x, y, command = stitch
        
        # Convert to pixel coordinates
        pixel_x = (x - min_x) * pixels_per_unit + offset_x
        pixel_y = (y - min_y) * pixels_per_unit + offset_y
        
        # Change color if needed
        if command == pyembroidery.COLOR_CHANGE:
            # Use a predefined color sequence for better visualization
            colors = [(0, 0, 0), (255, 0, 0), (0, 0, 255), (0, 128, 0), (128, 0, 128), (255, 165, 0)]
            current_color = colors[hash(str(current_color)) % len(colors)]
        
        # Skip jump stitches for cleaner visualization
        if command == pyembroidery.JUMP:
            last_x, last_y = pixel_x, pixel_y
            continue
        
        # Draw the stitch
        if last_x is not None and last_y is not None:
            draw.line(
                [last_x, last_y, pixel_x, pixel_y],
                fill=current_color,
                width=1
            )
        
        last_x, last_y = pixel_x, pixel_y
    
    # Add scale indicator (1 inch = 96 pixels)
    draw.line([(20, pixel_height - 30), (20 + 96, pixel_height - 30)], fill=(0, 0, 0), width=2)
    draw.text((20, pixel_height - 25), "1 inch", fill=(0, 0, 0))
    
    # Resize if needed to fit display area while maintaining aspect ratio
    if pixel_width > width or pixel_height > height:
        scale_x = width / pixel_width
        scale_y = height / pixel_height
        scale = min(scale_x, scale_y)
        new_width = int(pixel_width * scale)
        new_height = int(pixel_height * scale)
        img = img.resize((new_width, new_height), Image.LANCZOS)
    
    return img

def calculate_costs(design_info, job_inputs):
    """Calculate all costs based on design data and job inputs"""
    # Extract necessary values
    stitch_count = design_info["stitch_count"]
    color_count = job_inputs["color_count"]
    quantity = job_inputs["quantity"]
    use_foam = job_inputs["use_foam"]
    design_width_inches = design_info["width_inches"]
    design_height_inches = design_info["height_inches"]
    thread_length_yards = design_info["thread_length_yards"]
    active_heads = job_inputs["active_heads"]
    thread_weight = job_inputs["thread_weight"]
    markup_percentage = job_inputs["markup_percentage"]
    setup_fee = job_inputs["setup_fee"]
    stitch_speed = DEFAULT_STITCH_SPEED_40WT if thread_weight == "40wt" else DEFAULT_STITCH_SPEED_60WT
    coloreel_enabled = job_inputs["coloreel_enabled"]
    selected_workers = job_inputs.get("selected_workers", [])
    
    # 1. Thread consumption & cost
    thread_per_piece_yards = thread_length_yards
    total_thread_yards = thread_per_piece_yards * quantity
    
    # Different calculation if using Coloreel vs. traditional thread
    if coloreel_enabled:
        # With Coloreel, we just need one spool per head
        spools_required = active_heads
        thread_cost = spools_required * POLYNEON_5500YD_PRICE
    else:
        # Traditional method: one spool per color per head
        spools_required = color_count * active_heads
        thread_cost_per_spool = POLYNEON_5500YD_PRICE
        thread_cost = spools_required * thread_cost_per_spool
    
    # 2. Bobbin consumption & cost
    if 'bobbin_length_yards' in design_info:
        bobbin_thread_yards = design_info['bobbin_length_yards'] * quantity
    else:
        bobbin_thread_yards = thread_per_piece_yards * (1/3) * quantity  # 1/3 of top thread
    
    bobbins_required = math.ceil(bobbin_thread_yards / BOBBIN_YARDS)
    bobbin_cost = bobbins_required * (BOBBIN_144_PRICE / 144)  # Cost per bobbin
    
    # 3. Stabilizer/backing cost
    stabilizer_cost = quantity * STABILIZER_PRICE_PER_PIECE
    
    # 4. 3D Foam cost (if applicable)
    foam_cost = 0
    if use_foam:
        # Calculate how many foam pieces can be cut from one sheet
        foam_margin_inches = 0.5  # 0.5 inch margin
        pieces_per_sheet = math.floor(FOAM_SHEET_SIZE[0] / (design_width_inches + foam_margin_inches)) * \
                          math.floor(FOAM_SHEET_SIZE[1] / (design_height_inches + foam_margin_inches))
        
        if pieces_per_sheet <= 0:  # If design is too large for a single sheet
            pieces_per_sheet = 1
        
        sheets_needed = math.ceil(quantity / pieces_per_sheet)
        foam_cost = sheets_needed * FOAM_SHEET_PRICE
    
    # 5. Production time calculation
    # Get productivity rate based on the selected options
    complex_production = job_inputs.get("complex_production", False)
    custom_rate = job_inputs.get("custom_productivity_rate")
    productivity_rate = get_productivity_rate(complex_production, coloreel_enabled, custom_rate)
    
    # Stitching time (in minutes) - adjusted by productivity rate
    # Lower productivity rate means slower stitching (more time)
    stitching_time_minutes = (stitch_count / stitch_speed) / productivity_rate
    
    # Hooping time (in minutes)
    hooping_time_minutes = HOOPING_TIME_DEFAULT / 60  # Convert seconds to minutes
    
    # Total production time per piece (stitching + hooping)
    piece_production_time = stitching_time_minutes + hooping_time_minutes
    
    # Total production time for the batch, accounting for multiple heads
    pieces_per_run = min(active_heads, quantity)  # Can't use more heads than pieces
    runs_needed = math.ceil(quantity / pieces_per_run)
    
    # Calculate buffer time between cycles
    buffer_minutes = job_inputs.get("buffer_minutes", float(DEFAULT_BUFFER_MINUTES))
    buffer_percentage = job_inputs.get("buffer_percentage", float(DEFAULT_BUFFER_PERCENTAGE))
    
    # Buffer time formula: fixed time + percentage of cycle run time
    cycle_run_time = piece_production_time  # Time for a single cycle
    buffer_time_per_run = buffer_minutes + (cycle_run_time * buffer_percentage / 100)
    
    # Add buffer time to production time, but only apply it to runs_needed - 1 (no buffer after last run)
    buffer_time_total = buffer_time_per_run * max(0, runs_needed - 1)
    
    # Total production time including buffer time
    production_time_per_piece = piece_production_time  # Base time per piece (without buffer)
    total_production_time_minutes = (runs_needed * piece_production_time) + buffer_time_total
    total_production_time_hours = total_production_time_minutes / 60
    
    # 6. Labor cost
    # Use selected workers' rates if any are selected, otherwise use default rate
    if selected_workers:
        # Calculate average hourly rate of selected workers - convert to float to avoid decimal issues
        total_rate = sum(float(worker['hourly_rate']) for worker in selected_workers)
        avg_rate = total_rate / len(selected_workers)
        labor_cost = total_production_time_hours * avg_rate
        
        # Add worker information to results - convert rates to float
        worker_info = [{"name": w["name"], "rate": float(w["hourly_rate"])} for w in selected_workers]
    else:
        # Use default labor rate
        labor_cost = total_production_time_hours * float(HOURLY_LABOR_RATE)
        worker_info = [{"name": "Default Labor", "rate": float(HOURLY_LABOR_RATE)}]
    
    # 7. Total costs
    material_cost = thread_cost + bobbin_cost + stabilizer_cost + foam_cost
    direct_cost = material_cost + labor_cost
    
    # 8. Digitizing fee (if complex production is enabled)
    digitizing_fee = job_inputs.get("digitizing_fee", 0.0)
    
    # 9. Markup and final price
    profit_margin = direct_cost * (markup_percentage / 100)
    total_job_cost = direct_cost + profit_margin + setup_fee + digitizing_fee
    price_per_piece = total_job_cost / quantity if quantity > 0 else 0
    
    # Return all calculations
    return {
        "thread_cost": thread_cost,
        "bobbin_cost": bobbin_cost,
        "stabilizer_cost": stabilizer_cost,
        "foam_cost": foam_cost,
        "material_cost": material_cost,
        "production_time_minutes": total_production_time_minutes,
        "production_time_hours": total_production_time_hours,
        "labor_cost": labor_cost,
        "direct_cost": direct_cost,
        "profit_margin": profit_margin,
        "setup_fee": setup_fee,
        "digitizing_fee": digitizing_fee,
        "total_job_cost": total_job_cost,
        "price_per_piece": price_per_piece,
        "runs_needed": runs_needed,
        "spools_required": spools_required,
        "bobbins_required": bobbins_required,
        "productivity_rate": productivity_rate,
        "worker_info": worker_info,
        "buffer_time_minutes": buffer_time_total,
        "buffer_minutes_per_run": buffer_minutes,
        "buffer_percentage": buffer_percentage,
        "piece_production_time": piece_production_time
    }

def generate_detailed_quote_pdf(design_info, job_inputs, cost_results):
    """Generate a detailed internal quote PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    heading_style = styles["Heading2"]
    normal_style = styles["Normal"]
    
    # Custom styles
    section_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        spaceAfter=6,
        spaceBefore=12,
        textColor=colors.HexColor('#3a1d0d')
    )
    
    # Header with logo and quote number
    try:
        logo_path = "attached_assets/Asset 1@4x.png"
        logo_img = Image(logo_path, width=2*inch, height=0.75*inch)
        
        # Create a table for the header with logo on left, quote info on right
        quote_number = f"INTERNAL QUOTE {str(len(st.session_state.history) + 1).zfill(4)}"
        date_str = datetime.datetime.now().strftime("%B %d, %Y")
        
        header_data = [[logo_img, quote_number], ["", date_str]]
        header_table = Table(header_data, colWidths=[4*inch, 3*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 1), 'LEFT'),
            ('ALIGN', (1, 0), (1, 1), 'RIGHT'),
            ('VALIGN', (0, 0), (1, 1), 'TOP'),
            ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (1, 0), (1, 0), 14),
        ]))
        elements.append(header_table)
    except Exception as e:
        # Fallback if logo isn't available
        elements.append(Paragraph("Embroidery Job Quote (Internal)", title_style))
    
    elements.append(Spacer(1, 0.4 * inch))
    
    # Job information
    elements.append(Paragraph("Job Information", section_style))
    
    job_info_data = [
        ["Job Name", job_inputs.get("job_name", "")],
        ["Customer", job_inputs.get("customer_name", "")],
        ["Date", datetime.datetime.now().strftime("%Y-%m-%d")],
        ["Quantity", str(job_inputs["quantity"])],
        ["Garment Type", job_inputs["garment_type"]],
        ["Fabric Type", job_inputs["fabric_type"]],
        ["Placement", job_inputs.get("placement", "")],
    ]
    
    job_info_table = Table(job_info_data, colWidths=[2 * inch, 4 * inch])
    job_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(job_info_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Design information
    elements.append(Paragraph("Design Information", section_style))
    
    design_info_data = [
        ["Stitch Count", f"{design_info['stitch_count']:,}"],
        ["Colors", str(job_inputs["color_count"])],
        ["Dimensions", f"{design_info['width_inches']:.2f}\" × {design_info['height_inches']:.2f}\""],
        ["Thread Length", f"{design_info['thread_length_yards']:.2f} yards per piece"],
        ["Complexity Score", f"{design_info['complexity_score']:.1f}/100"],
    ]
    
    design_info_table = Table(design_info_data, colWidths=[2 * inch, 4 * inch])
    design_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(design_info_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Production details
    elements.append(Paragraph("Production Details", section_style))
    
    production_data = [
        ["Machine Heads", str(job_inputs["active_heads"])],
        ["Thread Weight", job_inputs["thread_weight"]],
        ["Hoop Size", job_inputs["hoop_size"]],
        ["Stabilizer Type", job_inputs["stabilizer_type"]],
        ["Using 3D Foam", "Yes" if job_inputs["use_foam"] else "No"],
        ["Using Coloreel", "Yes" if job_inputs["coloreel_enabled"] else "No"],
        ["Stitch Time", f"{cost_results['piece_production_time']:.1f} minutes per piece"],
        ["Buffer Time", f"{cost_results['buffer_time_minutes']:.1f} min ({cost_results['buffer_minutes_per_run']:.1f} min + {cost_results['buffer_percentage']:.1f}% of cycle)"],
        ["Total Production Time", f"{cost_results['production_time_hours']:.2f} hours ({cost_results['production_time_minutes']:.1f} min)"],
        ["Runs Needed", str(cost_results['runs_needed'])],
    ]
    
    production_table = Table(production_data, colWidths=[2 * inch, 4 * inch])
    production_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(production_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Cost Breakdown
    elements.append(Paragraph("Cost Breakdown", section_style))
    
    # Prepare cost data for the table
    cost_data = [
        ["Thread Cost", f"${cost_results['thread_cost']:.2f}"],
        ["Bobbin Cost", f"${cost_results['bobbin_cost']:.2f}"],
        ["Stabilizer Cost", f"${cost_results['stabilizer_cost']:.2f}"],
        ["Foam Cost", f"${cost_results['foam_cost']:.2f}"],
        ["Total Material Cost", f"${cost_results['material_cost']:.2f}"],
        ["Labor Cost", f"${cost_results['labor_cost']:.2f}"],
        ["Direct Cost", f"${cost_results['direct_cost']:.2f}"],
        ["Profit Margin", f"${cost_results['profit_margin']:.2f} ({job_inputs['markup_percentage']}%)"],
        ["Setup Fee", f"${cost_results['setup_fee']:.2f}"],
    ]
    
    # Add digitizing fee if applicable
    if job_inputs.get("complex_production", False) and cost_results.get("digitizing_fee", 0) > 0:
        cost_data.append(["Digitizing Fee", f"${cost_results['digitizing_fee']:.2f}"])
    
    # Add total cost rows
    cost_data.extend([
        ["TOTAL JOB COST", f"${cost_results['total_job_cost']:.2f}"],
        ["Price Per Piece", f"${cost_results['price_per_piece']:.2f}"],
    ])
    
    cost_table = Table(cost_data, colWidths=[2 * inch, 4 * inch])
    cost_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, -2), (-1, -1), colors.lightskyblue),
        ('TEXTCOLOR', (0, -2), (-1, -1), colors.darkblue),
        ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(cost_table)
    
    # Build the PDF
    doc.build(elements)
    
    # Return the PDF data
    buffer.seek(0)
    return buffer

def generate_customer_quote_pdf(design_info, job_inputs, cost_results):
    """Generate a client-facing quote PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    heading_style = styles["Heading2"]
    normal_style = styles["Normal"]
    
    # Custom styles
    section_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        spaceAfter=6,
        spaceBefore=12,
        textColor=colors.HexColor('#3a1d0d')
    )
    
    # Header with logo and quote number
    try:
        logo_path = "attached_assets/Asset 1@4x.png"
        logo_img = Image(logo_path, width=2*inch, height=0.75*inch)
        
        # Create a table for the header with logo on left, quote info on right
        quote_number = f"QUOTE {str(len(st.session_state.history) + 1).zfill(4)}"
        date_str = datetime.datetime.now().strftime("%B %d, %Y")
        
        header_data = [[logo_img, quote_number], ["", date_str]]
        header_table = Table(header_data, colWidths=[4*inch, 3*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 1), 'LEFT'),
            ('ALIGN', (1, 0), (1, 1), 'RIGHT'),
            ('VALIGN', (0, 0), (1, 1), 'TOP'),
            ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (1, 0), (1, 0), 14),
        ]))
        elements.append(header_table)
    except Exception as e:
        # Fallback if logo isn't available
        elements.append(Paragraph("Embroidery Quote", title_style))
    
    elements.append(Spacer(1, 0.4 * inch))
    
    # Company info (styled to match 12ozProphet example)
    company_info = """
    <b>Your Embroidery Company</b><br/>
    123 Stitch Lane<br/>
    Embroidery City, EC 12345<br/><br/>
    Phone: (555) 123-4567<br/>
    Email: info@yourembroidery.com<br/>
    Web: www.yourembroidery.com
    """
    elements.append(Paragraph(company_info, normal_style))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Job information
    elements.append(Paragraph("Quote Details", section_style))
    
    job_info_data = [
        ["Quote Date", datetime.datetime.now().strftime("%Y-%m-%d")],
        ["Job Name", job_inputs.get("job_name", "")],
        ["Customer", job_inputs.get("customer_name", "")],
        ["Quantity", str(job_inputs["quantity"])],
        ["Garment Type", job_inputs["garment_type"]],
        ["Placement", job_inputs.get("placement", "")],
    ]
    
    job_info_table = Table(job_info_data, colWidths=[2 * inch, 4 * inch])
    job_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(job_info_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Design information (simplified for customer)
    elements.append(Paragraph("Design Information", section_style))
    
    design_info_data = [
        ["Stitch Count", f"{design_info['stitch_count']:,}"],
        ["Colors", str(job_inputs["color_count"])],
        ["Dimensions", f"{design_info['width_inches']:.2f}\" × {design_info['height_inches']:.2f}\""],
    ]
    
    design_info_table = Table(design_info_data, colWidths=[2 * inch, 4 * inch])
    design_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(design_info_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Pricing (simplified)
    elements.append(Paragraph("Quote Summary", section_style))
    
    # Determine if we have additional fees
    has_setup_fee = cost_results['setup_fee'] > 0
    has_digitizing_fee = cost_results.get('digitizing_fee', 0) > 0 and job_inputs.get('complex_production', False)
    
    if has_setup_fee or has_digitizing_fee:
        pricing_data = []
        
        # Add setup fee if applicable
        if has_setup_fee:
            pricing_data.append(["Setup Fee", f"${cost_results['setup_fee']:.2f}"])
            
        # Add digitizing fee if applicable
        if has_digitizing_fee:
            pricing_data.append(["Digitizing Fee", f"${cost_results['digitizing_fee']:.2f}"])
            
        # Calculate the remaining cost (excluding fees)
        non_fee_costs = cost_results['total_job_cost']
        if has_setup_fee:
            non_fee_costs -= cost_results['setup_fee']
        if has_digitizing_fee:
            non_fee_costs -= cost_results['digitizing_fee']
            
        pricing_data.append(["Embroidery Cost", f"${non_fee_costs:.2f}"])
        pricing_data.append(["TOTAL", f"${cost_results['total_job_cost']:.2f}"])
        pricing_data.append(["Price Per Piece", f"${cost_results['price_per_piece']:.2f}"])
    else:
        pricing_data = [
            ["Total Cost", f"${cost_results['total_job_cost']:.2f}"],
            ["Price Per Piece", f"${cost_results['price_per_piece']:.2f}"],
        ]
    
    pricing_table = Table(pricing_data, colWidths=[2 * inch, 4 * inch])
    pricing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightskyblue),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.darkblue),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(pricing_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Terms and conditions
    elements.append(Paragraph("Terms & Conditions", section_style))
    terms = """
    • This quote is valid for 30 days from the quote date.
    • 50% deposit required to begin production.
    • Production time: 5-7 business days after approval.
    • Price does not include garments unless specified.
    • Artwork/digitizing fees may apply for design modifications.
    """
    elements.append(Paragraph(terms, normal_style))
    
    # Build the PDF
    doc.build(elements)
    
    # Return the PDF data
    buffer.seek(0)
    return buffer

def get_download_link(buffer, filename, text):
    """Generate a download link for a file"""
    b64 = base64.b64encode(buffer.read()).decode()
    href = f'''
    <a href="data:application/octet-stream;base64,{b64}" 
       download="{filename}" 
       class="download-button" 
       style="color: white; background: linear-gradient(90deg, #f3770c 0%, #f5993c 100%); display: block; padding: 12px 20px; margin: 10px 5px; border-radius: 15px; text-decoration: none; text-align: center; box-shadow: 0 4px 10px rgba(243, 119, 12, 0.3); font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif; font-weight: 600; transition: all 0.3s ease;">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="white" viewBox="0 0 16 16" style="vertical-align: middle; margin-right: 10px;">
            <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
            <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>
        </svg>
        {text}
    </a>
    '''
    return href

# QuickBooks Integration Functions
def get_quickbooks_client():
    """Initialize and return a QuickBooks client with simple, reliable token handling
    
    This function implements a straightforward approach to QuickBooks API authentication
    using the intuit-oauth library and the python-quickbooks package.
    """
    # Use session state to avoid redundant API calls on Streamlit reruns
    if "qb_client" in st.session_state and "qb_auth_timestamp" in st.session_state:
        # If we have a client in session state and it's less than 10 minutes old, use it
        if time.time() - st.session_state.qb_auth_timestamp < 600:  # 10 minutes
            return st.session_state.qb_client, None
    
    if not QUICKBOOKS_AVAILABLE:
        return None, "QuickBooks libraries not available"
    
    # Get settings from database
    qb_settings = database.get_quickbooks_settings()
    
    # Check for required settings
    required_settings = ['QB_CLIENT_ID', 'QB_CLIENT_SECRET', 'QB_REALM_ID', 'QB_REFRESH_TOKEN']
    missing_settings = [s for s in required_settings if not qb_settings.get(s, {}).get('value')]
    
    if missing_settings:
        missing_list = ', '.join(missing_settings)
        return None, f"Missing QuickBooks settings: {missing_list}"
    
    try:
        # Get necessary credentials and tokens
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value')
        access_token = qb_settings.get('QB_ACCESS_TOKEN', {}).get('value', '')
        refresh_token = qb_settings.get('QB_REFRESH_TOKEN', {}).get('value')
        realm_id = qb_settings.get('QB_REALM_ID', {}).get('value')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')
        
        # Get redirect URI with fallback
        redirect_uri = qb_settings.get('QB_REDIRECT_URI', {}).get('value')
        if not redirect_uri:
            # Use the Replit domain as the default redirect URI
            import os
            replit_domain = os.environ.get("REPLIT_DOMAINS")
            if replit_domain:
                replit_domain = replit_domain.split(',')[0].strip()
                redirect_uri = f"https://{replit_domain}"
            else:
                redirect_uri = "http://localhost:5000"
        
        # Log the settings (with sensitive data masked)
        print(f"QuickBooks settings:")
        print(f"- Client ID: {client_id[:5]}..." if client_id else "- Client ID: Not set")
        print(f"- Client Secret: {client_secret[:5]}..." if client_secret else "- Client Secret: Not set")
        print(f"- Access Token: {'Present' if access_token else 'Not set'}")
        print(f"- Refresh Token: {'Present' if refresh_token else 'Not set'}")
        print(f"- Realm ID: {realm_id}")
        print(f"- Environment: {environment}")
        print(f"- Redirect URI: {redirect_uri}")
        
        # Import required modules
        from intuitlib.client import AuthClient
        from quickbooks.auth import Oauth2SessionManager
        from quickbooks.client import QuickBooks
        
        # Check if tokens need to be refreshed
        token_expires_at = qb_settings.get('QB_ACCESS_TOKEN_EXPIRES_AT', {}).get('value')
        current_time = time.time()
        
        needs_refresh = False
        if token_expires_at:
            # Convert to float if stored as string
            expires_at = float(token_expires_at) if isinstance(token_expires_at, str) else token_expires_at
            time_left = expires_at - current_time
            print(f"Access token expires in: {time_left:.2f} seconds ({time_left/60:.2f} minutes)")
            
            # Refresh if less than 5 minutes remaining
            if time_left < 300:
                print("Token close to expiration, will refresh")
                needs_refresh = True
        else:
            # No expiration time means we should refresh
            print("No token expiration time, will attempt refresh")
            needs_refresh = True
            
        # Always refresh if access token is missing
        if not access_token:
            print("No access token found, will attempt refresh")
            needs_refresh = True
            
        # Refresh tokens if needed
        if needs_refresh:
            print("Refreshing tokens...")
            try:
                # Create auth client
                auth_client = AuthClient(
                    client_id=client_id,
                    client_secret=client_secret,
                    environment=environment,
                    redirect_uri=redirect_uri
                )
                
                # Refresh the token
                try:
                    auth_client.refresh(refresh_token=refresh_token)
                    
                    # Update with new tokens
                    access_token = auth_client.access_token
                    refresh_token = auth_client.refresh_token
                    token_expiration = time.time() + auth_client.expires_in
                    
                    # Save to database
                    database.update_quickbooks_token('QB_ACCESS_TOKEN', access_token, token_expiration)
                    database.update_quickbooks_token('QB_REFRESH_TOKEN', refresh_token)
                    
                    print(f"Token refresh successful, expires at: {time.ctime(token_expiration)}")
                    
                except Exception as refresh_error:
                    # Handle token refresh errors
                    error_str = str(refresh_error).lower()
                    
                    if "invalid_grant" in error_str or "token expired" in error_str:
                        print("Refresh token expired or invalid")
                        return None, "QuickBooks authentication expired. Please reconnect your account."
                    else:
                        raise refresh_error
                    
            except Exception as e:
                print(f"Error refreshing tokens: {str(e)}")
                import traceback
                print(traceback.format_exc())
                
                # Reset tokens on error
                database.reset_quickbooks_auth()
                
                return None, f"Error refreshing QuickBooks connection: {str(e)}"
        
        # Create session manager and client
        print("Creating QuickBooks client...")
        base_url = "sandbox" if environment.lower() == "sandbox" else "production"
        
        # Create session manager with our tokens
        session_manager = Oauth2SessionManager(
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
            realm_id=realm_id,
            base_url=base_url
        )
        
        # Create QuickBooks client
        client = QuickBooks(
            session_manager=session_manager,
            company_id=realm_id,
            minorversion=69  # Latest version
        )
        
        # Set sandbox mode based on environment
        client.sandbox = (environment.lower() == 'sandbox')
        
        # Set up token refresh callback to save refreshed tokens
        def token_refresh_callback(session_manager):
            print("Token refresh callback triggered")
            try:
                # Save the refreshed tokens to database
                if hasattr(session_manager, 'access_token') and session_manager.access_token:
                    # Default to 1 hour if expires_in not available
                    expires_in = getattr(session_manager, 'expires_in', 3600)
                    token_expiration = time.time() + expires_in
                    
                    database.update_quickbooks_token(
                        'QB_ACCESS_TOKEN', 
                        session_manager.access_token,
                        token_expiration
                    )
                
                if hasattr(session_manager, 'refresh_token') and session_manager.refresh_token:
                    database.update_quickbooks_token('QB_REFRESH_TOKEN', session_manager.refresh_token)
                    
            except Exception as e:
                print(f"Error in token refresh callback: {str(e)}")
        
        # Set the callback
        session_manager.callback = token_refresh_callback
        
        # Store client in session state to avoid redundant initialization
        st.session_state.qb_client = client
        st.session_state.qb_auth_timestamp = time.time()
        
        print("===== QUICKBOOKS CLIENT READY =====\n")
        return client, None
        
    except Exception as e:
        # Comprehensive error handling
        import traceback
        error_details = traceback.format_exc()
        print(f"Error initializing QuickBooks client: {str(e)}")
        print(error_details)
        return None, f"Unable to connect to QuickBooks: {str(e)}"

def export_to_quickbooks(design_info, job_inputs, cost_results):
    """Export quote as an estimate to QuickBooks with enhanced error handling and state preservation
    
    Returns:
        tuple: (success, message, estimate_id, estimate_url) with estimate_id and estimate_url set when successful
    """
    # Make defensive copies of all input data to avoid state issues
    import copy
    design_info = copy.deepcopy(design_info) if design_info else {}
    job_inputs = copy.deepcopy(job_inputs) if job_inputs else {}
    cost_results = copy.deepcopy(cost_results) if cost_results else {}
    
    # Check QuickBooks availability
    if not QUICKBOOKS_AVAILABLE:
        return False, "QuickBooks integration is not available. Please install the required libraries.", None, None
    
    # Debug info to aid in troubleshooting
    print(f"\n\n===== QUICKBOOKS EXPORT STARTED =====")
    print(f"Design info: {len(design_info)} fields")
    print(f"Job inputs: {len(job_inputs)} fields")
    print(f"Cost results: {len(cost_results)} fields")
    
    # Get QuickBooks client with better logging
    print(f"Step 1: Getting QuickBooks client...")
    client, error = get_quickbooks_client()
    if not client:
        print(f"ERROR: Could not get QuickBooks client: {error}")
        return False, error, None, None
    print(f"QuickBooks client obtained successfully")
    
    try:
        # Import necessary modules
        from quickbooks.objects.customer import Customer
        from quickbooks.objects.estimate import Estimate
        from quickbooks.objects.item import Item
        from quickbooks.objects.detailline import SalesItemLine, SalesItemLineDetail
        from quickbooks.objects.base import Ref
        
        # Log the QuickBooks realm ID and other debug information
        qb_settings = database.get_quickbooks_settings()
        realm_id = qb_settings.get('QB_REALM_ID', {}).get('value')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')
        
        # Print detailed export information
        print(f"Step 2: Preparing export data")
        print(f"QuickBooks Environment: {environment}")
        print(f"QuickBooks Realm ID: {realm_id}")
        print(f"Job Name: {job_inputs.get('job_name', 'Embroidery Job')}")
        print(f"Customer Name: {job_inputs.get('customer_name', 'New Customer')}")
        print(f"Quantity: {job_inputs.get('quantity', 1)}")
        print(f"Total Job Cost: ${cost_results['total_job_cost']:.2f}")
        print(f"Price Per Piece: ${cost_results['price_per_piece']:.2f}")
        
        # Save current token data before proceeding (this helps prevent auth issues)
        print(f"Step 3: Verifying QuickBooks authorization...")
        auth_status, auth_message = database.get_quickbooks_auth_status()
        if not auth_status:
            print(f"ERROR: QuickBooks authorization invalid: {auth_message}")
            return False, f"QuickBooks authorization invalid: {auth_message}. Please re-authorize in Admin settings.", None, None
        else:
            print(f"QuickBooks authorization valid")
        
        # Set default customer name if missing
        customer_name = job_inputs.get("customer_name", "").strip()
        if not customer_name:
            customer_name = "New Embroidery Customer"
            print(f"Using default customer name: '{customer_name}'")
        else:
            print(f"Using customer name from job: '{customer_name}'")
        
        # Clean customer name to avoid query issues
        safe_customer_name = customer_name.replace("'", "''")
        
        # Step 4: Find or create customer
        print(f"Step 4: Finding or creating customer...")
        try:
            # First try to query for the customer
            query = f"SELECT * FROM Customer WHERE DisplayName = '{safe_customer_name}'"
            print(f"Running customer query: {query}")
            customers = Customer.query(query, qb=client)
            print(f"Found {len(customers)} customers matching '{customer_name}'")
            
            # Create customer if none found
            if not customers:
                print(f"Creating new customer: '{customer_name}'")
                try:
                    # Use fallback customer name if needed
                    if not customer_name or customer_name.isspace():
                        customer_name = f"Embroidery Customer {int(time.time())}"
                    
                    # Create the customer with proper formatting
                    customer = Customer()
                    customer.DisplayName = customer_name
                    customer.CompanyName = customer_name
                    
                    # Parse first/last name if a full name is provided
                    if ' ' in customer_name:
                        customer.GivenName = customer_name.split(' ')[0]
                        customer.FamilyName = ' '.join(customer_name.split(' ')[1:])
                    
                    # Add print email if needed
                    customer.PrimaryEmailAddr = {"Address": ""}
                    
                    # Save the customer
                    print(f"Saving new customer...")
                    customer.save(qb=client)
                    print(f"New customer created with ID: {customer.Id}")
                except Exception as ce:
                    print(f"Error creating customer: {str(ce)}")
                    # Try a simplified approach as fallback
                    try:
                        print("Trying simplified customer creation")
                        customer = Customer()
                        customer.DisplayName = f"Embroidery Customer {int(time.time())}"
                        customer.CompanyName = customer.DisplayName
                        customer.save(qb=client)
                        print(f"Created generic customer with ID: {customer.Id}")
                    except Exception as simple_ce:
                        print(f"Simple customer creation also failed: {str(simple_ce)}")
                        return False, f"Could not create a customer in QuickBooks. Error: {str(simple_ce)}", None, None
            else:
                # Use existing customer
                customer = customers[0]
                print(f"Using existing customer: {customer.DisplayName} (ID: {customer.Id})")
            
            # Step 5: Create new estimate
            print(f"Step 5: Creating new estimate...")
            estimate = Estimate()
            
            # Set the customer reference
            print(f"Setting customer reference to ID: {customer.Id}")
            estimate.CustomerRef = customer.to_ref()
            
            # Add comprehensive job details to memo with proper formatting
            job_name = job_inputs.get("job_name", "Embroidery Job")
            stitch_count = design_info.get('stitch_count', 0)
            color_count = job_inputs.get('color_count', 1)
            garment_type = job_inputs.get('garment_type', 'Garment')
            quantity = job_inputs.get('quantity', 1)
            file_name = design_info.get('file_name', 'Custom design')
            placement = job_inputs.get('placement', 'Standard placement')
            use_foam = job_inputs.get('use_foam', False)
            foam_text = "3D Foam" if use_foam else "Flat Embroidery"
            
            # Create a detailed memo that will display prominently in QuickBooks
            memo_text = (
                f"Embroidery Job: {job_name}\n"
                f"File: {file_name}\n"
                f"Specs: {stitch_count:,} stitches, {color_count} colors, {foam_text}\n"
                f"Garment: {garment_type}, {quantity} pieces\n"
                f"Placement: {placement}"
            )
            print(f"Setting memo: {memo_text}")
            estimate.CustomerMemo = {"value": memo_text}
            
            # Also set the PrintStatus to ensure it's ready to view in QuickBooks
            estimate.PrintStatus = "NeedToPrint"
            
            # Add a delivery date based on production time
            import datetime
            prod_time_hours = cost_results.get('production_time_hours', 24)
            # Convert to business days (assuming 8-hour workday)
            prod_days = max(1, round(prod_time_hours / 8))
            # Calculate the estimated delivery date (business days from now)
            today = datetime.date.today()
            delivery_date = today + datetime.timedelta(days=(prod_days + 1))  # Add 1 day for delivery
            # Format date for QuickBooks
            estimate.DeliveryDate = delivery_date.strftime("%Y-%m-%d")
            
            # Step 6: Get or create service item
            print(f"Step 6: Finding or creating service item...")
            try:
                item_query = "SELECT * FROM Item WHERE Type = 'Service' AND Name = 'Embroidery Services'"
                print(f"Running item query: {item_query}")
                items = Item.query(item_query, qb=client)
                print(f"Found {len(items)} matching service items")
                
                if not items:
                    # Create the service item
                    print("Creating new 'Embroidery Services' item")
                    
                    # First get an income account to use
                    from quickbooks.objects.account import Account
                    print("Querying for income accounts...")
                    income_accounts = Account.query("SELECT * FROM Account WHERE AccountType = 'Income'", qb=client)
                    
                    if not income_accounts:
                        print("No income accounts found. Cannot create item.")
                        return False, "No income accounts found in QuickBooks. Please create an income account first.", None, None
                    
                    # Use the first available income account
                    income_account = income_accounts[0]
                    print(f"Using income account: {income_account.Name} (ID: {income_account.Id})")
                    
                    # Create the item with proper settings
                    item = Item()
                    item.Name = "Embroidery Services"
                    item.Description = "Embroidery services including digitizing, setup, and production"
                    item.Type = "Service"
                    item.IncomeAccountRef = income_account.to_ref()
                    item.Taxable = False
                    item.UnitPrice = 0
                    item.TrackQtyOnHand = False
                    
                    # Save the item
                    print("Saving new service item...")
                    item.save(qb=client)
                    print(f"Created service item with ID: {item.Id}")
                else:
                    # Use existing item
                    item = items[0]
                    print(f"Using existing item: {item.Name} (ID: {item.Id})")
                
                # Step 7: Create line item
                print(f"Step 7: Creating line item...")
                line = SalesItemLine()
                
                # Format the description properly with more details for better QuickBooks reporting
                quantity = job_inputs.get('quantity', 1)
                stitch_count = design_info.get('stitch_count', 0)
                garment_type = job_inputs.get('garment_type', 'Garment')
                placement = job_inputs.get('placement', 'Standard placement')
                job_name = job_inputs.get('job_name', 'Embroidery Job')
                file_name = design_info.get('file_name', 'Custom design')
                color_count = job_inputs.get('color_count', 1)
                use_foam = job_inputs.get('use_foam', False)
                foam_text = "3D Foam" if use_foam else "Flat Embroidery"
                
                # Create a detailed item description that will show up in QuickBooks reports
                line.Description = (
                    f"Embroidery: {job_name} - {file_name}\n"
                    f"{quantity} pieces, {stitch_count:,} stitches, {color_count} colors\n"
                    f"{garment_type}, {placement}, {foam_text}"
                )
                
                # Set amounts as strings to avoid precision issues
                total_cost = float(cost_results['total_job_cost'])
                per_piece = float(cost_results['price_per_piece'])
                
                line.Amount = round(total_cost, 2)
                line.DetailType = "SalesItemLineDetail"
                
                # Set line item details
                detail = SalesItemLineDetail()
                detail.ItemRef = item.to_ref()
                detail.Qty = quantity
                detail.UnitPrice = round(per_piece, 2)
                line.SalesItemLineDetail = detail
                
                # Add line to estimate
                estimate.Line = []
                estimate.Line.append(line)
                print("Line item created successfully")
                
                # Step 8: Save the estimate
                print(f"Step 8: Saving estimate to QuickBooks...")
                estimate.save(qb=client)
                
                # Get estimate details
                estimate_id = estimate.Id if hasattr(estimate, 'Id') else "Unknown"
                estimate_number = estimate.DocNumber if hasattr(estimate, 'DocNumber') else "Unknown"
                print(f"Estimate saved with ID: {estimate_id}, Number: {estimate_number}")
                
                # Return success message with estimate ID and URL for direct linking
                # Construct the URL to the estimate in QuickBooks
                base_url = "https://app.sandbox.qbo.intuit.com" if environment == "sandbox" else "https://app.qbo.intuit.com"
                estimate_url = f"{base_url}/app/estimate?txnId={estimate_id}"
                
                # Return tuple with success flag, message, estimate ID, and direct URL
                return True, (
                    f"Estimate #{estimate_number} (ID: {estimate_id}) created successfully! "
                    f"Customer: {customer.DisplayName}, Amount: ${total_cost:.2f}. "
                    f"You can view it in QuickBooks {environment} under Sales > Estimates."
                ), estimate_id, estimate_url
                
            except Exception as ie:
                print(f"Error handling items: {str(ie)}")
                import traceback
                print(traceback.format_exc())
                return False, f"Error with service item: {str(ie)}", None, None
                
        except Exception as ce:
            print(f"Error handling customer: {str(ce)}")
            import traceback
            print(traceback.format_exc())
            return False, f"Error with customer: {str(ce)}", None, None
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"QuickBooks Export Error: {str(e)}")
        print(f"Error details: {error_details}")
        return False, f"Error exporting to QuickBooks: {str(e)}", None, None

def get_quickbooks_auth_url():
    """Generate QuickBooks authorization URL with direct callback to our Streamlit app
    
    This function creates an authorization URL that redirects directly to our Streamlit app
    at the /callback path, where the token exchange is handled without relying on
    a separate OAuth server.
    
    Returns:
        str: Authorization URL or None if error
    """
    # Use session state to avoid regenerating the URL on every rerun
    if "qb_auth_url" in st.session_state:
        return st.session_state.qb_auth_url
        
    try:
        # Get settings from database
        qb_settings = database.get_quickbooks_settings()
        print("=== GENERATING QUICKBOOKS AUTH URL ===")
        
        # Get client credentials
        client_id = qb_settings.get('QB_CLIENT_ID', {}).get('value', '')
        client_secret = qb_settings.get('QB_CLIENT_SECRET', {}).get('value', '')
        environment = qb_settings.get('QB_ENVIRONMENT', {}).get('value', 'sandbox')
        
        # Verify client credentials are set
        if not client_id or not client_secret:
            error_msg = "Missing QuickBooks client credentials. Please set them in the Admin settings."
            print(error_msg)
            st.error(error_msg)
            return None
        
        # Get redirect URI - CRITICAL for OAuth flow
        import os
        
        # IMPORTANT: For Replit, always use the actual Replit domain for the callback
        # This ensures the callback comes back to our application properly
        replit_domain = os.environ.get("REPLIT_DOMAINS", "")
        
        if replit_domain:
            # Parse the first domain from the comma-separated list
            replit_domain = replit_domain.split(',')[0].strip()
            # Set the callback URL to use this domain
            redirect_uri = f"https://{replit_domain}/callback"
            print(f"Using redirect URI from Replit domain: {redirect_uri}")
        else:
            # Fallback for local development (should never happen in production)
            redirect_uri = "https://embroideryquotecalculator.juliewoodland.repl.co/callback"
            print(f"WARNING: Using hardcoded fallback redirect URI: {redirect_uri}")
        
        # Always update the redirect URI in the database to ensure consistency
        database.update_setting("quickbooks_settings", "QB_REDIRECT_URI", redirect_uri)
        
        # Initialize the OAuth client
        try:
            from intuitlib.client import AuthClient
            from intuitlib.enums import Scopes
            
            # Create the OAuth client with our credentials and redirect URI
            auth_client = AuthClient(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                environment=environment
            )
            
            # Define scopes for the authorization request
            scopes = [
                Scopes.ACCOUNTING,  # For financial data access
                Scopes.OPENID       # For authentication
            ]
            
            # Generate a unique state parameter for CSRF protection
            import uuid, time
            state = f"{str(uuid.uuid4())}_{int(time.time())}"
            
            # Get the authorization URL from the Intuit library
            auth_url = auth_client.get_authorization_url(scopes)
            
            # Add the state parameter to the URL
            from urllib.parse import urlparse, parse_qs, urlencode
            
            parsed_url = urlparse(auth_url)
            params = parse_qs(parsed_url.query)
            params['state'] = [state]
            
            # Reconstruct the URL with our added state parameter
            query_string = urlencode(params, doseq=True)
            new_url = parsed_url._replace(query=query_string).geturl()
            
            # Store the URL in session state to avoid regenerating it
            st.session_state.qb_auth_url = new_url
            
            return new_url
            
        except ImportError as imp_err:
            error_msg = f"Failed to import QuickBooks libraries: {str(imp_err)}"
            print(error_msg)
            st.error(error_msg)
            return None
        
    except Exception as e:
        import traceback
        error_msg = f"Error generating QuickBooks auth URL: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        st.error(f"Error connecting to QuickBooks: {str(e)}")
        return None


def get_productivity_rate(complex_production, coloreel_enabled, custom_rate=None):
    """Calculate productivity rate based on the selected options"""
    # If a custom rate is provided, use it
    if custom_rate is not None:
        return float(custom_rate)
    # If Coloreel is enabled, use the Coloreel productivity rate
    elif coloreel_enabled:
        return float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE)
    # If complex production is enabled, use the complex productivity rate
    elif complex_production:
        return float(DEFAULT_COMPLEX_PRODUCTIVITY_RATE)
    # Otherwise, use the default productivity rate
    else:
        return float(DEFAULT_PRODUCTIVITY_RATE)

# Main Application
def main():
    # Check for query parameters that could contain OAuth callback data
    query_params = st.query_params
    
    # ----- HANDLE QUICKBOOKS OAUTH CALLBACK -----
    # New implementation for the dedicated Flask OAuth server
    
    # Handle success message from the OAuth server
    if 'qb_auth_success' in query_params:
        st.markdown("## QuickBooks Authentication")
        st.success("✅ Successfully connected to QuickBooks!")
        st.info("Your connection has been established. You can now use QuickBooks features.")
        
        # Display connection details
        with st.expander("Connection Details"):
            # Get QuickBooks settings from database to show the details
            qb_settings = database.get_quickbooks_settings()
            realm_id = qb_settings.get('QB_REALM_ID', {}).get('value', 'Unknown')
            st.info(f"Company ID: {realm_id}")
            
            # Get access token info
            access_token_info = qb_settings.get('QB_ACCESS_TOKEN', {})
            if access_token_info and access_token_info.get('value'):
                token_preview = access_token_info.get('value')[:10] + '...'
                st.info(f"Access Token: {token_preview}")
                
                # If expiry is available, show it
                if 'expires_at' in access_token_info:
                    import time
                    expiry_time = float(access_token_info['expires_at'])
                    remaining = expiry_time - time.time()
                    if remaining > 0:
                        st.info(f"Token expires in: {int(remaining)} seconds")
                    else:
                        st.warning("Token has expired. It will be refreshed automatically on next API call.")
        
        # Clear the query parameters and continue
        if st.button("Continue to Application", key="success_continue"):
            st.query_params.clear()
            st.rerun()
        st.stop()
    
    # Handle error parameters from OAuth server
    if 'error' in query_params:
        st.markdown("## QuickBooks Authentication")
        error_msg = query_params['error'][0]
        error_desc = query_params.get('error_description', ['Unknown error'])[0]
        st.error(f"Authentication Error: {error_msg}")
        st.warning(f"Error details: {error_desc}")
        
        # Special handling for invalid_grant errors
        if "invalid_grant" in error_msg.lower():
            st.info("Each QuickBooks authorization code can only be used once and expires after 10 minutes.")
            
            with st.expander("Why does this happen?"):
                st.markdown("""
                ### Common reasons for 'Invalid authorization code' errors
                
                1. **Code already used**: The authorization code was already exchanged for tokens
                2. **Code expired**: More than 10 minutes passed since the code was issued
                3. **Browser issue**: Your browser may have made multiple requests with the same code
                
                Our new OAuth server should help prevent these issues in most cases!
                """)
        
        # Options to try again or continue
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Try Again", key="error_try_again"):
                # Clear query params before getting a new auth URL
                st.query_params.clear()
                st.rerun()
        
        with col2:
            if st.button("Continue Without QuickBooks", key="error_continue"):
                st.query_params.clear()
                st.rerun()
        st.stop()
    
    # Initialize settings update flags
    material_settings_updated = False
    machine_settings_updated = False
    labor_settings_updated = False
    
    # Custom CSS for iOS/iCloud-inspired design
    st.markdown("""
    <style>
    /* Main container and overall styles */
    .main {
        background-color: #ffecc6;
        background-image: linear-gradient(135deg, #ffecc6 0%, #ffac4b 100%);
        padding: 20px;
        border-radius: 10px;
    }
    
    /* Header styling */
    h1, h2, h3 {
        color: #3a1d0d;
        font-weight: 700;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    
    h1 {
        font-size: 3rem;
        margin-bottom: 1.5rem;
        font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    
    /* Card styling */
    div.stCard {
        border-radius: 15px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        padding: 20px;
        margin-bottom: 20px;
        background-color: #fff9f0;
        border: none;
    }
    
    /* Input fields */
    div.stTextInput > div > div > input {
        border-radius: 10px;
        border: 1px solid #fcd587;
        padding: 10px 15px;
        background-color: #fff9f0;
    }
    
    div.stSelectbox > div > div > div {
        border-radius: 10px;
        border: 1px solid #fcd587;
    }
    
    /* Button styling */
    .stButton > button {
        border-radius: 10px;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        transition: all 0.2s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
    }
    
    /* Metric display */
    div.stMetric {
        background-color: #fff9f0;
        padding: 15px;
        border-radius: 12px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
        margin-bottom: 10px;
    }
    
    div.stMetric > div {
        align-items: center;
    }
    
    div.stMetric label {
        font-weight: 600;
        color: #3a1d0d;
    }
    
    /* File uploader */
    .stUploader {
        border: 2px dashed #f3770c;
        border-radius: 15px;
        padding: 20px;
        background-color: #fff9f0;
        text-align: center;
    }
    
    /* Tab styling */
    button.stTab {
        font-weight: 600;
        border-radius: 10px 10px 0 0;
        padding: 10px 20px;
    }
    
    button.stTab[aria-selected="true"] {
        background-color: #fff9f0;
        border-bottom: 3px solid #f3770c;
    }
    
    div.stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    
    /* Expander styling */
    .stExpander {
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
    }
    
    /* Progress bar */
    div.stProgress > div > div {
        border-radius: 10px;
    }
    
    /* Slider adjustments */
    div.stSlider {
        padding-top: 10px;
        padding-bottom: 10px;
    }
    
    /* Images */
    .stImage img {
        border-radius: 10px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("Embroidery Quoting Tool")
    
    # Tabs for New Quote and History
    tab1, tab2, tab3 = st.tabs(["Create Quote", "Quote History", "Admin Settings"])
    
    with tab1:
        # Step 1: File Upload or Manual Entry Section
        st.markdown('<h2 style="font-family: \'Helvetica Neue Bold\', \'Helvetica Neue\', Helvetica, Arial, sans-serif; color: #3a1d0d;">Step 1: Choose Design Source</h2>', unsafe_allow_html=True)
        
        # Simple toggle for entry method
        entry_method = st.radio(
            "Select entry method",
            ["📄 Upload Design File", "✏️ Manual Entry"],
            horizontal=True,
            help="Choose whether to upload a design file or enter stitch count manually",
            format_func=lambda x: x.split(" ", 1)[1]  # Remove the emoji for display (but keep for selection)
        )
        
        # Map the simplified options back to the original format
        if entry_method == "📄 Upload Design File":
            entry_method = "Upload Design File"
        elif entry_method == "✏️ Manual Entry":
            entry_method = "Manual Entry (No Design File)"
        
        if entry_method == "Upload Design File":
            # File uploader with custom styling
            st.markdown("""
            <style>
            .uploadFile {
                background-color: #ffecc6; 
                background-image: linear-gradient(120deg, #ffecc6 0%, #fcd587 100%);
                border-radius: 15px !important;
                padding: 10px !important;
                margin-bottom: 10px !important;
            }
            .uploadFile div {
                background-color: transparent !important;
            }
            </style>
            """, unsafe_allow_html=True)
            
            uploaded_file = st.file_uploader("Upload DST File", type=["dst", "u01"],
                                         help="Upload your embroidery design file in DST or U01 format",
                                         key="file_uploader")
        else:
            # Manual entry form
            st.markdown("""
            <div style="
                background-color: #fff9f0;
                border: 1px solid #f3770c;
                border-radius: 15px;
                padding: 20px;
                margin-bottom: 20px;
            ">
                <h4 style="color: #3a1d0d; margin-top: 0;">Manual Stitch Information</h4>
                <p style="color: #8b6c55; font-size: 14px;">Enter stitch information manually if you don't have a design file.</p>
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                manual_stitch_count = st.number_input("Stitch Count", min_value=1, value=5000, step=100)
                manual_colors = st.number_input("Number of Colors", min_value=1, value=3)
            
            with col2:
                manual_width = st.number_input("Design Width (inches)", min_value=0.1, value=4.0, step=0.1)
                manual_height = st.number_input("Design Height (inches)", min_value=0.1, value=4.0, step=0.1)
            
            manual_complexity = st.slider("Design Complexity", min_value=0, max_value=100, value=50,
                                       help="Estimate of design complexity (0 = simple, 100 = complex)")
            
            # Create a design_info dict for manual entry
            if entry_method == "Manual Entry (No Design File)":
                # Calculate thread consumption for manual entry
                thread_length_meters = manual_stitch_count * 0.0048  # 4.8 meters per 1000 stitches
                thread_length_yards = thread_length_meters * 1.09361
                
                # Estimate bobbin thread consumption (typically about 1/3 of top thread)
                bobbin_length_meters = thread_length_meters / 3
                bobbin_length_yards = bobbin_length_meters * 1.09361
                
                st.session_state.design_info = {
                    "stitch_count": manual_stitch_count,
                    "color_changes": manual_colors,
                    "width_inches": manual_width,
                    "height_inches": manual_height,
                    "width_mm": manual_width * 25.4,
                    "height_mm": manual_height * 25.4,
                    "complexity_score": manual_complexity,
                    "thread_length_yards": thread_length_yards,
                    "thread_length_meters": thread_length_meters,
                    "bobbin_length_yards": bobbin_length_yards,
                    "bobbin_length_meters": bobbin_length_meters,
                    "pattern": None  # No pattern for manual entry
                }
        
        uploaded_file = None  # Initialize to avoid "possibly unbound" error
        
        if entry_method == "Upload Design File" and 'file_uploader' in st.session_state:
            uploaded_file = st.session_state.file_uploader
            
        if uploaded_file:
            # Parse the file and save in session state
            with st.spinner("Analyzing design file..."):
                st.session_state.design_info = parse_embroidery_file(uploaded_file)
        
        # Display design information in an expandable section
        if 'design_info' in st.session_state and st.session_state.design_info:
            with st.expander("Design Information", expanded=True):
                col1, col2 = st.columns([1, 1])
                
                # Basic design metrics
                with col1:
                    st.metric("Stitch Count", f"{st.session_state.design_info['stitch_count']:,}")
                    
                    # Top thread information
                    thread_yards = st.session_state.design_info['thread_length_yards']
                    thread_meters = st.session_state.design_info.get('thread_length_meters', thread_yards * 0.9144)
                    st.metric("Top Thread", f"{thread_yards:.2f} yards ({thread_meters:.2f} meters)")
                    
                    # Bobbin thread information
                    bobbin_yards = st.session_state.design_info.get('bobbin_length_yards', thread_yards * 0.33)
                    bobbin_meters = st.session_state.design_info.get('bobbin_length_meters', bobbin_yards * 0.9144)
                    st.metric("Bobbin Thread", f"{bobbin_yards:.2f} yards ({bobbin_meters:.2f} meters)")
                    
                    st.metric("Colors", f"{st.session_state.design_info['color_changes']}")
                    st.metric("Dimensions", 
                            f"{st.session_state.design_info['width_inches']:.2f}\" × {st.session_state.design_info['height_inches']:.2f}\" " +
                            f"({st.session_state.design_info['width_mm']:.1f}mm × {st.session_state.design_info['height_mm']:.1f}mm)")
                    
                    # Complexity score with visual indicator
                    complexity = st.session_state.design_info['complexity_score']
                    st.write("Design Complexity")
                    st.progress(complexity/100)
                    
                    if complexity < 30:
                        complexity_text = "Low complexity (quick, simple design)"
                    elif complexity < 70:
                        complexity_text = "Medium complexity"
                    else:
                        complexity_text = "High complexity (detailed, time-intensive)"
                    st.caption(complexity_text)
                
                # Design preview (only for uploaded files, not manual entry)
                with col2:
                    if st.session_state.design_info["pattern"] is not None:
                        # Checkbox for foam preview (default to 'use_foam' value if it exists in session state)
                        if 'use_foam' in st.session_state:
                            preview_with_foam = st.checkbox("Preview with 3D foam margin", value=st.session_state.use_foam)
                        else:
                            preview_with_foam = st.checkbox("Preview with 3D foam margin", value=False)
                        
                        # If preview_with_foam is checked, also update the 'use_foam' checkbox later in the form
                        if preview_with_foam:
                            st.session_state.use_foam = True
                        
                        # Generate and display preview
                        preview_img = render_design_preview(
                            st.session_state.design_info["pattern"], 
                            width=400, 
                            height=400, 
                            use_foam=preview_with_foam
                        )
                        st.image(preview_img, caption="Design Preview", use_container_width=True)
                    else:
                        # Show placeholder for manual entry
                        st.markdown("""
                        <div style="
                            background-color: #f8f8f8;
                            border: 1px dashed #ddd;
                            border-radius: 10px;
                            padding: 30px;
                            text-align: center;
                            height: 250px;
                            display: flex;
                            flex-direction: column;
                            justify-content: center;
                            align-items: center;
                        ">
                            <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M13 7h-2v2h2V7zm0 4h-2v6h2v-6zm-1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z" fill="#ccc"/>
                            </svg>
                            <p style="color: #888; margin-top: 15px;">No design preview available for manual entry</p>
                        </div>
                        """, unsafe_allow_html=True)
        
        # Step 2: Job Information & Materials
        st.markdown('<h2 style="font-family: \'Helvetica Neue Bold\', \'Helvetica Neue\', Helvetica, Arial, sans-serif; color: #3a1d0d;">Step 2: Job Information & Materials</h2>', unsafe_allow_html=True)
        
        # Job Info Card with enhanced styling
        st.markdown("""
        <div style="
            background-color: #ffecc6; 
            background-image: linear-gradient(120deg, #ffecc6 0%, #fcd587 100%);
            padding: 10px 15px;
            border-radius: 15px;
            margin-bottom: 5px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        ">
            <h3 style="margin: 0; color: #3a1d0d; font-weight: 700; font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif;">Job Information</h3>
        </div>
        """, unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        
        with col1:
            job_name = st.text_input("Job Name/Reference (Optional)", 
                                   help="A name to identify this quote (project name, etc.)")
            customer_name = st.text_input("Customer Name (Optional)",
                                      help="Name of the customer for this order")
            quantity = st.number_input("Quantity", min_value=1, value=50, 
                                    help="Number of pieces to be embroidered")
        
        with col2:
            garment_type = st.selectbox("Garment Type", 
                                      ["T-Shirt", "Polo", "Hat/Cap", "Jacket", "Sweatshirt", "Other"],
                                      help="Type of garment being embroidered")
            fabric_type = st.selectbox("Fabric Type", 
                                     ["Cotton", "Polyester", "Blend", "Performance/Athletic", "Canvas", "Denim", "Other"],
                                     help="Type of fabric - helps determine stabilizer requirements")
        
        placement = st.text_input("Placement/Other Notes (Optional)", 
                               placeholder="e.g., Left Chest, Cap Front, etc.",
                               help="Where the design will be placed on the garment")
        
        # Technical Settings Card with enhanced styling
        st.markdown("""
        <div style="
            background-color: #ffecc6; 
            background-image: linear-gradient(120deg, #ffecc6 0%, #fcd587 100%);
            padding: 10px 15px;
            border-radius: 15px;
            margin-bottom: 5px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        ">
            <h3 style="margin: 0; color: #3a1d0d; font-weight: 700; font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif;">Machine & Technical Settings</h3>
        </div>
        """
        , unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Ensure all slider values are integers
            max_heads = int(float(DEFAULT_MAX_HEADS))
            
            # Default active heads based on quantity
            if 'quantity' in locals():
                default_heads = min(quantity, max_heads) if quantity < 15 else max_heads
            else:
                default_heads = min(4, max_heads)
                
            active_heads = st.slider("Machine Heads", 1, max_heads, default_heads, 
                                  help="Number of embroidery heads that will run simultaneously")
            
            # Store previous state for comparison
            prev_coloreel_enabled = st.session_state.get('coloreel_enabled', False)
            
            # Coloreel ITCU checkbox
            coloreel_enabled = st.checkbox("Use Coloreel ITCU", value=prev_coloreel_enabled,
                                       help="Enable if using Coloreel instant thread coloring technology",
                                       key='coloreel_checkbox')
            
            # Update session state
            st.session_state.coloreel_enabled = coloreel_enabled
            
            # Complex production checkbox - auto-check if Coloreel is enabled
            prev_complex_production = st.session_state.get('complex_production', False)
            complex_production_default = coloreel_enabled or prev_complex_production
            
            complex_production = st.checkbox("Complex Production", 
                                         value=complex_production_default,
                                         help="Enable for complex designs that require slower stitching and additional attention",
                                         key='complex_production_checkbox')
            
            # Update session state
            st.session_state.complex_production = complex_production
            
            # Ensure complex production is enabled if Coloreel is enabled
            if coloreel_enabled and not complex_production:
                complex_production = True
                st.session_state.complex_production = True
            
            # Custom productivity rate slider
            custom_productivity_rate = None
            
            # Show productivity slider for either Coloreel or complex production
            if complex_production or coloreel_enabled:
                min_rate = 0.2  # 20% efficiency
                max_rate = 1.0  # 100% efficiency
                step = 0.05
                
                # Set different default values depending on which option is selected
                if coloreel_enabled:
                    default_rate = float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE)
                    slider_key = 'coloreel_productivity_slider'
                    slider_label = "Coloreel Productivity Rate"
                else:
                    default_rate = float(DEFAULT_COMPLEX_PRODUCTIVITY_RATE)
                    slider_key = 'complex_productivity_slider'
                    slider_label = "Productivity Rate"
                
                # Use previous value from session state if available
                prev_rate = st.session_state.get(slider_key, default_rate)
                
                custom_productivity_rate = st.slider(
                    slider_label, 
                    min_value=min_rate,
                    max_value=max_rate,
                    value=prev_rate,
                    step=step,
                    format="%.2f",
                    key=slider_key,
                    help="Adjust the productivity rate (lower values = slower production)"
                )
                
                # No need to manually update session state - Streamlit does this automatically
                
                if coloreel_enabled:
                    st.caption(f"Coloreel Efficiency: {int(custom_productivity_rate * 100)}% (default suggestion: {int(float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE) * 100)}%)")
                else:
                    st.caption(f"Production Efficiency: {int(custom_productivity_rate * 100)}%")
            
            # Simplified buffer time info
            buffer_minutes = float(DEFAULT_BUFFER_MINUTES)
            buffer_percentage = float(DEFAULT_BUFFER_PERCENTAGE)
            
            st.info(f"Buffer time: {buffer_minutes:.1f} minutes + {buffer_percentage:.1f}% runtime (set in Admin Settings)")
            
            # Apply head limitations for Coloreel
            coloreel_max_heads = int(DEFAULT_COLOREEL_MAX_HEADS)
            if coloreel_enabled and active_heads > coloreel_max_heads:
                active_heads = coloreel_max_heads
                # Use custom HTML for a brighter yellow warning that's more visible on warm background
                st.markdown(f"""
                <div style="background-color: #FFF2CC; border-left: 4px solid #FFD700; color: #775500; padding: 10px; border-radius: 10px; margin: 10px 0; font-weight: 500;">
                    ⚠️ Max heads limited to {coloreel_max_heads} with Coloreel enabled
                </div>
                """, unsafe_allow_html=True)
                
            # Calculate the final productivity rate based on all settings
            if not complex_production:
                productivity_rate = float(DEFAULT_PRODUCTIVITY_RATE)
            elif custom_productivity_rate is not None:
                # Use the custom productivity rate (which may come from either the Coloreel or complex slider)
                productivity_rate = custom_productivity_rate
            else:
                # Fallback to defaults if somehow no slider was shown
                if coloreel_enabled:
                    productivity_rate = float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE)
                else:
                    productivity_rate = float(DEFAULT_COMPLEX_PRODUCTIVITY_RATE)
        
        with col2:
            thread_weight = st.selectbox("Thread Weight", 
                                       ["40wt", "60wt"],
                                       help="Thread weight affects stitch quality and machine speed")
            
            # Auto-suggest hoop size based on design dimensions if available
            hoop_sizes = ["4\" Round", "5.5\" Round", "8\" Round", "12\" Round", "15\" Round", "Cap Frame"]
            default_hoop_index = 0
            
            if st.session_state.design_info:
                width = st.session_state.design_info["width_inches"]
                height = st.session_state.design_info["height_inches"]
                max_dimension = max(width, height)
                
                if max_dimension <= 3.5:
                    default_hoop_index = 0  # 4" hoop
                elif max_dimension <= 5:
                    default_hoop_index = 1  # 5.5" hoop
                elif max_dimension <= 7.5:
                    default_hoop_index = 2  # 8" hoop
                elif max_dimension <= 11.5:
                    default_hoop_index = 3  # 12" hoop
                else:
                    default_hoop_index = 4  # 15" hoop
                
                if garment_type == "Hat/Cap":
                    default_hoop_index = 5  # Cap frame
            
            hoop_size = st.selectbox("Hoop Size", hoop_sizes, index=default_hoop_index,
                                   help="Select the hoop size that best fits the design")
        
        with col3:
            # Auto-fill color count from the design if available
            default_colors = 1
            if st.session_state.design_info:
                default_colors = st.session_state.design_info["color_changes"]
            
            color_count = st.number_input("Number of Colors", min_value=1, value=default_colors,
                                       help="Number of thread colors used in the design")
            
            # Link stabilizer to fabric type
            stabilizer_map = {
                "Cotton": "Cutaway",
                "Polyester": "Cutaway",
                "Blend": "Cutaway",
                "Performance/Athletic": "Cutaway",
                "Canvas": "Tearaway",
                "Denim": "Tearaway",
                "Other": "Cutaway"
            }
            
            default_stabilizer = stabilizer_map.get(fabric_type, "Cutaway")
            stabilizer_type = st.selectbox("Stabilizer Type", 
                                         ["Cutaway", "Tearaway", "Water Soluble", "Heat Away", "None"],
                                         index=["Cutaway", "Tearaway", "Water Soluble", "Heat Away", "None"].index(default_stabilizer),
                                         help="Type of backing used to stabilize the fabric during embroidery")
        
        # Use the session state value if it exists, otherwise default to False
        default_foam_value = st.session_state.get('use_foam', False)
        use_foam = st.checkbox("Use 3D Foam", value=default_foam_value,
                             help="Check if using 3D foam for raised embroidery effect")
        
        # Update session state to keep in sync with preview checkbox
        st.session_state.use_foam = use_foam
        
        # Pricing Information Card with enhanced styling
        st.markdown("""
        <div style="
            background-color: #ffecc6; 
            background-image: linear-gradient(120deg, #ffecc6 0%, #fcd587 100%);
            padding: 10px 15px;
            border-radius: 15px;
            margin-bottom: 5px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        ">
            <h3 style="margin: 0; color: #3a1d0d; font-weight: 700; font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif;">Pricing Information</h3>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            markup_percentage = st.slider("Markup Percentage", 0, 200, 40,
                                      help="Profit margin percentage to add to direct costs")
            
            # Show digitizing fee input if complex production is enabled
            digitizing_fee = 0.0
            if complex_production:
                digitizing_fee = st.number_input("Digitizing Fee ($)", 
                                             min_value=0.0, 
                                             value=float(DEFAULT_DIGITIZING_FEE), 
                                             step=5.0,
                                             help="Fee for digitizing complex designs")
            
            # Labor worker selection
            workers = database.get_labor_workers()
            active_workers = [w for w in workers if w['is_active']]
            
            if active_workers:
                st.markdown("""
                <div style="margin-top: 20px;">
                    <h4 style="font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #3a1d0d; margin-bottom: 8px;">
                        Active Labor Workers
                    </h4>
                </div>
                """, unsafe_allow_html=True)
                
                # Display active workers with checkboxes - without showing hourly rates
                selected_workers = []
                for worker in active_workers:
                    is_selected = st.checkbox(
                        f"{worker['name']}", 
                        value=True,
                        key=f"worker_select_{worker['id']}"
                    )
                    if is_selected:
                        selected_workers.append(worker)
                
                # Option to show all workers
                if len(workers) > len(active_workers):
                    with st.expander("Show All Workers"):
                        inactive_workers = [w for w in workers if not w['is_active']]
                        for worker in inactive_workers:
                            is_selected = st.checkbox(
                                f"{worker['name']}", 
                                value=False,
                                key=f"worker_select_{worker['id']}"
                            )
                            if is_selected:
                                selected_workers.append(worker)
        
        with col2:
            setup_fee = st.number_input("Setup Fee ($)", 
                                    min_value=0.0, 
                                    value=0.0, 
                                    step=5.0,
                                    help="One-time fee for setup, etc.")
        
        # Calculate Button with enhanced styling
        st.markdown("""
        <style>
        .calculate-button {
            background: linear-gradient(90deg, #f3770c 0%, #f5993c 100%);
            color: white;
            font-weight: bold;
            padding: 0.75rem 1.5rem;
            font-size: 1.1rem;
            border: none;
            border-radius: 15px;
            box-shadow: 0 4px 10px rgba(243, 119, 12, 0.3);
            margin-top: 1rem;
            cursor: pointer;
            transition: all 0.3s ease;
            width: 100%;
            text-align: center;
        }
        .calculate-button:hover {
            box-shadow: 0 6px 15px rgba(243, 119, 12, 0.4);
            transform: translateY(-2px);
        }
        </style>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            calculate_pressed = st.button("Calculate Quote", type="primary", key="calculate_button")
        
        if calculate_pressed and 'design_info' in st.session_state:
            # Gather all inputs
            job_inputs = {
                "job_name": job_name,
                "customer_name": customer_name,
                "quantity": quantity,
                "garment_type": garment_type,
                "fabric_type": fabric_type,
                "placement": placement,
                "active_heads": active_heads,
                "coloreel_enabled": coloreel_enabled,
                "complex_production": complex_production,
                "thread_weight": thread_weight,
                "hoop_size": hoop_size,
                "color_count": color_count,
                "stabilizer_type": stabilizer_type,
                "use_foam": use_foam,
                "markup_percentage": markup_percentage,
                "setup_fee": setup_fee,
                "digitizing_fee": digitizing_fee if 'digitizing_fee' in locals() else 0.0,
                "custom_productivity_rate": custom_productivity_rate if 'custom_productivity_rate' in locals() and custom_productivity_rate is not None else None,
                "selected_workers": selected_workers if 'selected_workers' in locals() else [],
                # Add buffer time settings
                "buffer_minutes": buffer_minutes if 'buffer_minutes' in locals() else float(DEFAULT_BUFFER_MINUTES),
                "buffer_percentage": buffer_percentage if 'buffer_percentage' in locals() else float(DEFAULT_BUFFER_PERCENTAGE)
            }
            
            # Calculate all costs
            with st.spinner("Calculating costs..."):
                cost_results = calculate_costs(st.session_state.design_info, job_inputs)
            
            # Save to history
            if st.session_state.design_info is not None:
                design_info_copy = st.session_state.design_info.copy()
            else:
                design_info_copy = {}
                
            history_entry = {
                "timestamp": datetime.datetime.now(),
                "job_name": job_name if job_name else f"Quote {len(st.session_state.history) + 1}",
                "design_info": design_info_copy,
                "job_inputs": job_inputs.copy(),
                "cost_results": cost_results.copy()
            }
            st.session_state.history.append(history_entry)
            
            # Save to database
            quote_data = {
                "job_name": job_name if job_name else f"Quote {len(st.session_state.history)}",
                "customer_name": job_inputs.get("customer_name", ""),
                "stitch_count": st.session_state.design_info["stitch_count"],
                "color_count": job_inputs["color_count"],
                "quantity": job_inputs["quantity"],
                "width_inches": st.session_state.design_info["width_inches"],
                "height_inches": st.session_state.design_info["height_inches"],
                "total_cost": cost_results["total_job_cost"],
                "price_per_piece": cost_results["price_per_piece"]
            }
            database.save_quote(quote_data)
            
            # Display Results with enhanced styling
            st.markdown("""
            <div style="
                background-color: #f3770c; 
                background-image: linear-gradient(135deg, #f3770c 0%, #fcd587 100%);
                padding: 15px 20px;
                border-radius: 15px;
                margin-top: 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 12px rgba(243, 119, 12, 0.2);
                text-align: center;
            ">
                <h2 style="margin: 0; color: white; font-weight: 700; font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif; text-shadow: 0 1px 2px rgba(0,0,0,0.1);">Quote Results</h2>
            </div>
            """, unsafe_allow_html=True)
            
            # Custom CSS for metrics
            st.markdown("""
            <style>
            .metric-card {
                background-color: #fff9f0;
                border-radius: 15px;
                padding: 1rem;
                margin-bottom: 1rem;
                box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
                border-left: 4px solid #f3770c;
                transition: transform 0.2s ease, box-shadow 0.2s ease;
            }
            .metric-card:hover {
                transform: translateY(-3px);
                box-shadow: 0 6px 14px rgba(0, 0, 0, 0.08);
            }
            .metric-label {
                font-size: 0.9rem;
                color: #8b6c55;
                margin-bottom: 0.3rem;
                font-weight: 500;
            }
            .metric-value {
                font-size: 1.6rem;
                color: #3a1d0d;
                font-weight: 700;
                margin: 0;
            }
            </style>
            """, unsafe_allow_html=True)
            
            # Summary cards with custom styling
            col1, col2 = st.columns(2)
            
            with col1:
                # Total Job Cost - Highlight as most important
                st.markdown(f"""
                <div class="metric-card" style="border-left: 4px solid #f3770c; background-color: #fff2dd;">
                    <div class="metric-label">Total Job Cost</div>
                    <div class="metric-value">${cost_results['total_job_cost']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Price Per Piece
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Price Per Piece</div>
                    <div class="metric-value">${cost_results['price_per_piece']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Production Time
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Production Time</div>
                    <div class="metric-value">{cost_results['production_time_hours']:.2f} hours</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                # Material Cost
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Material Cost</div>
                    <div class="metric-value">${cost_results['material_cost']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Labor Cost
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Labor Cost</div>
                    <div class="metric-value">${cost_results['labor_cost']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Profit Margin
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Profit Margin</div>
                    <div class="metric-value">${cost_results['profit_margin']:.2f} ({markup_percentage}%)</div>
                </div>
                """, unsafe_allow_html=True)
            
            # Detailed breakdown in expander
            with st.expander("Detailed Cost Breakdown"):
                st.subheader("Materials")
                materials_col1, materials_col2 = st.columns(2)
                
                with materials_col1:
                    st.metric("Thread Cost", f"${cost_results['thread_cost']:.2f}")
                    st.metric("Bobbin Cost", f"${cost_results['bobbin_cost']:.2f}")
                
                with materials_col2:
                    st.metric("Stabilizer Cost", f"${cost_results['stabilizer_cost']:.2f}")
                    if use_foam:
                        st.metric("Foam Cost", f"${cost_results['foam_cost']:.2f}")
                
                st.subheader("Production Details")
                production_col1, production_col2, production_col3 = st.columns(3)
                
                with production_col1:
                    st.metric("Runs Needed", str(cost_results['runs_needed']))
                    st.metric("Spools Required", str(cost_results['spools_required']))
                
                with production_col2:
                    st.metric("Bobbins Required", f"{cost_results['bobbins_required']:.1f}")
                    st.metric("Setup Fee", f"${cost_results['setup_fee']:.2f}")
                    
                    # Show digitizing fee if applicable
                    if job_inputs.get("complex_production", False) and cost_results.get("digitizing_fee", 0) > 0:
                        st.metric("Digitizing Fee", f"${cost_results['digitizing_fee']:.2f}")
                
                with production_col3:
                    # Show buffer time details
                    st.metric("Production Time", f"{cost_results['piece_production_time']:.1f} min per piece")
                    st.metric("Buffer Time", f"{cost_results['buffer_time_minutes']:.1f} min ({cost_results['buffer_minutes_per_run']:.1f}min + {cost_results['buffer_percentage']:.1f}%)")
                    st.metric("Total Production Time", f"{cost_results['production_time_hours']:.2f} hours")
                
                # Display labor workers if any are selected
                if "worker_info" in cost_results and cost_results["worker_info"]:
                    st.subheader("Labor Information")
                    
                    # Create a simple table to display worker information without showing rates
                    worker_data = {
                        "Workers Assigned": [w["name"] for w in cost_results["worker_info"]]
                    }
                    
                    worker_df = pd.DataFrame(worker_data)
                    st.dataframe(worker_df, use_container_width=True)
            
            # Generate PDFs
            detailed_pdf = generate_detailed_quote_pdf(st.session_state.design_info, job_inputs, cost_results)
            customer_pdf = generate_customer_quote_pdf(st.session_state.design_info, job_inputs, cost_results)
            
            # Download buttons with enhanced styling
            st.markdown("""
            <div style="
                background-color: #ffecc6; 
                background-image: linear-gradient(120deg, #ffecc6 0%, #fcd587 100%);
                padding: 10px 15px;
                border-radius: 15px;
                margin: 20px 0 10px 0;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
            ">
                <h3 style="margin: 0; color: #3a1d0d; font-weight: 700; font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif;">Download Quotes</h3>
            </div>
            """, unsafe_allow_html=True)
            
            # Custom CSS for download buttons
            st.markdown("""
            <style>
            .download-button {
                display: block;
                background: linear-gradient(90deg, #f3770c 0%, #f5993c 100%);
                color: white;
                font-weight: 600;
                text-align: center;
                padding: 12px 20px;
                margin: 10px 5px;
                border-radius: 15px;
                box-shadow: 0 4px 10px rgba(243, 119, 12, 0.3);
                text-decoration: none;
                transition: all 0.3s ease;
                font-family: 'Helvetica Neue Bold', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            }
            .download-button:hover {
                box-shadow: 0 6px 15px rgba(243, 119, 12, 0.4);
                transform: translateY(-2px);
                background: linear-gradient(90deg, #f5993c 0%, #f3770c 100%);
            }
            .download-button svg {
                vertical-align: middle;
                margin-right: 10px;
            }
            </style>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            internal_filename = f"internal_quote_{job_name}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf"
            customer_filename = f"customer_quote_{job_name}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf"
            
            with col1:
                st.markdown(f'''
                <a href="data:application/pdf;base64,{base64.b64encode(detailed_pdf.getvalue()).decode()}" 
                   download="{internal_filename}" 
                   class="download-button">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="white" viewBox="0 0 16 16">
                        <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
                        <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>
                    </svg>
                    <span style="color: white;">Internal Quote PDF</span>
                </a>
                ''', unsafe_allow_html=True)
            
            with col2:
                st.markdown(f'''
                <a href="data:application/pdf;base64,{base64.b64encode(customer_pdf.getvalue()).decode()}" 
                   download="{customer_filename}" 
                   class="download-button">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="white" viewBox="0 0 16 16">
                        <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
                        <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>
                    </svg>
                    <span style="color: white;">Customer Quote PDF</span>
                </a>
                ''', unsafe_allow_html=True)
            
            # Add QuickBooks Export Option
            if QUICKBOOKS_AVAILABLE:
                st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
                
                # Check if QuickBooks is authenticated
                is_authenticated, auth_message = database.get_quickbooks_auth_status()
                
                if is_authenticated:
                    # Create the QuickBooks export button to match the download buttons
                    # Create a dedicated container for the QuickBooks export
                    export_container = st.container()
                    
                    # Track export status without using rerun
                    if 'qb_last_export_status' not in st.session_state:
                        st.session_state.qb_last_export_status = None
                    
                    # Display the export status if available
                    if st.session_state.qb_last_export_status:
                        success, message = st.session_state.qb_last_export_status
                        if success:
                            export_container.success(f"Successfully exported to QuickBooks: {message}")
                        else:
                            export_container.error(f"Failed to export to QuickBooks: {message}")
                    
                    # Create the Export button in a more isolated way to prevent state changes
                    # We'll keep this in its own column to prevent UI shifts
                    export_col1, export_col2 = export_container.columns([2, 1])
                    
                    # Status messages will go in column 1
                    status_placeholder = export_col1.empty()
                    
                    # The button will go in column 2 
                    export_clicked = export_col2.button(
                        "Export to QuickBooks", 
                        help="Create an estimate in QuickBooks based on this quote. After export, you can find it in Sales > Estimates in your QuickBooks account.",
                        key="export_to_qb_button",
                        use_container_width=True,
                        type="primary",
                        on_click=None  # No callback - we'll handle the click directly
                    )
                    
                    # Process the export ONLY if button is clicked
                    if export_clicked:
                        # Show status in the placeholder
                        status_placeholder.info("Starting QuickBooks export...")
                        
                        try:
                            # Safely make copies of all required data
                            import copy
                            if 'design_info' in st.session_state and st.session_state.design_info:
                                # Use deep copying to ensure we preserve all data
                                export_design_info = copy.deepcopy(st.session_state.design_info)
                                export_job_inputs = copy.deepcopy(job_inputs)
                                export_cost_results = copy.deepcopy(cost_results)
                                
                                # Update placeholder with progress
                                status_placeholder.info("Exporting to QuickBooks... (this may take a moment)")
                                
                                # Export to QuickBooks (this will be logged extensively)
                                success, message, estimate_id, estimate_url = export_to_quickbooks(
                                    export_design_info, 
                                    export_job_inputs, 
                                    export_cost_results
                                )
                                
                                # Store the result without refreshing the page
                                st.session_state.qb_last_export_status = (success, message, estimate_id, estimate_url)
                                
                                # Update the UI with the result (no page refresh)
                                if success:
                                    # We already have estimate_id and estimate_url directly from the function
                                    # Show success with a clickable link
                                    status_placeholder.success(f"Successfully exported to QuickBooks: {message}")
                                    
                                    # If we have a URL to link to, add a more attractive button-style link
                                    if estimate_url:
                                        # Create an improved QuickBooks link experience
                                        status_placeholder.markdown(f"""
                                        <div style="display: flex; flex-direction: column; align-items: center; margin: 15px 0;">
                                            <p style="margin-bottom: 10px; font-weight: bold;">Your estimate is ready to view in QuickBooks!</p>
                                            <a href="{estimate_url}" target="_blank" rel="noopener noreferrer" style="
                                                display: inline-flex;
                                                align-items: center;
                                                background: linear-gradient(90deg, #00A09D 0%, #00BAAC 100%);
                                                color: white;
                                                padding: 10px 20px;
                                                border-radius: 8px;
                                                text-decoration: none;
                                                font-weight: bold;
                                                margin-top: 5px;
                                                box-shadow: 0px 3px 6px rgba(0,0,0,0.2);
                                                transition: all 0.2s ease;
                                            ">
                                                <span style="margin-right: 8px;">View in QuickBooks</span>
                                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                                    <polyline points="15 3 21 3 21 9"></polyline>
                                                    <line x1="10" y1="14" x2="21" y2="3"></line>
                                                </svg>
                                            </a>
                                            <p style="margin-top: 10px; font-size: 0.8em; color: #666;">Note: It may take a few moments for the estimate to appear in QuickBooks. The estimate will open in a new tab while your quote remains visible here.</p>
                                            
                                            <div style="margin-top: 15px; border-top: 1px solid #eee; padding-top: 15px; width: 100%; text-align: center;">
                                                <p style="font-size: 0.9em; color: #555;">
                                                    Find your estimate in QuickBooks Online under:<br/>
                                                    <strong>Sales > Estimates</strong>
                                                </p>
                                            </div>
                                        </div>
                                        """, unsafe_allow_html=True)
                                else:
                                    status_placeholder.error(f"Failed to export to QuickBooks: {message}")
                            else:
                                status_placeholder.error("Design information not available. Please recalculate the quote.")
                                st.session_state.qb_last_export_status = (False, "Design information not available")
                        except Exception as e:
                            # Capture detailed error information
                            import traceback
                            error_trace = traceback.format_exc()
                            print(f"EXPORT ERROR: {str(e)}\n{error_trace}")
                            
                            # Update UI with error
                            status_placeholder.error(f"Error during QuickBooks export: {str(e)}")
                            with status_placeholder.expander("Error Details"):
                                st.code(error_trace)
                                
                            # Store error status
                            st.session_state.qb_last_export_status = (False, f"Error: {str(e)}")
                else:
                    st.warning(f"QuickBooks integration not available: {auth_message}. Please configure in Admin settings.")
        
        elif calculate_pressed and ('design_info' not in st.session_state or not st.session_state.design_info):
            st.error("Please upload a design file or complete the manual entry form to generate a quote.")
    
    # History Tab
    with tab2:
        st.header("Quote History")
        
        if not st.session_state.history:
            st.info("No quote history yet. Create quotes in the 'Create Quote' tab to see them here.")
        else:
            for i, entry in enumerate(reversed(st.session_state.history)):
                with st.expander(f"{entry['job_name']} - {entry['timestamp'].strftime('%Y-%m-%d %H:%M')}"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**Job Details**")
                        st.write(f"Customer: {entry['job_inputs'].get('customer_name', '')}")
                        st.write(f"Quantity: {entry['job_inputs']['quantity']}")
                        st.write(f"Garment: {entry['job_inputs']['garment_type']}")
                        st.write(f"Stitch Count: {entry['design_info']['stitch_count']:,}")
                    
                    with col2:
                        st.write("**Quote Summary**")
                        st.write(f"Total Cost: ${entry['cost_results']['total_job_cost']:.2f}")
                        st.write(f"Price Per Piece: ${entry['cost_results']['price_per_piece']:.2f}")
                        st.write(f"Production Time: {entry['cost_results']['production_time_hours']:.2f} hours")
                    
                    # Regenerate PDFs for history items
                    detailed_pdf = generate_detailed_quote_pdf(entry['design_info'], entry['job_inputs'], entry['cost_results'])
                    customer_pdf = generate_customer_quote_pdf(entry['design_info'], entry['job_inputs'], entry['cost_results'])
                    
                    pdf_col1, pdf_col2 = st.columns(2)
                    
                    with pdf_col1:
                        st.markdown(
                            get_download_link(detailed_pdf, f"internal_quote_{entry['job_name']}_{entry['timestamp'].strftime('%Y%m%d')}.pdf", "Download Internal Quote PDF"),
                            unsafe_allow_html=True
                        )
                    
                    with pdf_col2:
                        st.markdown(
                            get_download_link(customer_pdf, f"customer_quote_{entry['job_name']}_{entry['timestamp'].strftime('%Y%m%d')}.pdf", "Download Customer Quote PDF"),
                            unsafe_allow_html=True
                        )
                    
                    # Add QuickBooks Export Option for history items too
                    if QUICKBOOKS_AVAILABLE:
                        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
                        
                        # Check if QuickBooks is authenticated
                        is_authenticated, auth_message = database.get_quickbooks_auth_status()
                        
                        if is_authenticated:
                            # Export to QuickBooks button for history to match download buttons
                            # Create a container for the history export
                            export_history_container = st.container()
                            
                            # Track export status without using rerun
                            history_status_key = f"qb_history_export_status_{i}"
                            if history_status_key not in st.session_state:
                                st.session_state[history_status_key] = None
                            
                            # Use columns to isolate the export button and status
                            export_hist_col1, export_hist_col2 = export_history_container.columns([2, 1])
                            
                            # Status messages will go in column 1
                            status_history_placeholder = export_hist_col1.empty()
                            
                            # Display previous export result in the status placeholder
                            if st.session_state[history_status_key]:
                                success, message, estimate_id, estimate_url = st.session_state[history_status_key]
                                if success:
                                    # Show success message
                                    status_history_placeholder.success(f"Successfully exported to QuickBooks: {message}")
                                    
                                    # If we have an estimate URL, create a styled direct link
                                    if estimate_url:
                                        
                                        # Add a styled button link with improved design
                                        status_history_placeholder.markdown(f"""
                                        <div style="display: flex; flex-direction: column; align-items: center; margin: 15px 0;">
                                            <p style="margin-bottom: 10px; font-weight: bold;">Your estimate is ready to view in QuickBooks!</p>
                                            <a href="{estimate_url}" target="_blank" rel="noopener noreferrer" style="
                                                display: inline-flex;
                                                align-items: center;
                                                background: linear-gradient(90deg, #00A09D 0%, #00BAAC 100%);
                                                color: white;
                                                padding: 10px 20px;
                                                border-radius: 8px;
                                                text-decoration: none;
                                                font-weight: bold;
                                                margin-top: 5px;
                                                box-shadow: 0px 3px 6px rgba(0,0,0,0.2);
                                                transition: all 0.2s ease;
                                            ">
                                                <span style="margin-right: 8px;">View in QuickBooks</span>
                                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                                    <polyline points="15 3 21 3 21 9"></polyline>
                                                    <line x1="10" y1="14" x2="21" y2="3"></line>
                                                </svg>
                                            </a>
                                            <p style="margin-top: 10px; font-size: 0.8em; color: #666;">Note: It may take a few moments for the estimate to appear in QuickBooks. The estimate will open in a new tab while your quote remains visible here.</p>
                                            
                                            <div style="margin-top: 15px; border-top: 1px solid #eee; padding-top: 15px; width: 100%; text-align: center;">
                                                <p style="font-size: 0.9em; color: #555;">
                                                    Find your estimate in QuickBooks Online under:<br/>
                                                    <strong>Sales > Estimates</strong>
                                                </p>
                                            </div>
                                        </div>
                                        """, unsafe_allow_html=True)
                                else:
                                    status_history_placeholder.error(f"Failed to export to QuickBooks: {message}")
                            
                            # Create the export button in column 2
                            export_history_clicked = export_hist_col2.button(
                                "Export to QuickBooks", 
                                help="Create an estimate in QuickBooks based on this quote. After export, you can find it in Sales > Estimates in your QuickBooks account.",
                                key=f"export_to_qb_button_{i}",
                                use_container_width=True,
                                type="primary"
                            )
                            
                            # Handle export when clicked - NO RERUN needed
                            if export_history_clicked:
                                # Show status in the placeholder
                                status_history_placeholder.info("Starting QuickBooks export...")
                                
                                try:
                                    # Safe copying of history item data
                                    import copy
                                    export_design_info = copy.deepcopy(entry['design_info'])
                                    export_job_inputs = copy.deepcopy(entry['job_inputs'])
                                    export_cost_results = copy.deepcopy(entry['cost_results'])
                                    
                                    # Update the placeholder
                                    status_history_placeholder.info("Exporting to QuickBooks... (this may take a moment)")
                                    
                                    # Perform the export with enhanced debugging
                                    print(f"Starting QuickBooks export for history item {i}")
                                    print(f"Job: {export_job_inputs.get('job_name', 'Unknown')}")
                                    print(f"Customer: {export_job_inputs.get('customer_name', 'Unknown')}")
                                    
                                    # Execute the export
                                    success, message, estimate_id, estimate_url = export_to_quickbooks(
                                        export_design_info, 
                                        export_job_inputs, 
                                        export_cost_results
                                    )
                                    
                                    # Store the result without refreshing
                                    st.session_state[history_status_key] = (success, message, estimate_id, estimate_url)
                                    
                                    # Update the UI with the result (no page refresh)
                                    if success:
                                        # Show success with a styled clickable link
                                        status_history_placeholder.success(f"Successfully exported to QuickBooks: {message}")
                                        
                                        # Add a more attractive button-style link if URL is provided
                                        if estimate_url:
                                            status_history_placeholder.markdown(f"""
                                            <div style="display: flex; flex-direction: column; align-items: center; margin: 15px 0;">
                                                <p style="margin-bottom: 10px; font-weight: bold;">Your estimate is ready to view in QuickBooks!</p>
                                                <a href="{estimate_url}" target="_blank" rel="noopener noreferrer" style="
                                                    display: inline-flex;
                                                    align-items: center;
                                                    background: linear-gradient(90deg, #00A09D 0%, #00BAAC 100%);
                                                    color: white;
                                                    padding: 10px 20px;
                                                    border-radius: 8px;
                                                    text-decoration: none;
                                                    font-weight: bold;
                                                    margin-top: 5px;
                                                    box-shadow: 0px 3px 6px rgba(0,0,0,0.2);
                                                    transition: all 0.2s ease;
                                                ">
                                                    <span style="margin-right: 8px;">View in QuickBooks</span>
                                                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                                        <polyline points="15 3 21 3 21 9"></polyline>
                                                        <line x1="10" y1="14" x2="21" y2="3"></line>
                                                    </svg>
                                                </a>
                                                <p style="margin-top: 10px; font-size: 0.8em; color: #666;">Note: It may take a few moments for the estimate to appear in QuickBooks. The estimate will open in a new tab while your quote remains visible here.</p>
                                                
                                                <div style="margin-top: 15px; border-top: 1px solid #eee; padding-top: 15px; width: 100%; text-align: center;">
                                                    <p style="font-size: 0.9em; color: #555;">
                                                        Find your estimate in QuickBooks Online under:<br/>
                                                        <strong>Sales > Estimates</strong>
                                                    </p>
                                                </div>
                                            </div>
                                            """, unsafe_allow_html=True)
                                    else:
                                        status_history_placeholder.error(f"Failed to export to QuickBooks: {message}")
                                    
                                except Exception as e:
                                    # Detailed error reporting
                                    import traceback
                                    error_trace = traceback.format_exc()
                                    print(f"HISTORY EXPORT ERROR: {str(e)}\n{error_trace}")
                                    
                                    # Show error in UI
                                    status_history_placeholder.error(f"Error during QuickBooks export: {str(e)}")
                                    with status_history_placeholder.expander("Error Details"):
                                        st.code(error_trace)
                                    
                                    # Store error status
                                    st.session_state[history_status_key] = (False, f"Error: {str(e)}", None, None)
    
    # Admin Settings Tab
    with tab3:
        st.header("Admin Settings")
        
        # Add password protection
        import os
        
        # Check if the session state has the admin logged in flag
        if 'admin_logged_in' not in st.session_state:
            st.session_state.admin_logged_in = False
        
        # If not logged in, show login form
        if not st.session_state.admin_logged_in:
            st.warning("Admin access is protected. Please enter the password to continue.")
            
            with st.form("admin_login_form"):
                admin_password = st.text_input("Admin Password", type="password")
                submitted = st.form_submit_button("Login")
                
                if submitted:
                    # Check password against environment variable
                    correct_password = os.environ.get("ADMIN_PASSWORD", "")
                    
                    if admin_password == correct_password:
                        st.session_state.admin_logged_in = True
                        st.rerun()  # Refresh the page after successful login
                    else:
                        st.error("Incorrect password. Please try again.")
        
        # If logged in, show admin settings
        if st.session_state.admin_logged_in:
            st.warning("Changes to these settings will affect all future quotes. Use with caution.")
            
            # Logout button
            if st.button("Logout from Admin"):
                st.session_state.admin_logged_in = False
                st.rerun()
            
            # Admin settings
            material_settings_updated = False
            machine_settings_updated = False
            labor_settings_updated = False
            quickbooks_settings_updated = False
        
        # Only show settings if logged in
        if st.session_state.admin_logged_in:
            # Material Settings
            with st.expander("Material Settings", expanded=True):
                st.subheader("Thread Settings")
                col1, col2 = st.columns(2)
            
            with col1:
                new_polyneon_5500yd_price = st.number_input(
                    "Polyneon 5500yd Spool Price ($)",
                    min_value=0.01,
                    value=float(POLYNEON_5500YD_PRICE),
                    format="%.2f",
                    help="Cost of a 5500 yard spool of Polyneon thread"
                )
                
                new_polyneon_1100yd_price = st.number_input(
                    "Polyneon 1100yd Spool Price ($)",
                    min_value=0.01,
                    value=float(POLYNEON_1100YD_PRICE),
                    format="%.2f",
                    help="Cost of a 1100 yard spool of Polyneon thread"
                )
            
            with col2:
                new_bobbin_144_price = st.number_input(
                    "Bobbin 144-Pack Price ($)",
                    min_value=0.01,
                    value=float(BOBBIN_144_PRICE),
                    format="%.2f",
                    help="Cost of a pack of 144 bobbins"
                )
                
                new_bobbin_yards = st.number_input(
                    "Yards Per Bobbin",
                    min_value=1,
                    value=int(float(BOBBIN_YARDS)),
                    help="Number of yards of thread per bobbin"
                )
            
            st.subheader("Other Materials")
            col1, col2 = st.columns(2)
            
            with col1:
                new_foam_sheet_price = st.number_input(
                    "3D Foam Sheet Price ($)",
                    min_value=0.01,
                    value=float(FOAM_SHEET_PRICE),
                    format="%.2f",
                    help="Cost per sheet of 3D foam"
                )
            
            with col2:
                new_stabilizer_price = st.number_input(
                    "Stabilizer Price Per Piece ($)",
                    min_value=0.01,
                    value=float(STABILIZER_PRICE_PER_PIECE),
                    format="%.2f",
                    help="Cost per piece of stabilizer backing"
                )
            
            if st.button("Update Material Settings"):
                # Update database
                database.update_setting("material_settings", "POLYNEON_5500YD_PRICE", new_polyneon_5500yd_price)
                database.update_setting("material_settings", "POLYNEON_1100YD_PRICE", new_polyneon_1100yd_price)
                database.update_setting("material_settings", "BOBBIN_144_PRICE", new_bobbin_144_price)
                database.update_setting("material_settings", "BOBBIN_YARDS", new_bobbin_yards)
                database.update_setting("material_settings", "FOAM_SHEET_PRICE", new_foam_sheet_price)
                database.update_setting("material_settings", "STABILIZER_PRICE_PER_PIECE", new_stabilizer_price)
                st.success("Material settings updated successfully!")
                material_settings_updated = True
        
            # Machine Settings
            with st.expander("Machine Settings"):
                st.subheader("Machine Speed Settings")
                col1, col2 = st.columns(2)
            
            with col1:
                new_stitch_speed_40wt = st.number_input(
                    "40wt Thread Stitch Speed (rpm)",
                    min_value=100,
                    max_value=1500,
                    value=int(float(DEFAULT_STITCH_SPEED_40WT)),
                    help="Default stitching speed for 40wt thread in rpm"
                )
            
            with col2:
                new_stitch_speed_60wt = st.number_input(
                    "60wt Thread Stitch Speed (rpm)",
                    min_value=100,
                    max_value=1500,
                    value=int(float(DEFAULT_STITCH_SPEED_60WT)),
                    help="Default stitching speed for 60wt thread in rpm"
                )
            
            st.subheader("Machine Configuration")
            col1, col2 = st.columns(2)
            
            with col1:
                new_max_heads = st.number_input(
                    "Maximum Machine Heads",
                    min_value=1,
                    max_value=50,
                    value=int(float(DEFAULT_MAX_HEADS)),
                    help="Maximum number of embroidery heads available"
                )
                
                new_coloreel_max_heads = st.number_input(
                    "Maximum Coloreel Heads",
                    min_value=1,
                    max_value=10,
                    value=int(float(DEFAULT_COLOREEL_MAX_HEADS)),
                    help="Maximum number of embroidery heads when using Coloreel"
                )
            
            with col2:
                new_hooping_time = st.number_input(
                    "Hooping Time (seconds)",
                    min_value=1,
                    max_value=300,
                    value=int(float(HOOPING_TIME_DEFAULT)),
                    help="Average time to hoop an item in seconds"
                )
                
            # Productivity Settings
            st.subheader("Productivity Settings")
            col1, col2 = st.columns(2)
            
            with col1:
                new_default_productivity = st.number_input(
                    "Default Productivity Rate",
                    min_value=0.1,
                    max_value=1.0,
                    value=float(DEFAULT_PRODUCTIVITY_RATE),
                    format="%.2f",
                    step=0.05,
                    help="Default productivity rate (1.0 = 100% efficiency)"
                )
                
                new_complex_productivity = st.number_input(
                    "Complex Production Rate",
                    min_value=0.1,
                    max_value=1.0,
                    value=float(DEFAULT_COMPLEX_PRODUCTIVITY_RATE),
                    format="%.2f",
                    step=0.05,
                    help="Productivity rate for complex designs (lower means slower production)"
                )
            
            with col2:
                new_coloreel_productivity = st.number_input(
                    "Coloreel Productivity Rate",
                    min_value=0.1,
                    max_value=1.0,
                    value=float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE),
                    format="%.2f",
                    step=0.05,
                    help="Productivity rate for Coloreel ITCU (lower means slower production)"
                )
                
                new_digitizing_fee = st.number_input(
                    "Default Digitizing Fee ($)",
                    min_value=0.0,
                    max_value=500.0,
                    value=float(DEFAULT_DIGITIZING_FEE),
                    format="%.2f",
                    step=5.0,
                    help="Default fee for digitizing complex designs"
                )

            st.subheader("Buffer Time Settings")
            st.info("Buffer time is added between production cycles for product removal and setup.")
            col1, col2 = st.columns(2)
            
            with col1:
                new_buffer_minutes = st.number_input(
                    "Fixed Buffer Time (minutes)",
                    min_value=0.0,
                    max_value=20.0,
                    value=float(DEFAULT_BUFFER_MINUTES),
                    format="%.1f",
                    step=0.5,
                    help="Fixed time in minutes added between each production cycle for product removal and setup"
                )
            
            with col2:
                new_buffer_percentage = st.number_input(
                    "Percentage of Cycle Time (%)",
                    min_value=0.0,
                    max_value=50.0,
                    value=float(DEFAULT_BUFFER_PERCENTAGE),
                    format="%.1f",
                    step=1.0,
                    help="Additional buffer time calculated as a percentage of the production cycle time"
                )
            
            if st.button("Update Machine Settings"):
                # Update database
                database.update_setting("machine_settings", "DEFAULT_STITCH_SPEED_40WT", new_stitch_speed_40wt)
                database.update_setting("machine_settings", "DEFAULT_STITCH_SPEED_60WT", new_stitch_speed_60wt)
                database.update_setting("machine_settings", "DEFAULT_MAX_HEADS", new_max_heads)
                database.update_setting("machine_settings", "DEFAULT_COLOREEL_MAX_HEADS", new_coloreel_max_heads)
                database.update_setting("machine_settings", "HOOPING_TIME_DEFAULT", new_hooping_time)
                database.update_setting("machine_settings", "DEFAULT_PRODUCTIVITY_RATE", new_default_productivity)
                database.update_setting("machine_settings", "DEFAULT_COMPLEX_PRODUCTIVITY_RATE", new_complex_productivity)
                database.update_setting("machine_settings", "DEFAULT_COLOREEL_PRODUCTIVITY_RATE", new_coloreel_productivity)
                database.update_setting("machine_settings", "DEFAULT_DIGITIZING_FEE", new_digitizing_fee)
                # Save buffer time settings
                database.update_setting("machine_settings", "DEFAULT_BUFFER_MINUTES", new_buffer_minutes)
                database.update_setting("machine_settings", "DEFAULT_BUFFER_PERCENTAGE", new_buffer_percentage)
                st.success("Machine settings updated successfully!")
                machine_settings_updated = True
        
            # Labor Settings
            with st.expander("Labor Settings"):
                st.subheader("Default Labor Rate")
                new_hourly_labor_rate = st.number_input(
                    "Default Hourly Labor Rate ($)",
                    min_value=1.0,
                    value=float(HOURLY_LABOR_RATE),
                    format="%.2f",
                    help="Default cost of labor per hour"
                )
            
                if st.button("Update Default Labor Rate"):
                    # Update database
                    database.update_setting("labor_settings", "HOURLY_LABOR_RATE", new_hourly_labor_rate)
                    st.success("Default labor rate updated successfully!")
                    labor_settings_updated = True
                    
                # Horizontal line to separate default rate from worker management
                st.markdown("---")
                
                # Labor Workers Management
                st.subheader("Labor Workers Management")
                st.markdown("Create, update, or remove laborers with individual hourly rates.")
                
                # Get existing workers from database
                workers = database.get_labor_workers()
            
                # New worker form
                with st.form("add_worker_form"):
                    st.subheader("Add New Worker")
                    new_worker_name = st.text_input("Worker Name")
                    new_worker_rate = st.number_input("Hourly Rate ($)", min_value=1.0, value=float(HOURLY_LABOR_RATE), format="%.2f")
                    new_worker_active = st.checkbox("Active by Default", value=True, help="If checked, this worker will be active by default in new quotes")
                
                    add_worker_submitted = st.form_submit_button("Add Worker", type="primary")
                    if add_worker_submitted and new_worker_name:
                        worker_id = database.add_labor_worker(new_worker_name, new_worker_rate, new_worker_active)
                        if worker_id:
                            st.success(f"Worker '{new_worker_name}' added successfully!")
                            # Refresh the page to show the new worker
                            st.rerun()
                        else:
                            st.error("Failed to add worker. Please try again.")
            
                # Display existing workers
                if workers:
                    st.subheader("Existing Workers")
                
                    # Custom CSS for worker cards
                    st.markdown("""
                    <style>
                    .worker-card {
                        border: 1px solid #f3770c;
                        border-radius: 10px;
                        padding: 15px;
                        margin-bottom: 15px;
                        background-color: #fff9f0;
                    }
                    .worker-header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 10px;
                    }
                    .worker-name {
                        font-weight: bold;
                        font-size: 16px;
                        color: #3a1d0d;
                    }
                    .worker-rate {
                        color: #f3770c;
                        font-weight: bold;
                    }
                    .worker-status {
                        font-size: 14px;
                        padding: 3px 8px;
                        border-radius: 12px;
                        display: inline-block;
                    }
                    .status-active {
                        background-color: #d4edda;
                        color: #155724;
                    }
                    .status-inactive {
                        background-color: #f8d7da;
                        color: #721c24;
                    }
                    </style>
                    """, unsafe_allow_html=True)
                
                    # Display existing workers in a table format with edit/delete buttons
                    worker_data = []
                    for worker in workers:
                        worker_data.append({
                            "id": worker['id'],
                            "name": worker['name'],
                            "hourly_rate": f"${worker['hourly_rate']:.2f}",
                            "status": "Active" if worker['is_active'] else "Inactive"
                        })
                    
                    # Create and display the workers table
                    worker_df = pd.DataFrame(worker_data)
                    st.dataframe(worker_df[["name", "hourly_rate", "status"]], use_container_width=True)
                    
                    # Worker editing section - select a worker to edit
                    st.subheader("Edit Worker")
                    
                    # Worker selection 
                    worker_options = [f"{w['name']} (${float(w['hourly_rate']):.2f}/hr)" for w in workers]
                    selected_worker_index = st.selectbox("Select a worker to edit:", 
                                                        options=range(len(worker_options)),
                                                        format_func=lambda x: worker_options[x])
                
                    # Get the selected worker details
                    selected_worker = workers[selected_worker_index]
                    
                    # Show edit form for the selected worker
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        # Edit form for this worker
                        edited_name = st.text_input("Name", value=selected_worker['name'], key=f"name_{selected_worker['id']}")
                        edited_rate = st.number_input("Hourly Rate ($)", 
                                                  min_value=1.0, 
                                                  value=float(selected_worker['hourly_rate']), 
                                                  format="%.2f", 
                                                  key=f"rate_{selected_worker['id']}")
                    
                    with col2:
                        edited_active = st.checkbox("Active", 
                                                value=selected_worker['is_active'], 
                                                key=f"active_{selected_worker['id']}")
                        
                    # Save changes button
                    if st.button("Save Changes", key=f"save_{selected_worker['id']}"):
                        success = database.update_labor_worker(
                            selected_worker['id'], 
                            name=edited_name,
                            hourly_rate=edited_rate,
                            is_active=edited_active
                        )
                        if success:
                            st.success(f"Worker '{edited_name}' updated successfully!")
                            # Refresh the page to show updated data
                            st.rerun()
                        else:
                            st.error("Failed to update worker. Please try again.")
                    
                    # Delete button (with confirmation)
                    if st.button("Delete Worker", key=f"delete_{selected_worker['id']}"):
                        confirm_delete = st.checkbox("Confirm deletion? This cannot be undone.", key=f"confirm_{selected_worker['id']}")
                        if confirm_delete:
                            success = database.delete_labor_worker(selected_worker['id'])
                            if success:
                                st.success(f"Worker '{selected_worker['name']}' deleted successfully!")
                                # Refresh the page to update the list
                                st.rerun()
                            else:
                                st.error("Failed to delete worker. Please try again.")
                else:
                    st.info("No workers found. Add your first worker using the form above.")
        
        # QuickBooks Integration has been removed
        
        # View Database Quotes
        with st.expander("View Quote Database"):
            st.subheader("Recent Quotes")
            quotes = database.get_recent_quotes(limit=20)
            
            if not quotes:
                st.info("No quotes saved to database yet.")
            else:
                # Create a DataFrame for display
                df = pd.DataFrame(quotes)
                df['created_at'] = pd.to_datetime(df['created_at'])
                df['created_at'] = df['created_at'].dt.strftime('%Y-%m-%d %H:%M')
                df = df.rename(columns={
                    'job_name': 'Job Name',
                    'customer_name': 'Customer',
                    'stitch_count': 'Stitches',
                    'quantity': 'Qty',
                    'total_cost': 'Total Cost',
                    'price_per_piece': 'Price/Piece',
                    'created_at': 'Date'
                })
                df['Total Cost'] = df['Total Cost'].map('${:.2f}'.format)
                df['Price/Piece'] = df['Price/Piece'].map('${:.2f}'.format)
                
                st.dataframe(df, use_container_width=True)
        
        # Instead of using flags, just show the reload button
        if st.button("Reload Application Settings"):
            st.rerun()

if __name__ == "__main__":
    main()
