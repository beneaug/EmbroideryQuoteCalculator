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

# Set page config
st.set_page_config(
    page_title="Embroidery Quoting Tool",
    page_icon="🧵",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Constants
POLYNEON_5500YD_PRICE = 9.69
POLYNEON_1100YD_PRICE = 3.19
BOBBIN_144_PRICE = 35.85
BOBBIN_YARDS = 124
FOAM_SHEET_PRICE = 2.45
FOAM_SHEET_SIZE = (18, 12)  # inches
DEFAULT_STITCH_SPEED_40WT = 750  # rpm
DEFAULT_STITCH_SPEED_60WT = 400  # rpm
DEFAULT_MAX_HEADS = 15
DEFAULT_COLOREEL_MAX_HEADS = 2
HOOPING_TIME_DEFAULT = 50  # seconds
STABILIZER_PRICE_PER_PIECE = 0.18  # $0.18 per piece

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
    """Render a visual preview of the embroidery design"""
    # Calculate the scale factor to fit the design within the specified dimensions
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
    
    scale_x = (width - 40) / design_width if design_width > 0 else 1
    scale_y = (height - 40) / design_height if design_height > 0 else 1
    scale = min(scale_x, scale_y)
    
    # Create a new image with white background
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    
    # Draw design boundary if foam is used (add 0.5 inches around the design)
    if use_foam:
        # Convert 0.5 inches to pyembroidery units (0.1mm)
        foam_margin = int(0.5 * 25.4 * 10)
        
        # Calculate boundary with foam margin
        boundary_min_x = min_x - foam_margin
        boundary_min_y = min_y - foam_margin
        boundary_max_x = max_x + foam_margin
        boundary_max_y = max_y + foam_margin
        
        # Draw foam boundary
        boundary_x1 = (boundary_min_x - min_x) * scale + width // 2
        boundary_y1 = (boundary_min_y - min_y) * scale + height // 2
        boundary_x2 = (boundary_max_x - min_x) * scale + width // 2
        boundary_y2 = (boundary_max_y - min_y) * scale + height // 2
        
        draw.rectangle([boundary_x1, boundary_y1, boundary_x2, boundary_y2], outline='lightblue', width=2)
    
    # Center the design
    offset_x = width // 2
    offset_y = height // 2
    
    # Draw stitches
    current_color = (0, 0, 0)  # Default color is black
    last_x, last_y = None, None
    
    for stitch in stitches:
        x, y, command = stitch
        
        # Change color if needed
        if command == pyembroidery.COLOR_CHANGE:
            # Cycle through some distinct colors for visualization
            colors = [(0, 0, 0), (255, 0, 0), (0, 0, 255), (0, 128, 0), (128, 0, 128), (255, 165, 0)]
            current_color = colors[hash(str(current_color)) % len(colors)]
        
        # Skip jump stitches for cleaner visualization
        if command == pyembroidery.JUMP:
            last_x, last_y = (x - min_x) * scale + offset_x, (y - min_y) * scale + offset_y
            continue
        
        # Draw the stitch
        if last_x is not None and last_y is not None:
            draw.line(
                [last_x, last_y, (x - min_x) * scale + offset_x, (y - min_y) * scale + offset_y],
                fill=current_color,
                width=1
            )
        
        last_x, last_y = (x - min_x) * scale + offset_x, (y - min_y) * scale + offset_y
    
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
    # Stitching time (in minutes)
    stitching_time_minutes = stitch_count / stitch_speed
    
    # Hooping time (in minutes)
    hooping_time_minutes = HOOPING_TIME_DEFAULT / 60  # Convert seconds to minutes
    
    # Total production time per piece
    production_time_per_piece = stitching_time_minutes + hooping_time_minutes
    
    # Total production time for the batch, accounting for multiple heads
    pieces_per_run = min(active_heads, quantity)  # Can't use more heads than pieces
    runs_needed = math.ceil(quantity / pieces_per_run)
    
    total_production_time_minutes = runs_needed * production_time_per_piece
    total_production_time_hours = total_production_time_minutes / 60
    
    # 6. Labor cost (Assuming $25/hour)
    hourly_labor_rate = 25
    labor_cost = total_production_time_hours * hourly_labor_rate
    
    # 7. Total costs
    material_cost = thread_cost + bobbin_cost + stabilizer_cost + foam_cost
    direct_cost = material_cost + labor_cost
    
    # 8. Markup and final price
    profit_margin = direct_cost * (markup_percentage / 100)
    total_job_cost = direct_cost + profit_margin + setup_fee
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
        "total_job_cost": total_job_cost,
        "price_per_piece": price_per_piece,
        "runs_needed": runs_needed,
        "spools_required": spools_required,
        "bobbins_required": bobbins_required
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
        ["TOTAL JOB COST", f"${cost_results['total_job_cost']:.2f}"],
        ["Price Per Piece", f"${cost_results['price_per_piece']:.2f}"],
    ]
    
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
    
    if cost_results['setup_fee'] > 0:
        pricing_data = [
            ["Setup Fee", f"${cost_results['setup_fee']:.2f}"],
            ["Embroidery Cost", f"${(cost_results['total_job_cost'] - cost_results['setup_fee']):.2f}"],
            ["TOTAL", f"${cost_results['total_job_cost']:.2f}"],
            ["Price Per Piece", f"${cost_results['price_per_piece']:.2f}"],
        ]
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

# Main Application
def main():
    st.title("Embroidery Quoting Tool")
    
    # Tabs for New Quote and History
    tab1, tab2 = st.tabs(["Create Quote", "Quote History"])
    
    with tab1:
        # Step 1: File Upload Section
        st.header("Step 1: Upload Design File")
        uploaded_file = st.file_uploader("Upload DST File", type=["dst", "u01"],
                                      help="Upload your embroidery design file in DST or U01 format")
        
        if uploaded_file:
            # Parse the file and save in session state
            with st.spinner("Analyzing design file..."):
                st.session_state.design_info = parse_embroidery_file(uploaded_file)
            
            if st.session_state.design_info:
                # Display design information in an expandable section
                with st.expander("Design Information", expanded=True):
                    col1, col2 = st.columns([1, 1])
                    
                    # Basic design metrics
                    with col1:
                        st.metric("Stitch Count", f"{st.session_state.design_info['stitch_count']:,}")
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
                    
                    # Design preview
                    with col2:
                        # Checkbox for foam preview
                        preview_with_foam = st.checkbox("Preview with 3D foam margin", value=False)
                        
                        # Generate and display preview
                        preview_img = render_design_preview(
                            st.session_state.design_info["pattern"], 
                            width=400, 
                            height=400, 
                            use_foam=preview_with_foam
                        )
                        st.image(preview_img, caption="Design Preview", use_column_width=True)
        
        # Step 2: Job Information & Materials
        st.header("Step 2: Job Information & Materials")
        
        # Job Info Card
        st.subheader("Job Information")
        col1, col2 = st.columns(2)
        
        with col1:
            job_name = st.text_input("Job Name/Reference (Optional)", 
                                   help="A name to identify this quote (customer name, project name, etc.)")
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
        
        # Technical Settings Card
        st.subheader("Machine & Technical Settings")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            active_heads = st.slider("Machine Heads", 1, DEFAULT_MAX_HEADS, min(4, DEFAULT_MAX_HEADS), 
                                  help="Number of embroidery heads that will run simultaneously")
            
            coloreel_enabled = st.checkbox("Use Coloreel ITCU", value=False,
                                        help="Enable if using Coloreel instant thread coloring technology")
            
            if coloreel_enabled and active_heads > DEFAULT_COLOREEL_MAX_HEADS:
                active_heads = DEFAULT_COLOREEL_MAX_HEADS
                st.warning(f"Max heads limited to {DEFAULT_COLOREEL_MAX_HEADS} with Coloreel enabled")
        
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
        
        # Pricing Information Card
        st.subheader("Pricing Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            markup_percentage = st.slider("Markup Percentage", 0, 200, 40,
                                       help="Profit margin percentage to add to direct costs")
        
        with col2:
            setup_fee = st.number_input("Setup Fee ($)", min_value=0.0, value=0.0, step=5.0,
                                      help="One-time fee for setup, digitizing, etc.")
        
        # Calculate Button
        calculate_pressed = st.button("Calculate Quote", type="primary")
        
        if calculate_pressed and st.session_state.design_info:
            # Gather all inputs
            job_inputs = {
                "job_name": job_name,
                "quantity": quantity,
                "garment_type": garment_type,
                "fabric_type": fabric_type,
                "placement": placement,
                "active_heads": active_heads,
                "coloreel_enabled": coloreel_enabled,
                "thread_weight": thread_weight,
                "hoop_size": hoop_size,
                "color_count": color_count,
                "stabilizer_type": stabilizer_type,
                "use_foam": use_foam,
                "markup_percentage": markup_percentage,
                "setup_fee": setup_fee
            }
            
            # Calculate all costs
            with st.spinner("Calculating costs..."):
                cost_results = calculate_costs(st.session_state.design_info, job_inputs)
            
            # Save to history
            history_entry = {
                "timestamp": datetime.datetime.now(),
                "job_name": job_name if job_name else f"Quote {len(st.session_state.history) + 1}",
                "design_info": st.session_state.design_info.copy(),
                "job_inputs": job_inputs.copy(),
                "cost_results": cost_results.copy()
            }
            st.session_state.history.append(history_entry)
            
            # Display Results
            st.header("Quote Results")
            
            # Summary card
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("Total Job Cost", f"${cost_results['total_job_cost']:.2f}")
                st.metric("Price Per Piece", f"${cost_results['price_per_piece']:.2f}")
                st.metric("Production Time", f"{cost_results['production_time_hours']:.2f} hours")
            
            with col2:
                st.metric("Material Cost", f"${cost_results['material_cost']:.2f}")
                st.metric("Labor Cost", f"${cost_results['labor_cost']:.2f}")
                st.metric("Profit Margin", f"${cost_results['profit_margin']:.2f} ({markup_percentage}%)")
            
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
            
            # Generate PDFs
            detailed_pdf = generate_detailed_quote_pdf(st.session_state.design_info, job_inputs, cost_results)
            customer_pdf = generate_customer_quote_pdf(st.session_state.design_info, job_inputs, cost_results)
            
            # Download buttons
            st.subheader("Download Quotes")
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown(
                    get_download_link(detailed_pdf, f"internal_quote_{job_name}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf", "Download Internal Quote PDF"),
                    unsafe_allow_html=True
                )
            
            with col2:
                st.markdown(
                    get_download_link(customer_pdf, f"customer_quote_{job_name}_{datetime.datetime.now().strftime('%Y%m%d')}.pdf", "Download Customer Quote PDF"),
                    unsafe_allow_html=True
                )
        
        elif calculate_pressed and not st.session_state.design_info:
            st.error("Please upload a DST file first to generate a quote.")
    
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

if __name__ == "__main__":
    main()
