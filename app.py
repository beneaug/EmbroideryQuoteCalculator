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
HOOPING_TIME = machine_settings.get("HOOPING_TIME_DEFAULT", {}).get("value", 50)  # seconds
DEFAULT_PRODUCTIVITY_RATE = machine_settings.get("DEFAULT_PRODUCTIVITY_RATE", {}).get("value", 1.0)  # 100%
DEFAULT_COMPLEX_PRODUCTIVITY_RATE = machine_settings.get("DEFAULT_COMPLEX_PRODUCTIVITY_RATE", {}).get("value", 0.8)  # 80%
DEFAULT_COLOREEL_PRODUCTIVITY_RATE = machine_settings.get("DEFAULT_COLOREEL_PRODUCTIVITY_RATE", {}).get("value", 0.75)  # 75%
DEFAULT_DIGITIZING_FEE = machine_settings.get("DEFAULT_DIGITIZING_FEE", {}).get("value", 25.0)  # $25

# Labor rate from database
HOURLY_LABOR_RATE = labor_settings.get("HOURLY_LABOR_RATE", {}).get("value", 25)  # $/hour

# Thread cost calculations
STITCHES_PER_YARD_40WT = 120
STITCHES_PER_YARD_60WT = 160
THREAD_WASTE_PERCENT = 0.1  # 10% waste
POLYNEON_COST_PER_STITCH_40WT = (POLYNEON_5500YD_PRICE / 5500) / STITCHES_PER_YARD_40WT * (1 + THREAD_WASTE_PERCENT)
POLYNEON_COST_PER_STITCH_60WT = (POLYNEON_1100YD_PRICE / 1100) / STITCHES_PER_YARD_60WT * (1 + THREAD_WASTE_PERCENT)
BOBBIN_COST_PER_STITCH = (BOBBIN_144_PRICE / 144) / (BOBBIN_YARDS * STITCHES_PER_YARD_40WT)

# Other constants
MACHINE_OPERATING_COST_PER_HOUR = 15  # $/hour
FOAM_PIECES_PER_SQUARE_INCH = 1 / (3 * 3)  # One 3x3 inch piece per design

def parse_embroidery_file(uploaded_file):
    """Parse embroidery file and extract key information"""
    file_bytes = uploaded_file.getvalue()
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}")
    temp_file.write(file_bytes)
    temp_file.close()
    
    try:
        pattern = pyembroidery.read(temp_file.name)
        
        # Get stitch count
        stitch_count = pattern.count_stitches()
        
        # Get distinct thread colors
        color_count = len(pattern.threadlist)
        if color_count == 0:  # Handle files with no thread information
            color_count = len(set(s[2] for s in pattern.stitches if s[2] != None))
            if color_count == 0:  # If still 0, estimate from color changes
                color_changes = sum(1 for s in pattern.stitches if s[2] == 0xFE)
                color_count = max(1, color_changes + 1)
        
        # Get dimensions in inches
        min_x, min_y, max_x, max_y = pattern.bounds()
        width_mm = max_x - min_x
        height_mm = max_y - min_y
        width_inches = width_mm / 25.4
        height_inches = height_mm / 25.4
        
        # Get total jumps and trims for complexity estimation
        jumps = sum(1 for s in pattern.stitches if s[2] == 0x00)
        trims = sum(1 for s in pattern.stitches if s[2] == 0xFF)
        color_changes = sum(1 for s in pattern.stitches if s[2] == 0xFE)
        
        # Calculate complexity factors
        density = stitch_count / (width_mm * height_mm) if (width_mm * height_mm) > 0 else 0
        jump_ratio = jumps / stitch_count if stitch_count > 0 else 0
        trim_ratio = trims / stitch_count if stitch_count > 0 else 0
        color_change_ratio = color_changes / stitch_count if stitch_count > 0 else 0
        
        # Create complexity score - higher means more complex
        complexity_score = (
            density * 1000 +    # Density factor
            jump_ratio * 50 +   # Jump factor
            trim_ratio * 100 +  # Trim factor
            color_change_ratio * 30  # Color change factor
        )
        
        # Simple complexity classification
        if complexity_score < 5:
            complexity = "Simple"
        elif complexity_score < 15:
            complexity = "Moderate"
        else:
            complexity = "Complex"
        
        # Format results
        design_info = {
            "filename": uploaded_file.name,
            "stitch_count": stitch_count,
            "color_count": color_count,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "width_inches": width_inches,
            "height_inches": height_inches,
            "complexity": complexity,
            "complexity_score": complexity_score,
            "jumps": jumps,
            "trims": trims,
            "color_changes": color_changes,
            "pattern": pattern  # Include the pattern object for rendering
        }
        
        return design_info
    except Exception as e:
        st.error(f"Error parsing embroidery file: {str(e)}")
        return None
    finally:
        # Clean up temporary file
        os.unlink(temp_file.name)

def render_design_preview(pattern, width=400, height=400, use_foam=False):
    """Render a visual preview of the embroidery design at 1:1 scale"""
    # Create a figure and axis
    fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
    
    # Get design bounds
    min_x, min_y, max_x, max_y = pattern.bounds()
    width_mm = max_x - min_x
    height_mm = max_y - min_y
    
    # Transform coordinates from embroidery space to display space
    padding = 10  # mm padding around design
    display_width = width_mm + 2 * padding
    display_height = height_mm + 2 * padding
    
    # Use light gray background for foam backing
    if use_foam:
        ax.set_facecolor('#E0E0E0')
    
    # Set aspect ratio to equal for proper display
    ax.set_aspect('equal')
    
    # Remove axes and set limits
    ax.axis('off')
    ax.set_xlim([min_x - padding, max_x + padding])
    ax.set_ylim([max_y + padding, min_y - padding])  # Flip Y-axis for proper orientation
    
    # Draw stitches
    last_x, last_y = None, None
    current_color = None
    
    for stitch in pattern.stitches:
        x, y, cmd = stitch
        
        # Skip non-stitch commands
        if cmd == 0xFE:  # Color change
            current_color = pattern.threadlist[stitch[2] & 0xFF].color if len(pattern.threadlist) > 0 else '#000000'
            continue
        elif cmd in [0xFF, 0x00]:  # Jump or trim
            last_x, last_y = x, y
            continue
        
        # Draw stitch line
        if last_x is not None and last_y is not None:
            color = current_color if current_color else '#000000'
            # Convert embroidery hexcolor format to matplotlib format
            if isinstance(color, int):
                color = f'#{color:06x}'
            ax.plot([last_x, x], [last_y, y], color=color, linewidth=0.5)
        
        # Update last position
        last_x, last_y = x, y
    
    # Set plot title with design dimensions
    ax.set_title(f"Design Preview ({width_mm:.1f}mm × {height_mm:.1f}mm)")
    
    # Use transparent background for the figure
    fig.patch.set_alpha(0.0)
    
    # Convert plot to image
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    buf.seek(0)
    
    # Clean up matplotlib resources
    plt.close(fig)
    
    return buf

def calculate_costs(design_info, job_inputs):
    """Calculate all costs based on design data and job inputs"""
    # Extract design details
    stitch_count = design_info["stitch_count"]
    color_count = design_info["color_count"]
    complexity = design_info["complexity"]
    width_inches = design_info["width_inches"]
    height_inches = design_info["height_inches"]
    
    # Extract job inputs
    quantity = job_inputs["quantity"]
    thread_weight = job_inputs["thread_weight"]
    use_foam = job_inputs["use_foam"]
    active_heads = job_inputs["active_heads"]
    complex_production = job_inputs["complex_production"]
    coloreel_enabled = job_inputs["coloreel_enabled"]
    digitizing_fee = job_inputs["digitizing_fee"]
    premium_product = job_inputs["premium_product"]
    minimum_total = job_inputs["minimum_total"]
    markup_factor = job_inputs["markup_factor"]
    
    # Select thread cost based on weight
    if thread_weight == "40wt":
        thread_cost_per_stitch = POLYNEON_COST_PER_STITCH_40WT
        stitch_speed = DEFAULT_STITCH_SPEED_40WT
    else:  # 60wt
        thread_cost_per_stitch = POLYNEON_COST_PER_STITCH_60WT
        stitch_speed = DEFAULT_STITCH_SPEED_60WT
    
    # Calculate thread costs
    top_thread_cost = thread_cost_per_stitch * stitch_count
    bobbin_thread_cost = BOBBIN_COST_PER_STITCH * stitch_count
    total_thread_cost = top_thread_cost + bobbin_thread_cost
    
    # Foam costs if used
    foam_cost = 0
    if use_foam:
        # Calculate area needed in square inches
        design_area = width_inches * height_inches
        # Calculate number of foam pieces needed (1 piece per 9 sq inches)
        foam_pieces = math.ceil(design_area * FOAM_PIECES_PER_SQUARE_INCH)
        # Calculate cost
        foam_cost = foam_pieces * FOAM_SHEET_PRICE
    
    # Calculate stabilizer costs - one piece per item
    stabilizer_cost = STABILIZER_PRICE_PER_PIECE * quantity
    
    # Calculate labor and machine time
    productivity_rate = get_productivity_rate(complex_production, coloreel_enabled)
    
    # Effective stitch speed considering productivity rate
    effective_stitch_speed = stitch_speed * productivity_rate
    
    # Runtime calculation (hours)
    # Consider reduced active heads if coloreel is enabled
    if coloreel_enabled:
        active_heads = min(active_heads, DEFAULT_COLOREEL_MAX_HEADS)
    
    # Calculate stitching time
    stitching_time_hours = stitch_count / (effective_stitch_speed * 60) / active_heads
    
    # Add setup time - hooping + color changes
    # Each color change takes ~20 seconds, hooping takes HOOPING_TIME seconds per piece
    if coloreel_enabled:
        color_change_time_hours = 0  # No color changes with Coloreel
    else:
        color_change_time_hours = (color_count - 1) * 20 / 3600 * quantity  # 20 seconds per color change
    
    hooping_time_hours = (HOOPING_TIME / 3600) * quantity  # Convert seconds to hours
    
    # Total production time
    total_production_time_hours = stitching_time_hours + color_change_time_hours + hooping_time_hours
    
    # Labor cost calculation
    labor_cost = total_production_time_hours * HOURLY_LABOR_RATE
    
    # Machine cost calculation
    machine_cost = total_production_time_hours * MACHINE_OPERATING_COST_PER_HOUR
    
    # Add digitizing fee if applicable
    total_digitizing_fee = digitizing_fee if digitizing_fee > 0 else 0
    
    # Calculate base costs
    base_materials_cost = total_thread_cost * quantity + foam_cost + stabilizer_cost
    base_fixed_costs = machine_cost + labor_cost + total_digitizing_fee
    
    # Calculate total cost before markup
    total_cost_before_markup = base_materials_cost + base_fixed_costs
    
    # Apply premium product factor if selected (adds 20%)
    if premium_product:
        total_cost_before_markup *= 1.2
    
    # Apply markup factor
    total_cost = total_cost_before_markup * markup_factor
    
    # Apply minimum total if needed
    if total_cost < minimum_total:
        total_cost = minimum_total
    
    # Calculate per piece price
    price_per_piece = total_cost / quantity
    
    # Format all costs for display with 2 decimal places
    cost_results = {
        "thread_cost_per_piece": top_thread_cost,
        "bobbin_cost_per_piece": bobbin_thread_cost,
        "total_thread_cost": total_thread_cost * quantity,
        "stabilizer_cost": stabilizer_cost,
        "foam_cost": foam_cost,
        "base_materials_cost": base_materials_cost,
        
        "stitching_time_hours": stitching_time_hours,
        "color_change_time_hours": color_change_time_hours,
        "hooping_time_hours": hooping_time_hours,
        "total_production_time_hours": total_production_time_hours,
        "total_production_time_minutes": total_production_time_hours * 60,
        
        "labor_cost": labor_cost,
        "machine_cost": machine_cost,
        "digitizing_fee": total_digitizing_fee,
        "base_fixed_costs": base_fixed_costs,
        
        "total_cost_before_markup": total_cost_before_markup,
        "markup_factor": markup_factor,
        "premium_factor": 1.2 if premium_product else 1.0,
        "total_cost": total_cost,
        "price_per_piece": price_per_piece,
        
        "productivity_rate": productivity_rate,
        "effective_stitch_speed": effective_stitch_speed,
        "active_heads": active_heads
    }
    
    return cost_results

def generate_detailed_quote_pdf(design_info, job_inputs, cost_results):
    """Generate a detailed internal quote PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    subtitle_style = styles['Heading2']
    section_title_style = styles['Heading3']
    normal_style = styles['Normal']
    
    # Create a custom style for table headers
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=colors.white,
        alignment=1,  # Center alignment
    )
    
    # Title
    elements.append(Paragraph("Embroidery Quote (Internal)", title_style))
    
    # Job and customer info
    job_name = job_inputs.get("job_name", "Unnamed Job")
    customer_name = job_inputs.get("customer_name", "Unknown Customer")
    elements.append(Paragraph(f"Job: {job_name}", subtitle_style))
    elements.append(Paragraph(f"Customer: {customer_name}", normal_style))
    elements.append(Paragraph(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d')}", normal_style))
    elements.append(Spacer(1, 0.2 * inch))
    
    # Design details
    elements.append(Paragraph("Design Details", section_title_style))
    design_data = [
        ["Filename", design_info.get("filename", "Unknown")],
        ["Stitch Count", f"{design_info.get('stitch_count', 0):,}"],
        ["Colors", f"{design_info.get('color_count', 0)}"],
        ["Dimensions", f"{design_info.get('width_inches', 0):.2f}\" × {design_info.get('height_inches', 0):.2f}\""],
        ["Complexity", design_info.get("complexity", "Unknown")]
    ]
    design_table = Table(design_data, colWidths=[2*inch, 3.5*inch])
    design_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(design_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Job parameters
    elements.append(Paragraph("Job Parameters", section_title_style))
    job_data = [
        ["Quantity", f"{job_inputs.get('quantity', 0)}"],
        ["Thread Weight", job_inputs.get("thread_weight", "40wt")],
        ["Using Foam", "Yes" if job_inputs.get("use_foam", False) else "No"],
        ["Active Heads", f"{job_inputs.get('active_heads', 0)}"],
        ["Complex Production", "Yes" if job_inputs.get("complex_production", False) else "No"],
        ["Coloreel Enabled", "Yes" if job_inputs.get("coloreel_enabled", False) else "No"],
        ["Premium Product", "Yes" if job_inputs.get("premium_product", False) else "No"],
        ["Minimum Total", f"${job_inputs.get('minimum_total', 0):.2f}"],
        ["Markup Factor", f"{job_inputs.get('markup_factor', 1.0):.2f}×"]
    ]
    job_table = Table(job_data, colWidths=[2*inch, 3.5*inch])
    job_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(job_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Cost breakdown
    elements.append(Paragraph("Cost Breakdown", section_title_style))
    cost_data = [
        ["Item", "Value"],
        ["Thread Cost", f"${cost_results.get('total_thread_cost', 0):.2f}"],
        ["Stabilizer Cost", f"${cost_results.get('stabilizer_cost', 0):.2f}"],
        ["Foam Cost", f"${cost_results.get('foam_cost', 0):.2f}"],
        ["Total Materials", f"${cost_results.get('base_materials_cost', 0):.2f}"],
        ["Production Time", f"{cost_results.get('total_production_time_minutes', 0):.1f} minutes"],
        ["Labor Cost", f"${cost_results.get('labor_cost', 0):.2f}"],
        ["Machine Cost", f"${cost_results.get('machine_cost', 0):.2f}"],
        ["Digitizing Fee", f"${cost_results.get('digitizing_fee', 0):.2f}"],
        ["Total Fixed Costs", f"${cost_results.get('base_fixed_costs', 0):.2f}"],
        ["Subtotal", f"${cost_results.get('total_cost_before_markup', 0):.2f}"],
        ["Premium Factor", f"{cost_results.get('premium_factor', 1.0):.2f}×"],
        ["Markup Factor", f"{cost_results.get('markup_factor', 1.0):.2f}×"],
        ["Total Cost", f"${cost_results.get('total_cost', 0):.2f}"],
        ["Price Per Piece", f"${cost_results.get('price_per_piece', 0):.2f}"]
    ]
    cost_table = Table(cost_data, colWidths=[2.5*inch, 3*inch])
    cost_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
        ('ALIGN', (0, 0), (1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 1), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.black),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        # Highlight the final two rows (Total Cost and Price Per Piece)
        ('BACKGROUND', (0, -2), (1, -1), colors.lightyellow),
        ('FONTNAME', (0, -2), (1, -1), 'Helvetica-Bold')
    ]))
    elements.append(cost_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Technical details
    elements.append(Paragraph("Technical Details", section_title_style))
    tech_data = [
        ["Productivity Rate", f"{cost_results.get('productivity_rate', 0):.2f}"],
        ["Effective Stitch Speed", f"{cost_results.get('effective_stitch_speed', 0):.0f} rpm"],
        ["Active Heads", f"{cost_results.get('active_heads', 0)}"],
        ["Stitching Time", f"{cost_results.get('stitching_time_hours', 0)*60:.1f} minutes"],
        ["Color Change Time", f"{cost_results.get('color_change_time_hours', 0)*60:.1f} minutes"],
        ["Hooping Time", f"{cost_results.get('hooping_time_hours', 0)*60:.1f} minutes"]
    ]
    tech_table = Table(tech_data, colWidths=[2*inch, 3.5*inch])
    tech_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(tech_table)
    
    # Generate the PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_customer_quote_pdf(design_info, job_inputs, cost_results):
    """Generate a client-facing quote PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    subtitle_style = styles['Heading2']
    section_title_style = styles['Heading3']
    normal_style = styles['Normal']
    
    # Title
    quote_number = f"{datetime.datetime.now().strftime('%Y%m%d')}-{job_inputs.get('job_name', '')[:3].upper()}"
    elements.append(Paragraph(f"Embroidery Quote #{quote_number}", title_style))
    
    # Job and customer info
    job_name = job_inputs.get("job_name", "Unnamed Job")
    customer_name = job_inputs.get("customer_name", "Dear Customer")
    elements.append(Paragraph(f"Project: {job_name}", subtitle_style))
    elements.append(Paragraph(f"Client: {customer_name}", normal_style))
    elements.append(Paragraph(f"Date: {datetime.datetime.now().strftime('%B %d, %Y')}", normal_style))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Design details
    elements.append(Paragraph("Design Specifications", section_title_style))
    design_data = [
        ["Stitch Count", f"{design_info.get('stitch_count', 0):,}"],
        ["Colors", f"{design_info.get('color_count', 0)}"],
        ["Dimensions", f"{design_info.get('width_inches', 0):.2f}\" × {design_info.get('height_inches', 0):.2f}\""]
    ]
    design_table = Table(design_data, colWidths=[2.5*inch, 3*inch])
    design_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(design_table)
    elements.append(Spacer(1, 0.2 * inch))
    
    # Order details
    elements.append(Paragraph("Order Details", section_title_style))
    order_data = [
        ["Quantity", f"{job_inputs.get('quantity', 0)}"],
        ["Thread Type", "Premium Polyneon" if job_inputs.get("thread_weight", "40wt") == "40wt" else "Fine Detail Polyneon"],
        ["3D Foam", "Yes" if job_inputs.get("use_foam", False) else "No"],
        ["Premium Finish", "Yes" if job_inputs.get("premium_product", False) else "No"]
    ]
    order_table = Table(order_data, colWidths=[2.5*inch, 3*inch])
    order_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    elements.append(order_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Price summary
    elements.append(Paragraph("Price Summary", section_title_style))
    total_cost = cost_results.get('total_cost', 0)
    price_per_piece = cost_results.get('price_per_piece', 0)
    
    price_data = [
        ["Description", "Amount"],
        ["Total Order Price", f"${total_cost:.2f}"],
        ["Price Per Piece", f"${price_per_piece:.2f}"]
    ]
    price_table = Table(price_data, colWidths=[3.5*inch, 2*inch])
    price_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
        ('ALIGN', (0, 0), (1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 1), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 1), (0, -1), colors.black),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        # Highlight the rows
        ('BACKGROUND', (0, 1), (1, -1), colors.lightyellow)
    ]))
    elements.append(price_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Terms and notes
    elements.append(Paragraph("Terms and Conditions", section_title_style))
    terms_text = """
    1. This quote is valid for 30 days from the date of issuance.
    2. A 50% deposit is required to begin production.
    3. Production time is typically 5-7 business days after approval of all design proofs.
    4. Minor variations in design size and appearance may occur during production.
    5. Additional fees may apply for design revisions or rush orders.
    
    Thank you for your business!
    """
    elements.append(Paragraph(terms_text, normal_style))
    
    # Generate the PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

def get_download_link(buffer, filename, text):
    """Generate a download link for a file"""
    b64 = base64.b64encode(buffer.getvalue()).decode()
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{filename}">{text}</a>'
    return href

# QuickBooks integration functions have been removed
# def get_quickbooks_client():
#     """Function used to initialize a QuickBooks client"""
#     pass

# def export_to_quickbooks():
#     """Function used to export quotes to QuickBooks"""
#     pass

# def get_quickbooks_auth_url():
#     """Function used to generate QuickBooks auth URL"""
#     pass

def get_productivity_rate(complex_production, coloreel_enabled, custom_rate=None):
    """Calculate productivity rate based on the selected options"""
    if custom_rate is not None:
        return float(custom_rate)
        
    # Start with base productivity rate
    productivity = DEFAULT_PRODUCTIVITY_RATE
    
    # Apply reductions for complexity and Coloreel
    if complex_production:
        productivity = DEFAULT_COMPLEX_PRODUCTIVITY_RATE
    
    if coloreel_enabled:
        productivity = DEFAULT_COLOREEL_PRODUCTIVITY_RATE
    
    # If both complex AND Coloreel, take the lowest rate and reduce further
    if complex_production and coloreel_enabled:
        productivity = min(DEFAULT_COMPLEX_PRODUCTIVITY_RATE, DEFAULT_COLOREEL_PRODUCTIVITY_RATE) * 0.9
        
    return productivity

def main():
    # Set gradient background - iOS style light yellow/orange gradient
    background_gradient = """
    <style>
        .stApp {
            background: linear-gradient(to bottom right, #ffecc6, #ffac4b);
        }
        .css-18e3th9 {
            padding-top: 1rem;
        }
        .css-1kyxreq {
            margin-top: -60px;
        }
        
        /* Custom button styles */
        .css-1x8cf1d {
            background-color: #ff9d00;
            border-color: #ff8800;
        }
        .css-1x8cf1d:hover {
            background-color: #ff8800;
            border-color: #ff7700;
        }
        
        /* Remove colored header bar */
        header {
            visibility: hidden;
        }
        
        /* Make sidebar background transparent */
        section[data-testid="stSidebar"] {
            background-color: rgba(255, 255, 255, 0.3);
            backdrop-filter: blur(5px);
        }
    </style>
    """
    st.markdown(background_gradient, unsafe_allow_html=True)
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Calculator", "History", "Settings", "Admin"])
    
    # Tab 1: Embroidery Quote Calculator
    with tab1:
        st.title("Embroidery Quote Calculator")
        st.markdown("Upload your embroidery file and adjust settings to calculate the quote.")
        
        # Step 1: Design Upload
        with st.expander("Step 1: Upload Design", expanded=True):
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.write("Upload your embroidery design file:")
                uploaded_file = st.file_uploader("Choose a file", type=["dst", "u01"])
                st.write("OR enter design details manually:")
                
                if not uploaded_file:
                    manual_stitch_count = st.number_input("Stitch Count", min_value=0, max_value=100000, value=5000, step=100)
                    manual_color_count = st.number_input("Color Count", min_value=1, max_value=50, value=3, step=1)
                    manual_width = st.number_input("Width (inches)", min_value=0.1, max_value=20.0, value=4.0, step=0.1)
                    manual_height = st.number_input("Height (inches)", min_value=0.1, max_value=20.0, value=3.0, step=0.1)
                    
                    # Create manual design info
                    design_info = {
                        "filename": "Manual Entry",
                        "stitch_count": manual_stitch_count,
                        "color_count": manual_color_count,
                        "width_inches": manual_width,
                        "height_inches": manual_height,
                        "width_mm": manual_width * 25.4,
                        "height_mm": manual_height * 25.4,
                        "complexity": "Moderate",  # Default for manual entry
                        "complexity_score": 10,  # Default for manual entry
                        "pattern": None  # No pattern for manual entry
                    }
            
            with col2:
                if uploaded_file:
                    with st.spinner("Processing design file..."):
                        # Parse the embroidery file
                        design_info = parse_embroidery_file(uploaded_file)
                        
                        if design_info:
                            # Create columns for metrics
                            metric_col1, metric_col2, metric_col3 = st.columns(3)
                            
                            with metric_col1:
                                st.metric("Stitch Count", f"{design_info['stitch_count']:,}")
                            
                            with metric_col2:
                                st.metric("Colors", str(design_info['color_count']))
                            
                            with metric_col3:
                                st.metric("Size (inches)", f"{design_info['width_inches']:.2f} × {design_info['height_inches']:.2f}")
                            
                            # Render design preview
                            st.write("Design Preview:")
                            if design_info.get("pattern"):
                                preview_buffer = render_design_preview(design_info["pattern"])
                                st.image(preview_buffer, use_column_width=True)
                            else:
                                st.info("Preview not available for this file format.")
                    
                elif 'design_info' in locals():
                    # Show manual design info
                    metric_col1, metric_col2, metric_col3 = st.columns(3)
                    
                    with metric_col1:
                        st.metric("Stitch Count", f"{design_info['stitch_count']:,}")
                    
                    with metric_col2:
                        st.metric("Colors", str(design_info['color_count']))
                    
                    with metric_col3:
                        st.metric("Size (inches)", f"{design_info['width_inches']:.2f} × {design_info['height_inches']:.2f}")
                    
                    # No preview for manual entry
                    st.info("Preview not available for manual entry.")
                else:
                    st.info("Upload a file or enter design details manually to continue.")
        
        # Step 2: Set Job Parameters
        with st.expander("Step 2: Job Parameters", expanded=uploaded_file is not None or ('design_info' in locals() and design_info)):
            if uploaded_file is not None or ('design_info' in locals() and design_info):
                col1, col2 = st.columns(2)
                
                with col1:
                    job_name = st.text_input("Job Name", value="New Embroidery Project")
                    customer_name = st.text_input("Customer Name", value="")
                    quantity = st.number_input("Quantity", min_value=1, max_value=10000, value=100, step=10)
                    thread_weight = st.selectbox("Thread Weight", ["40wt", "60wt"], index=0)
                    use_foam = st.checkbox("Use 3D Foam", value=False)
                    
                with col2:
                    active_heads = st.slider("Active Machine Heads", min_value=1, max_value=DEFAULT_MAX_HEADS, value=min(DEFAULT_MAX_HEADS, 10))
                    complex_production = st.checkbox("Complex Production", value=False, 
                                                  help="Check this for complex items that slow down production (e.g., hats, bags)")
                    coloreel_enabled = st.checkbox("Coloreel Enabled", value=False,
                                               help="Check this if using Coloreel thread coloring technology (max 2 heads)")
                    
                    # If Coloreel is enabled, limit active heads
                    if coloreel_enabled and active_heads > DEFAULT_COLOREEL_MAX_HEADS:
                        st.warning(f"Coloreel operation limits active heads to {DEFAULT_COLOREEL_MAX_HEADS}.")
                        active_heads = DEFAULT_COLOREEL_MAX_HEADS
                    
                    premium_product = st.checkbox("Premium Product", value=False,
                                              help="Check this for higher quality products that require more attention to detail")
                    
                    # Advanced pricing options
                    with st.expander("Advanced Pricing Options"):
                        digitizing_fee = st.number_input("Digitizing Fee ($)", 
                                                      min_value=0.0, 
                                                      max_value=500.0, 
                                                      value=DEFAULT_DIGITIZING_FEE, 
                                                      step=5.0)
                        minimum_total = st.number_input("Minimum Total Order ($)", 
                                                     min_value=0.0, 
                                                     max_value=1000.0, 
                                                     value=50.0, 
                                                     step=10.0)
                        markup_factor = st.slider("Markup Factor", 
                                               min_value=1.0, 
                                               max_value=5.0, 
                                               value=2.0, 
                                               step=0.1)
                
                # Compile all job inputs
                job_inputs = {
                    "job_name": job_name,
                    "customer_name": customer_name,
                    "quantity": quantity,
                    "thread_weight": thread_weight,
                    "use_foam": use_foam,
                    "active_heads": active_heads,
                    "complex_production": complex_production,
                    "coloreel_enabled": coloreel_enabled,
                    "premium_product": premium_product,
                    "digitizing_fee": digitizing_fee,
                    "minimum_total": minimum_total,
                    "markup_factor": markup_factor
                }
                
                # Calculate button
                calculate_button = st.button("Calculate Quote", type="primary")
                
                if calculate_button and 'design_info' in locals():
                    with st.spinner("Calculating..."):
                        # Calculate costs
                        cost_results = calculate_costs(design_info, job_inputs)
                        
                        # Store in session state
                        st.session_state.design_info = design_info
                        st.session_state.job_inputs = job_inputs
                        st.session_state.cost_results = cost_results
                        
                        # Jump to step 3
                        st.rerun()
        
        # Step 3: Quote Results
        with st.expander("Step 3: Quote Results", expanded='cost_results' in st.session_state):
            if 'cost_results' in st.session_state:
                design_info = st.session_state.design_info
                job_inputs = st.session_state.job_inputs
                cost_results = st.session_state.cost_results
                
                # Display the results
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("Quote Summary")
                    st.info(f"Job: {job_inputs['job_name']}")
                    st.info(f"Customer: {job_inputs['customer_name']}")
                    st.info(f"Quantity: {job_inputs['quantity']} pieces")
                    
                    # Key metrics
                    st.metric("Total Order Price", f"${cost_results['total_cost']:.2f}")
                    st.metric("Price Per Item", f"${cost_results['price_per_piece']:.2f}")
                
                with col2:
                    st.subheader("Detailed Breakdown")
                    
                    # Material costs
                    st.write("Material Costs:")
                    material_df = pd.DataFrame({
                        'Item': ['Thread', 'Stabilizer', 'Foam', 'Total Materials'],
                        'Cost': [
                            f"${cost_results['total_thread_cost']:.2f}",
                            f"${cost_results['stabilizer_cost']:.2f}",
                            f"${cost_results['foam_cost']:.2f}",
                            f"${cost_results['base_materials_cost']:.2f}"
                        ]
                    })
                    st.dataframe(material_df, hide_index=True)
                    
                    # Production details
                    st.write("Production Details:")
                    production_df = pd.DataFrame({
                        'Item': ['Production Time', 'Labor Cost', 'Machine Cost', 'Digitizing Fee'],
                        'Value': [
                            f"{cost_results['total_production_time_minutes']:.1f} min",
                            f"${cost_results['labor_cost']:.2f}",
                            f"${cost_results['machine_cost']:.2f}",
                            f"${cost_results['digitizing_fee']:.2f}"
                        ]
                    })
                    st.dataframe(production_df, hide_index=True)
                
                # Pricing summary
                st.subheader("Pricing Summary")
                pricing_df = pd.DataFrame({
                    'Item': ['Base Cost', 'Premium Factor', 'Markup Factor', 'Total Price'],
                    'Value': [
                        f"${cost_results['total_cost_before_markup']:.2f}",
                        f"{cost_results['premium_factor']:.2f}×",
                        f"{cost_results['markup_factor']:.2f}×",
                        f"${cost_results['total_cost']:.2f}"
                    ]
                })
                st.dataframe(pricing_df, hide_index=True)
                
                # Generate PDF quotes
                st.subheader("Generate Quote PDFs")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("Detailed Quote (Internal):")
                    detailed_pdf = generate_detailed_quote_pdf(design_info, job_inputs, cost_results)
                    st.markdown(get_download_link(detailed_pdf, f"internal_quote_{job_inputs['job_name'].replace(' ', '_')}.pdf", 
                                               "Download Internal Quote"), unsafe_allow_html=True)
                
                with col2:
                    st.write("Customer Quote:")
                    customer_pdf = generate_customer_quote_pdf(design_info, job_inputs, cost_results)
                    st.markdown(get_download_link(customer_pdf, f"customer_quote_{job_inputs['job_name'].replace(' ', '_')}.pdf", 
                                               "Download Customer Quote"), unsafe_allow_html=True)
                
                # Save quote button
                save_col1, save_col2 = st.columns([1, 3])
                with save_col1:
                    save_quote_button = st.button("Save Quote to History", key="save_quote_btn")
                
                if save_quote_button:
                    with st.spinner("Saving quote..."):
                        # Prepare quote data
                        quote_data = {
                            "job_name": job_inputs["job_name"],
                            "customer_name": job_inputs["customer_name"],
                            "stitch_count": design_info["stitch_count"],
                            "color_count": design_info["color_count"],
                            "quantity": job_inputs["quantity"],
                            "width_inches": design_info["width_inches"],
                            "height_inches": design_info["height_inches"],
                            "total_cost": cost_results["total_cost"],
                            "price_per_piece": cost_results["price_per_piece"]
                        }
                        
                        # Save to database
                        quote_id = database.save_quote(quote_data)
                        
                        if quote_id:
                            st.success(f"Quote saved successfully! Quote ID: {quote_id}")
                        else:
                            st.error("Error saving quote. Please try again.")
            else:
                st.info("Complete steps 1 and 2 to generate a quote.")
    
    # Tab 2: Quote History
    with tab2:
        st.title("Quote History")
        st.write("View and manage your recent quotes.")
        
        # Fetch recent quotes
        with st.spinner("Loading quote history..."):
            recent_quotes = database.get_recent_quotes(limit=20)
            
            if recent_quotes:
                # Prepare DataFrame
                df = pd.DataFrame(recent_quotes)
                
                # Format DataFrame
                df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
                df['total_cost'] = df['total_cost'].apply(lambda x: f"${x:.2f}")
                df['price_per_piece'] = df['price_per_piece'].apply(lambda x: f"${x:.2f}")
                
                # Rename columns
                df = df.rename(columns={
                    'job_name': 'Job Name',
                    'customer_name': 'Customer',
                    'stitch_count': 'Stitches',
                    'color_count': 'Colors',
                    'quantity': 'Qty',
                    'width_inches': 'Width"',
                    'height_inches': 'Height"',
                    'total_cost': 'Total',
                    'price_per_piece': 'Per Item',
                    'created_at': 'Date'
                })
                
                # Reorder columns
                columns = ['Date', 'Job Name', 'Customer', 'Stitches', 'Colors', 
                           'Qty', 'Width"', 'Height"', 'Total', 'Per Item']
                df = df[columns]
                
                # Display table
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                # TODO: Add functionality to view/recreate individual quotes in the future
                st.info("Select a quote to view details (Feature coming soon!)")
            else:
                st.info("No quotes found in history. Try creating a new quote first.")

    # Tab 3: Settings
    with tab3:
        st.title("Settings")
        st.write("Adjust application settings and parameters.")
        
        # Create tabs for different setting categories
        settings_tab1, settings_tab2, settings_tab3 = st.tabs(["Material Settings", "Machine Settings", "Labor Settings"])
        
        # Material Settings
        with settings_tab1:
            st.header("Material Settings")
            
            material_col1, material_col2 = st.columns(2)
            
            with material_col1:
                st.subheader("Thread Pricing")
                polyneon_5500_price = st.number_input("Polyneon 5500yd Spool Price ($)", 
                                                   min_value=1.0, 
                                                   max_value=50.0, 
                                                   value=float(material_settings.get("POLYNEON_5500YD_PRICE", {}).get("value", 9.69)), 
                                                   step=0.1,
                                                   format="%.2f")
                
                polyneon_1100_price = st.number_input("Polyneon 1100yd Spool Price ($)", 
                                                   min_value=0.5, 
                                                   max_value=20.0, 
                                                   value=float(material_settings.get("POLYNEON_1100YD_PRICE", {}).get("value", 3.19)), 
                                                   step=0.1,
                                                   format="%.2f")
            
            with material_col2:
                st.subheader("Other Materials")
                bobbin_144_price = st.number_input("Box of 144 Bobbins Price ($)", 
                                               min_value=10.0, 
                                               max_value=100.0, 
                                               value=float(material_settings.get("BOBBIN_144_PRICE", {}).get("value", 35.85)), 
                                               step=0.1,
                                               format="%.2f")
                
                bobbin_yards = st.number_input("Yards per Bobbin", 
                                           min_value=50, 
                                           max_value=300, 
                                           value=int(material_settings.get("BOBBIN_YARDS", {}).get("value", 124)), 
                                           step=1)
                
                foam_price = st.number_input("Foam Sheet Price ($)", 
                                         min_value=0.5, 
                                         max_value=10.0, 
                                         value=float(material_settings.get("FOAM_SHEET_PRICE", {}).get("value", 2.45)), 
                                         step=0.05,
                                         format="%.2f")
                
                stabilizer_price = st.number_input("Stabilizer Price per Piece ($)", 
                                               min_value=0.01, 
                                               max_value=1.0, 
                                               value=float(material_settings.get("STABILIZER_PRICE_PER_PIECE", {}).get("value", 0.18)), 
                                               step=0.01,
                                               format="%.2f")
            
            # Save button for material settings
            save_material_settings = st.button("Save Material Settings")
            if save_material_settings:
                with st.spinner("Saving material settings..."):
                    # Update all settings
                    success1 = database.update_setting("material_settings", "POLYNEON_5500YD_PRICE", polyneon_5500_price)
                    success2 = database.update_setting("material_settings", "POLYNEON_1100YD_PRICE", polyneon_1100_price)
                    success3 = database.update_setting("material_settings", "BOBBIN_144_PRICE", bobbin_144_price)
                    success4 = database.update_setting("material_settings", "BOBBIN_YARDS", bobbin_yards)
                    success5 = database.update_setting("material_settings", "FOAM_SHEET_PRICE", foam_price)
                    success6 = database.update_setting("material_settings", "STABILIZER_PRICE_PER_PIECE", stabilizer_price)
                    
                    if all([success1, success2, success3, success4, success5, success6]):
                        st.success("Material settings saved successfully!")
                        st.info("The page will refresh in 2 seconds...")
                        
                        # Add a slight delay before refreshing to show the success message
                        import time
                        time.sleep(2)
                        
                        # Force Streamlit to rerun and update settings
                        st.rerun()
                    else:
                        st.error("Error saving some settings. Please try again.")
        
        # Machine Settings
        with settings_tab2:
            st.header("Machine Settings")
            
            machine_col1, machine_col2 = st.columns(2)
            
            with machine_col1:
                st.subheader("Stitch Speed")
                stitch_speed_40wt = st.number_input("Default Stitch Speed 40wt (rpm)", 
                                                 min_value=100, 
                                                 max_value=1500, 
                                                 value=int(machine_settings.get("DEFAULT_STITCH_SPEED_40WT", {}).get("value", 750)), 
                                                 step=50)
                
                stitch_speed_60wt = st.number_input("Default Stitch Speed 60wt (rpm)", 
                                                 min_value=100, 
                                                 max_value=1500, 
                                                 value=int(machine_settings.get("DEFAULT_STITCH_SPEED_60WT", {}).get("value", 400)), 
                                                 step=50)
                
                hooping_time = st.number_input("Hooping Time (seconds per piece)", 
                                           min_value=10, 
                                           max_value=300, 
                                           value=int(machine_settings.get("HOOPING_TIME_DEFAULT", {}).get("value", 50)), 
                                           step=5)
            
            with machine_col2:
                st.subheader("Machine Configuration")
                max_heads = st.number_input("Maximum Machine Heads", 
                                         min_value=1, 
                                         max_value=50, 
                                         value=int(machine_settings.get("DEFAULT_MAX_HEADS", {}).get("value", 15)), 
                                         step=1)
                
                coloreel_max_heads = st.number_input("Maximum Coloreel Heads", 
                                                  min_value=1, 
                                                  max_value=10, 
                                                  value=int(machine_settings.get("DEFAULT_COLOREEL_MAX_HEADS", {}).get("value", 2)), 
                                                  step=1)
                
                st.subheader("Default Productivity Rates")
                productivity_rate = st.slider("Standard Productivity Rate", 
                                           min_value=0.5, 
                                           max_value=1.0, 
                                           value=float(machine_settings.get("DEFAULT_PRODUCTIVITY_RATE", {}).get("value", 1.0)), 
                                           step=0.05,
                                           format="%.2f")
                
                complex_productivity_rate = st.slider("Complex Production Rate", 
                                                   min_value=0.3, 
                                                   max_value=1.0, 
                                                   value=float(machine_settings.get("DEFAULT_COMPLEX_PRODUCTIVITY_RATE", {}).get("value", 0.8)), 
                                                   step=0.05,
                                                   format="%.2f")
                
                coloreel_productivity_rate = st.slider("Coloreel Productivity Rate", 
                                                    min_value=0.3, 
                                                    max_value=1.0, 
                                                    value=float(machine_settings.get("DEFAULT_COLOREEL_PRODUCTIVITY_RATE", {}).get("value", 0.75)), 
                                                    step=0.05,
                                                    format="%.2f")
                
                digitizing_fee = st.number_input("Default Digitizing Fee ($)", 
                                             min_value=0.0, 
                                             max_value=300.0, 
                                             value=float(machine_settings.get("DEFAULT_DIGITIZING_FEE", {}).get("value", 25.0)), 
                                             step=5.0,
                                             format="%.2f")
            
            # Save button for machine settings
            save_machine_settings = st.button("Save Machine Settings")
            if save_machine_settings:
                with st.spinner("Saving machine settings..."):
                    # Update all settings
                    success1 = database.update_setting("machine_settings", "DEFAULT_STITCH_SPEED_40WT", stitch_speed_40wt)
                    success2 = database.update_setting("machine_settings", "DEFAULT_STITCH_SPEED_60WT", stitch_speed_60wt)
                    success3 = database.update_setting("machine_settings", "DEFAULT_MAX_HEADS", max_heads)
                    success4 = database.update_setting("machine_settings", "DEFAULT_COLOREEL_MAX_HEADS", coloreel_max_heads)
                    success5 = database.update_setting("machine_settings", "HOOPING_TIME_DEFAULT", hooping_time)
                    success6 = database.update_setting("machine_settings", "DEFAULT_PRODUCTIVITY_RATE", productivity_rate)
                    success7 = database.update_setting("machine_settings", "DEFAULT_COMPLEX_PRODUCTIVITY_RATE", complex_productivity_rate)
                    success8 = database.update_setting("machine_settings", "DEFAULT_COLOREEL_PRODUCTIVITY_RATE", coloreel_productivity_rate)
                    success9 = database.update_setting("machine_settings", "DEFAULT_DIGITIZING_FEE", digitizing_fee)
                    
                    if all([success1, success2, success3, success4, success5, success6, success7, success8, success9]):
                        st.success("Machine settings saved successfully!")
                        st.info("The page will refresh in 2 seconds...")
                        
                        # Add a slight delay before refreshing to show the success message
                        import time
                        time.sleep(2)
                        
                        # Force Streamlit to rerun and update settings
                        st.rerun()
                    else:
                        st.error("Error saving some settings. Please try again.")
        
        # Labor Settings
        with settings_tab3:
            st.header("Labor Settings")
            
            labor_col1, labor_col2 = st.columns(2)
            
            with labor_col1:
                st.subheader("Default Labor Rate")
                labor_rate = st.number_input("Default Hourly Labor Rate ($)", 
                                         min_value=5.0, 
                                         max_value=100.0, 
                                         value=float(labor_settings.get("HOURLY_LABOR_RATE", {}).get("value", 25)), 
                                         step=0.5,
                                         format="%.2f")
                
                # Save button for labor rate
                save_labor_rate = st.button("Save Labor Rate")
                if save_labor_rate:
                    with st.spinner("Saving labor rate..."):
                        success = database.update_setting("labor_settings", "HOURLY_LABOR_RATE", labor_rate)
                        
                        if success:
                            st.success("Labor rate saved successfully!")
                            st.info("The page will refresh in 2 seconds...")
                            
                            # Add a slight delay before refreshing to show the success message
                            import time
                            time.sleep(2)
                            
                            # Force Streamlit to rerun and update settings
                            st.rerun()
                        else:
                            st.error("Error saving labor rate. Please try again.")
            
            with labor_col2:
                st.subheader("Workers")
                
                # Load workers from database
                workers = database.get_labor_workers()
                
                if workers:
                    # Display workers in a table
                    workers_df = pd.DataFrame(workers)
                    workers_df['hourly_rate'] = workers_df['hourly_rate'].apply(lambda x: f"${x:.2f}")
                    workers_df['is_active'] = workers_df['is_active'].apply(lambda x: "Active" if x else "Inactive")
                    workers_df = workers_df.rename(columns={'name': 'Name', 'hourly_rate': 'Hourly Rate', 'is_active': 'Status'})
                    
                    st.dataframe(workers_df[['Name', 'Hourly Rate', 'Status']], hide_index=True)
                    
                    # Multi-select for workers
                    selected_worker_ids = st.multiselect("Select workers to edit:", 
                                                      options=workers_df.index.tolist(),
                                                      format_func=lambda x: workers[x]['name'])
                    
                    if selected_worker_ids:
                        # For now, just allow editing the first selected worker
                        selected_worker = workers[selected_worker_ids[0]]
                        
                        st.subheader(f"Edit Worker: {selected_worker['name']}")
                        
                        edit_name = st.text_input("Name", value=selected_worker['name'])
                        edit_rate = st.number_input("Hourly Rate ($)", 
                                                 min_value=5.0, 
                                                 max_value=100.0, 
                                                 value=float(selected_worker['hourly_rate']), 
                                                 step=0.5,
                                                 format="%.2f")
                        edit_status = st.checkbox("Active", value=selected_worker['is_active'])
                        
                        update_worker = st.button("Update Worker")
                        delete_worker = st.button("Delete Worker", type="secondary")
                        
                        if update_worker:
                            with st.spinner("Updating worker..."):
                                success = database.update_labor_worker(
                                    selected_worker['id'], 
                                    name=edit_name, 
                                    hourly_rate=edit_rate, 
                                    is_active=edit_status
                                )
                                
                                if success:
                                    st.success(f"Worker {edit_name} updated successfully!")
                                    st.info("The page will refresh in 2 seconds...")
                                    
                                    # Add a slight delay before refreshing
                                    import time
                                    time.sleep(2)
                                    
                                    # Force Streamlit to rerun
                                    st.rerun()
                                else:
                                    st.error("Error updating worker. Please try again.")
                        
                        if delete_worker:
                            with st.spinner("Deleting worker..."):
                                success = database.delete_labor_worker(selected_worker['id'])
                                
                                if success:
                                    st.success(f"Worker {selected_worker['name']} deleted successfully!")
                                    st.info("The page will refresh in 2 seconds...")
                                    
                                    # Add a slight delay before refreshing
                                    import time
                                    time.sleep(2)
                                    
                                    # Force Streamlit to rerun
                                    st.rerun()
                                else:
                                    st.error("Error deleting worker. Please try again.")
                
                # Add new worker form
                st.subheader("Add New Worker")
                
                new_name = st.text_input("Name", key="new_worker_name")
                new_rate = st.number_input("Hourly Rate ($)", 
                                        min_value=5.0, 
                                        max_value=100.0, 
                                        value=25.0, 
                                        step=0.5,
                                        format="%.2f",
                                        key="new_worker_rate")
                new_status = st.checkbox("Active", value=True, key="new_worker_status")
                
                add_worker = st.button("Add Worker")
                
                if add_worker and new_name:
                    with st.spinner("Adding worker..."):
                        worker_id = database.add_labor_worker(new_name, new_rate, new_status)
                        
                        if worker_id:
                            st.success(f"Worker {new_name} added successfully!")
                            st.info("The page will refresh in 2 seconds...")
                            
                            # Add a slight delay before refreshing
                            import time
                            time.sleep(2)
                            
                            # Force Streamlit to rerun
                            st.rerun()
                        else:
                            st.error("Error adding worker. Please try again.")
    
    # Tab 4: Admin
    with tab4:
        st.title("Admin")
        st.write("Administrative functions and advanced settings.")
        
        # QuickBooks functionality has been removed
        
        # System information
        st.header("System Information")
        st.write("Basic system information about the application environment.")
        
        # Create a grid for system info
        info_col1, info_col2 = st.columns(2)
        
        with info_col1:
            st.subheader("Application")
            st.info(f"Version: 1.0.0")
            st.info(f"Last Updated: {datetime.datetime.now().strftime('%Y-%m-%d')}")
            st.info(f"Server Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        with info_col2:
            st.subheader("Database")
            st.info("Type: PostgreSQL")
            st.info("Status: Connected")
            # Show database stats
            import psycopg2
            conn = None
            try:
                conn = database.get_connection()
                if conn:
                    result = conn.execute(text("SELECT COUNT(*) FROM quotes"))
                    quote_count = result.scalar()
                    st.info(f"Saved Quotes: {quote_count}")
                else:
                    st.error("Unable to connect to database for stats")
            except Exception as e:
                st.error(f"Error getting database stats: {str(e)}")
            finally:
                if conn:
                    conn.close()

if __name__ == "__main__":
    main()
