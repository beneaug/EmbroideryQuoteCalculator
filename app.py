import streamlit as st
import pyembroidery
import pandas as pd
import numpy as np
import io
import base64
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
import database

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
        
        # Estimate thread consumption (simple heuristic: 1 meter per 500 stitches)
        thread_length_meters = stitch_count / 500
        thread_length_yards = thread_length_meters * 1.09361
        
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
    
    # Create an image with the correct dimensions for 1:1 scale
    img = Image.new('RGB', (pixel_width, pixel_height), color='white')
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
        draw.rectangle(boundary_coords, outline='lightblue', width=2)
    
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
    bobbin_thread_yards = thread_per_piece_yards * 0.4 * quantity  # 40% of top thread
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
    
    # Total production time per piece
    production_time_per_piece = stitching_time_minutes + hooping_time_minutes
    
    # Total production time for the batch, accounting for multiple heads
    pieces_per_run = min(active_heads, quantity)  # Can't use more heads than pieces
    runs_needed = math.ceil(quantity / pieces_per_run)
    
    total_production_time_minutes = runs_needed * production_time_per_piece
    total_production_time_hours = total_production_time_minutes / 60
    
    # 6. Labor cost
    labor_cost = total_production_time_hours * HOURLY_LABOR_RATE
    
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
        "productivity_rate": productivity_rate
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
        textColor=colors.darkblue
    )
    
    # Title
    elements.append(Paragraph("Embroidery Job Quote (Internal)", title_style))
    elements.append(Spacer(1, 0.2 * inch))
    
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
        ["Production Time", f"{cost_results['production_time_hours']:.2f} hours ({cost_results['production_time_minutes']:.1f} min)"],
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
        textColor=colors.darkblue
    )
    
    # Title
    elements.append(Paragraph("Embroidery Quote", title_style))
    elements.append(Spacer(1, 0.2 * inch))
    
    # Company info (placeholder - customize as needed)
    company_info = """
    Your Embroidery Company<br/>
    123 Stitch Lane<br/>
    Embroidery City, EC 12345<br/>
    Phone: (555) 123-4567<br/>
    Email: info@yourembroidery.com
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
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{filename}">{text}</a>'
    return href

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
    }
    
    h1 {
        font-size: 3rem;
        margin-bottom: 1.5rem;
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
        st.header("Step 1: Choose File or Manual Entry")
        
        # Toggle between file upload and manual entry
        entry_method = st.radio(
            "Select entry method",
            ["Upload Design File", "Manual Entry (No Design File)"],
            horizontal=True,
            help="Choose whether to upload a design file or enter stitch count manually"
        )
        
        if entry_method == "Upload Design File":
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
                st.session_state.design_info = {
                    "stitch_count": manual_stitch_count,
                    "color_changes": manual_colors,
                    "width_inches": manual_width,
                    "height_inches": manual_height,
                    "width_mm": manual_width * 25.4,
                    "height_mm": manual_height * 25.4,
                    "complexity_score": manual_complexity,
                    "thread_length_yards": manual_stitch_count * 0.01,  # Approximate thread length
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
                    # Add thread length in yards and meters
                    thread_yards = st.session_state.design_info['thread_length_yards']
                    thread_meters = thread_yards * 0.9144  # Convert yards to meters
                    st.metric("Thread Length", f"{thread_yards:.2f} yards ({thread_meters:.2f} meters)")
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
                        # Checkbox for foam preview
                        preview_with_foam = st.checkbox("Preview with 3D foam margin", value=False)
                        
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
        st.header("Step 2: Job Information & Materials")
        
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
            <h3 style="margin: 0; color: #3a1d0d; font-weight: 700;">Job Information</h3>
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
            <h3 style="margin: 0; color: #3a1d0d; font-weight: 700;">Machine & Technical Settings</h3>
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
            
            # Complex production checkbox
            complex_production = st.checkbox("Complex Production", value=False,
                                         help="Enable for complex designs that require slower stitching and additional attention")
            
            # Custom productivity rate slider (only shown when complex production is enabled)
            custom_productivity_rate = None
            if complex_production:
                # Calculate default based on complex production
                default_rate = float(DEFAULT_COMPLEX_PRODUCTIVITY_RATE)
                min_rate = 0.2  # 20% efficiency
                max_rate = 1.0  # 100% efficiency
                step = 0.05
                
                custom_productivity_rate = st.slider(
                    "Productivity Rate", 
                    min_value=min_rate,
                    max_value=max_rate,
                    value=default_rate,
                    step=step,
                    format="%.2f",
                    help="Adjust the productivity rate (lower values = slower production)"
                )
                
                st.caption(f"Production Efficiency: {int(custom_productivity_rate * 100)}%")
            
            # Coloreel ITCU checkbox
            coloreel_enabled = st.checkbox("Use Coloreel ITCU", value=False,
                                       help="Enable if using Coloreel instant thread coloring technology")
            
            # If Coloreel is enabled, automatically enable complex production and use Coloreel rate
            if coloreel_enabled:
                if not complex_production:
                    complex_production = True
                    st.info("Complex Production automatically enabled with Coloreel ITCU")
                
                # Override custom productivity rate with Coloreel rate
                custom_productivity_rate = float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE)
                st.caption(f"Coloreel Productivity Rate: {custom_productivity_rate:.2f} ({int(custom_productivity_rate * 100)}% efficiency)")
            
            # Apply head limitations for Coloreel
            coloreel_max_heads = int(DEFAULT_COLOREEL_MAX_HEADS)
            if coloreel_enabled and active_heads > coloreel_max_heads:
                active_heads = coloreel_max_heads
                st.warning(f"Max heads limited to {coloreel_max_heads} with Coloreel enabled")
                
            # Calculate the final productivity rate based on all settings
            if not complex_production:
                productivity_rate = float(DEFAULT_PRODUCTIVITY_RATE)
            elif coloreel_enabled:
                productivity_rate = float(DEFAULT_COLOREEL_PRODUCTIVITY_RATE)
            elif custom_productivity_rate is not None:
                productivity_rate = custom_productivity_rate
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
        
        use_foam = st.checkbox("Use 3D Foam", value=False,
                             help="Check if using 3D foam for raised embroidery effect")
        
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
            <h3 style="margin: 0; color: #3a1d0d; font-weight: 700;">Pricing Information</h3>
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
                "custom_productivity_rate": custom_productivity_rate if 'custom_productivity_rate' in locals() and custom_productivity_rate is not None else None
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
                <h2 style="margin: 0; color: white; font-weight: 700; text-shadow: 0 1px 2px rgba(0,0,0,0.1);">Quote Results</h2>
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
                production_col1, production_col2 = st.columns(2)
                
                with production_col1:
                    st.metric("Runs Needed", str(cost_results['runs_needed']))
                    st.metric("Spools Required", str(cost_results['spools_required']))
                
                with production_col2:
                    st.metric("Bobbins Required", f"{cost_results['bobbins_required']:.1f}")
                    st.metric("Setup Fee", f"${cost_results['setup_fee']:.2f}")
                    
                    # Show digitizing fee if applicable
                    if job_inputs.get("complex_production", False) and cost_results.get("digitizing_fee", 0) > 0:
                        st.metric("Digitizing Fee", f"${cost_results['digitizing_fee']:.2f}")
            
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
                <h3 style="margin: 0; color: #3a1d0d; font-weight: 700;">Download Quotes</h3>
            </div>
            """, unsafe_allow_html=True)
            
            # Custom CSS for download buttons
            st.markdown("""
            <style>
            .download-button {
                display: block;
                background: linear-gradient(90deg, #3a1d0d 0%, #8b6c55 100%);
                color: white;
                font-weight: 600;
                text-align: center;
                padding: 12px 20px;
                margin: 10px 5px;
                border-radius: 15px;
                box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15);
                text-decoration: none;
                transition: all 0.3s ease;
            }
            .download-button:hover {
                box-shadow: 0 6px 15px rgba(0, 0, 0, 0.2);
                transform: translateY(-2px);
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
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                        <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
                        <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>
                    </svg>
                    Internal Quote PDF
                </a>
                ''', unsafe_allow_html=True)
            
            with col2:
                st.markdown(f'''
                <a href="data:application/pdf;base64,{base64.b64encode(customer_pdf.getvalue()).decode()}" 
                   download="{customer_filename}" 
                   class="download-button">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                        <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
                        <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>
                    </svg>
                    Customer Quote PDF
                </a>
                ''', unsafe_allow_html=True)
        
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
    
    # Admin Settings Tab
    with tab3:
        st.header("Admin Settings")
        st.warning("Changes to these settings will affect all future quotes. Use with caution.")
        
        # Admin settings (no password protection as requested)
        material_settings_updated = False
        machine_settings_updated = False
        labor_settings_updated = False
        
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
                st.success("Machine settings updated successfully!")
                machine_settings_updated = True
        
        # Labor Settings
        with st.expander("Labor Settings"):
            new_hourly_labor_rate = st.number_input(
                "Hourly Labor Rate ($)",
                min_value=1.0,
                value=float(HOURLY_LABOR_RATE),
                format="%.2f",
                help="Cost of labor per hour"
            )
            
            if st.button("Update Labor Settings"):
                # Update database
                database.update_setting("labor_settings", "HOURLY_LABOR_RATE", new_hourly_labor_rate)
                st.success("Labor settings updated successfully!")
                labor_settings_updated = True
        
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
        
        # Reset session when settings are updated
        if material_settings_updated or machine_settings_updated or labor_settings_updated:
            if st.button("Reload Application with New Settings"):
                st.rerun()

if __name__ == "__main__":
    main()
