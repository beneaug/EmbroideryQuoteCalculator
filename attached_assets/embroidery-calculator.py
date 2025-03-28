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
    page_title="Embroidery Cost Calculator",
    page_icon="🧵",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for a clean, modern look
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Helvetica:wght@300;400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Helvetica', sans-serif;
    }
    
    h1, h2, h3, h4, h5 {
        font-family: 'Helvetica', sans-serif;
        font-weight: 700;
    }
    
    .stButton button {
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
        width: 100%;
    }
    
    .section-header {
        font-size: 1.3rem;
        font-weight: bold;
        margin-bottom: 1rem;
        margin-top: 2rem;
        color: #333;
    }
    
    .info-text {
        color: #555;
        font-size: 0.8rem;
    }
    
    .data-value {
        font-size: 1.8rem;
        font-weight: bold;
    }
    
    .data-label {
        font-size: 0.9rem;
        color: #555;
    }
    
    .card {
        border-radius: 5px;
        padding: 1.5rem;
        background-color: #fff;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 1rem;
    }
    
    .cost-value {
        font-size: 2rem;
        font-weight: bold;
        color: #333;
    }
    
    .cost-description {
        font-size: 0.8rem;
        color: #555;
    }

    .metric-container {
        padding: 0.8rem 0;
    }
    
    .complexity-bar {
        height: 8px;
        background-color: #f0f0f0;
        border-radius: 4px;
        margin: 10px 0;
        overflow: hidden;
    }
    
    .complexity-fill {
        height: 100%;
        background: linear-gradient(90deg, #ff4d4d, #ffa500);
        border-radius: 4px;
    }
    
    .complexity-note {
        background-color: #e9f5ff;
        padding: 10px;
        border-radius: 5px;
        border-left: 4px solid #1890ff;
        font-size: 0.9rem;
    }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 1px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: white;
        border-radius: 4px 4px 0 0;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: white;
        border-bottom: 2px solid #ff4b4b;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Input fields styling */
    div[data-baseweb="input"] input {
        border-radius: 5px;
    }
    
    /* File uploader styling */
    .uploadedFile {
        border: 1px solid #f0f0f0;
        border-radius: 5px;
        padding: 10px;
    }
    
    /* Container styling */
    .block-container {
        padding-top: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    /* Tooltip icon */
    .tooltip-icon {
        color: #ccc;
        font-size: 16px;
        cursor: pointer;
    }
    
    /* Number input styling */
    input[type="number"] {
        padding: 10px;
        border-radius: 5px;
        border: 1px solid #ddd;
    }
</style>
""", unsafe_allow_html=True)

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

# Initialize session state for history
if 'history' not in st.session_state:
    st.session_state.history = []

# Title
st.title("Embroidery Cost Calculator")

# Tabs for New Calculation and History
tab1, tab2 = st.tabs(["New Calculation", "History"])

with tab1:
    # Machine Configuration Section
    st.markdown('<div class="section-header">Machine Configuration</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.markdown("Active Heads")
        max_heads = st.slider("", 1, DEFAULT_MAX_HEADS, DEFAULT_MAX_HEADS, label_visibility="collapsed")
        st.markdown('<div class="info-text">More active heads = faster production</div>', unsafe_allow_html=True)
    
    with col2:
        coloreel_enabled = st.checkbox("Use Coloreel ITCU", value=False)
        if coloreel_enabled and max_heads > DEFAULT_COLOREEL_MAX_HEADS:
            max_heads = DEFAULT_COLOREEL_MAX_HEADS
            st.warning(f"Max heads limited to {DEFAULT_COLOREEL_MAX_HEADS} with Coloreel enabled")
    
    with col3:
        st.markdown("Machine Status")
        st.markdown('<div class="data-value">{} heads</div>'.format(max_heads), unsafe_allow_html=True)
        st.markdown('<div class="data-label">Production Capacity</div>', unsafe_allow_html=True)
    
    st.markdown('<hr>', unsafe_allow_html=True)
    
    # Design Upload Section
    st.markdown('<div class="section-header">Design Upload</div>', unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Upload DST/U01 File", type=["dst", "u01"],
                                   help="Upload your embroidery design file")
    
    # Process the uploaded file
    design_info = None
    if uploaded_file is not None:
        # Function to parse embroidery file
        def parse_embroidery_file(uploaded_file):
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
        
        # Function to render embroidery design preview
        def render_design_preview(pattern, width=400, height=400, use_foam=False, foam_thickness_mm=3):
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
                
                # Skip jump stitches in visualization
                if command == pyembroidery.JUMP:
                    last_x, last_y = x, y
                    continue
                
                # Draw line if we have a previous point
                if last_x is not None and last_y is not None:
                    draw.line(
                        [
                            (last_x - min_x) * scale + offset_x,
                            (last_y - min_y) * scale + offset_y,
                            (x - min_x) * scale + offset_x,
                            (y - min_y) * scale + offset_y
                        ],
                        fill=current_color,
                        width=1
                    )
                
                last_x, last_y = x, y
            
            return img
        
        # Parse the file
        design_info = parse_embroidery_file(uploaded_file)
        
        if design_info:
            # Display file information
            st.text(f"{uploaded_file.name} {round(uploaded_file.size/1024, 1)}KB")
            
            # Thread Colors Section
            st.markdown('<div class="section-header">Thread Colors</div>', unsafe_allow_html=True)
            
            col1, col2 = st.columns([1, 3])
            
            with col1:
                st.markdown("Number of Colors")
                num_colors = st.number_input("", min_value=1, max_value=15, value=design_info["color_changes"], label_visibility="collapsed")
                
                # Display color pickers for each color
                for i in range(num_colors):
                    st.markdown(f"Color {i+1}")
                    color = st.color_picker("", "#000000", key=f"color_{i}", label_visibility="collapsed")
            
            # Design Information and Preview
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown('<div class="section-header">Design Information</div>', unsafe_allow_html=True)
                
                col1_1, col1_2 = st.columns(2)
                
                with col1_1:
                    st.markdown('<div class="data-label">Stitch Count</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{design_info["stitch_count"]:,}</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="data-label">Design Width</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{design_info["width_mm"]:.1f}mm</div>', unsafe_allow_html=True)
                
                with col1_2:
                    st.markdown('<div class="data-label">Thread Length</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{design_info["thread_length_yards"]:.1f} yards</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="data-label">Design Height</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{design_info["height_mm"]:.1f}mm</div>', unsafe_allow_html=True)
                
                # Complexity Analysis
                st.markdown('<div class="section-header">Complexity Analysis</div>', unsafe_allow_html=True)
                
                complexity_score = design_info["complexity_score"]
                st.markdown(f'<div class="complexity-bar"><div class="complexity-fill" style="width: {complexity_score}%;"></div></div>', unsafe_allow_html=True)
                st.markdown(f'Complexity Score: {complexity_score:.2f}/100', unsafe_allow_html=False)
                
                # Complexity description based on score
                complexity_desc = ""
                if complexity_score < 30:
                    complexity_desc = "Simple design with low stitch count and minimal technical requirements"
                elif complexity_score < 50:
                    complexity_desc = "Moderately complex design with average stitch density"
                elif complexity_score < 70:
                    complexity_desc = "Complex design requiring careful attention to detail"
                else:
                    complexity_desc = "Very complex design with high stitch density and technical challenges"
                
                st.markdown(f'<div class="complexity-note">{complexity_desc}</div>', unsafe_allow_html=True)
                
                # Thread weight selection
                st.markdown("Thread Weight")
                thread_weight = st.selectbox("", options=[40, 60], index=0, label_visibility="collapsed")
                
                # 3D Foam option
                use_foam = st.checkbox("Use 3D Foam")
                
                # Quantity
                st.markdown("Quantity")
                quantity = st.number_input("", min_value=1, value=1, label_visibility="collapsed")
            
            with col2:
                st.markdown('<div class="section-header">Design Preview</div>', unsafe_allow_html=True)
                
                # Render and display the design preview
                preview_img = render_design_preview(design_info["pattern"], width=500, height=500, use_foam=use_foam)
                st.image(preview_img, use_column_width=True)
            
            # Calculate costs and production information
            if design_info is not None:
                # Function to calculate costs
                def calculate_costs(design_info, quantity, thread_weight, use_foam, active_heads, num_colors):
                    # Calculate thread costs
                    thread_yards_per_piece = design_info["thread_length_yards"] * 1.05  # Add 5% buffer
                    total_thread_yards = thread_yards_per_piece * quantity
                    
                    # Spools needed calculation - one spool per head for each color
                    spools_per_head = num_colors
                    total_spools = spools_per_head * active_heads
                    
                    # Calculate thread cost
                    thread_cost = total_spools * POLYNEON_5500YD_PRICE  # Always using 5500yd spools for production
                    
                    # Calculate bobbin costs
                    bobbin_yards_per_piece = design_info["thread_length_yards"] * 0.4  # Estimate: 40% of top thread
                    total_bobbin_yards = bobbin_yards_per_piece * quantity
                    bobbins_needed = math.ceil(total_bobbin_yards / BOBBIN_YARDS)
                    bobbin_cost = (bobbins_needed / 144) * BOBBIN_144_PRICE
                    
                    # Calculate foam costs if applicable
                    foam_cost = 0
                    foam_sheets_needed = 0
                    pieces_per_sheet = 0
                    
                    if use_foam:
                        # Add 0.5 inches to design dimensions for foam
                        design_width_with_margin = design_info["width_inches"] + 1  # 0.5 inches on each side
                        design_height_with_margin = design_info["height_inches"] + 1  # 0.5 inches on each side
                        
                        # Calculate how many foam pieces we can cut from one sheet
                        pieces_per_row = math.floor(FOAM_SHEET_SIZE[0] / design_width_with_margin)
                        pieces_per_column = math.floor(FOAM_SHEET_SIZE[1] / design_height_with_margin)
                        pieces_per_sheet = pieces_per_row * pieces_per_column
                        
                        # Calculate how many sheets we need
                        foam_sheets_needed = math.ceil(quantity / pieces_per_sheet)
                        foam_cost = foam_sheets_needed * FOAM_SHEET_PRICE
                    
                    # Calculate stitching time (in minutes)
                    stitch_speed = DEFAULT_STITCH_SPEED_40WT if thread_weight == 40 else DEFAULT_STITCH_SPEED_60WT
                    stitch_time_per_piece_minutes = design_info["stitch_count"] / stitch_speed
                    
                    # Calculate total cycles (batches)
                    pieces_per_cycle = active_heads
                    total_cycles = math.ceil(quantity / pieces_per_cycle)
                    
                    # Calculate hooping time
                    hooping_time_per_piece_seconds = HOOPING_TIME_DEFAULT
                    hooping_time_per_cycle_minutes = (hooping_time_per_piece_seconds * pieces_per_cycle) / 60
                    
                    # Calculate total production time
                    # We assume concurrent operation (hooping while stitching)
                    cycle_time_minutes = stitch_time_per_piece_minutes
                    buffer_time_minutes = 1.1  # Add 1.1 minutes buffer between cycles
                    total_runtime_minutes = (cycle_time_minutes * total_cycles) + (buffer_time_minutes * (total_cycles - 1)) if total_cycles > 1 else cycle_time_minutes
                    
                    # Calculate total costs
                    total_material_cost = thread_cost + bobbin_cost + foam_cost
                    
                    return {
                        "thread_yards_per_piece": thread_yards_per_piece,
                        "total_thread_yards": total_thread_yards,
                        "spools_per_head": spools_per_head,
                        "total_spools": total_spools,
                        "thread_cost": thread_cost,
                        "bobbin_yards_per_piece": bobbin_yards_per_piece,
                        "total_bobbin_yards": total_bobbin_yards,
                        "bobbins_needed": bobbins_needed,
                        "bobbin_cost": bobbin_cost,
                        "foam_cost": foam_cost,
                        "foam_sheets_needed": foam_sheets_needed,
                        "pieces_per_sheet": pieces_per_sheet if use_foam else 0,
                        "pieces_per_cycle": pieces_per_cycle,
                        "total_cycles": total_cycles,
                        "stitch_time_per_piece_minutes": stitch_time_per_piece_minutes,
                        "hooping_time_per_cycle_minutes": hooping_time_per_cycle_minutes,
                        "cycle_time_minutes": cycle_time_minutes,
                        "total_runtime_minutes": total_runtime_minutes,
                        "total_material_cost": total_material_cost
                    }
                
                # Calculate costs
                cost_info = calculate_costs(
                    design_info,
                    quantity,
                    thread_weight,
                    use_foam,
                    max_heads,
                    num_colors
                )
                
                # Production Information Section
                st.markdown('<div class="section-header">Production Information</div>', unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown('<div class="data-label">Total Cycles</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{cost_info["total_cycles"]}</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="data-label">Pieces per Cycle</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{cost_info["pieces_per_cycle"]}</div>', unsafe_allow_html=True)
                
                with col2:
                    st.markdown('<div class="data-label">Stitch Time</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{cost_info["stitch_time_per_piece_minutes"]:.1f} min</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="data-label">Hooping Time/Cycle</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{cost_info["hooping_time_per_cycle_minutes"]:.1f} min</div>', unsafe_allow_html=True)
                    st.markdown('<div class="info-text">Operations run concurrently</div>', unsafe_allow_html=True)
                
                with col3:
                    st.markdown('<div class="data-label">Cycle Time</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{cost_info["cycle_time_minutes"]:.1f} min</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="data-label">Total Runtime</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="data-value">{cost_info["total_runtime_minutes"]:.1f} min</div>', unsafe_allow_html=True)
                    st.markdown('<div class="info-text">Includes 1.1 min buffer between cycles</div>', unsafe_allow_html=True)
                
                # Cost Breakdown Section
                st.markdown('<div class="section-header">Cost Breakdown <span class="tooltip-icon" title="Costs are calculated based on Madeira USA pricing">ℹ️</span></div>', unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown('<div class="data-label">Thread Cost</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="cost-value">${cost_info["thread_cost"]:.2f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="cost-description">{cost_info["spools_per_head"]} spools per head ({num_colors} colors)<br>Total: {cost_info["total_spools"]} spools</div>', unsafe_allow_html=True)
                
                with col2:
                    st.markdown('<div class="data-label">Bobbin Cost</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="cost-value">${cost_info["bobbin_cost"]:.2f}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="cost-description">Using {math.ceil(cost_info["bobbins_needed"])} bobbins</div>', unsafe_allow_html=True)
                
                with col3:
                    st.markdown('<div class="data-label">Total Cost</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="cost-value">${cost_info["total_material_cost"]:.2f}</div>', unsafe_allow_html=True)
                
                # Action buttons
                col1, col2 = st.columns(2)
                
                with col1:
                    # Save to history button
                    if st.button("Save Calculation"):
                        # Create history entry
                        history_entry = {
                            "timestamp": datetime.datetime.now(),
                            "filename": uploaded_file.name,
                            "design_info": design_info,
                            "cost_info": cost_info,
                            "settings": {
                                "quantity": quantity,
                                "thread_weight": thread_weight,
                                "use_foam": use_foam,
                                "active_heads": max_heads,
                                "coloreel_enabled": coloreel_enabled,
                                "num_colors": num_colors
                            }
                        }
                        
                        # Add to history
                        st.session_state.history.append(history_entry)
                        st.success("Calculation saved to history!")
                
                with col2:
                    # Function to generate PDF report
                    def generate_pdf_report(design_info, cost_info, settings):
                        buffer = io.BytesIO()
                        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
                        
                        # Define styles
                        styles = getSampleStyleSheet()
                        title_style = styles["Heading1"]
                        title_style.fontName = "Helvetica-Bold"
                        
                        subtitle_style = styles["Heading2"]
                        subtitle_style.fontName = "Helvetica-Bold"
                        
                        normal_style = styles["Normal"]
                        normal_style.fontName = "Helvetica"
                        
                        # Build the story
                        story = []
                        
                        # Title
                        story.append(Paragraph("Embroidery Price Calculator Report", title_style))
                        story.append(Spacer(1, 0.25 * inch))
                        
                        # Design information
                        story.append(Paragraph("Design Information", subtitle_style))
                        
                        design_data = [
                            ["Stitch Count", f"{design_info['stitch_count']}"],
                            ["Colors", f"{settings['num_colors']}"],
                            ["Dimensions", f"{design_info['width_mm']:.1f}mm × {design_info['height_mm']:.1f}mm"],
                            ["Thread Length", f"{design_info['thread_length_yards']:.1f} yards"],
                            ["Complexity Score", f"{design_info['complexity_score']:.1f}/100"],
                            ["Quantity", f"{settings['quantity']}"],
                            ["Thread Weight", f"{settings['thread_weight']}wt"],
                            ["3D Foam", "Yes" if settings['use_foam'] else "No"],
                            ["Active Heads", f"{settings['active_heads']}"],
                            ["Coloreel Enabled", "Yes" if settings['coloreel_enabled'] else "No"]
                        ]
                        
                        design_table = Table(design_data, colWidths=[2 * inch, 3 * inch])
                        design_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                        ]))
                        
                        story.append(design_table)
                        story.append(Spacer(1, 0.25 * inch))
                        
                        # Production information
                        story.append(Paragraph("Production Information", subtitle_style))
                        
                        production_data = [
                            ["Total Cycles", f"{cost_info['total_cycles']}"],
                            ["Pieces per Cycle", f"{cost_info['pieces_per_cycle']}"],
                            ["Stitch Time", f"{cost_info['stitch_time_per_piece_minutes']:.1f} minutes"],
                            ["Hooping Time per Cycle", f"{cost_info['hooping_time_per_cycle_minutes']:.1f} minutes"],
                            ["Cycle Time", f"{cost_info['cycle_time_minutes']:.1f} minutes"],
                            ["Total Runtime", f"{cost_info['total_runtime_minutes']:.1f} minutes ({cost_info['total_runtime_minutes'] / 60:.1f} hours)"]
                        ]
                        
                        production_table = Table(production_data, colWidths=[2 * inch, 3 * inch])
                        production_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                        ]))
                        
                        story.append(production_table)
                        story.append(Spacer(1, 0.25 * inch))
                        
                        # Material costs
                        story.append(Paragraph("Cost Breakdown", subtitle_style))
                        
                        cost_data = [
                            ["Item", "Details", "Cost"],
                            ["Thread", f"{cost_info['spools_per_head']} spools per head × {settings['active_heads']} heads", f"${cost_info['thread_cost']:.2f}"],
                            ["Bobbin", f"{math.ceil(cost_info['bobbins_needed'])} bobbins", f"${cost_info['bobbin_cost']:.2f}"]
                        ]
                        
                        if settings['use_foam']:
                            cost_data.append(["3D Foam", f"{cost_info['foam_sheets_needed']} sheets", f"${cost_info['foam_cost']:.2f}"])
                        
                        cost_data.append(["Total", "", f"${cost_info['total_material_cost']:.2f}"])
                        
                        cost_table = Table(cost_data, colWidths=[1.5 * inch, 2.5 * inch, 1 * inch])
                        cost_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                        ]))
                        
                        story.append(cost_table)
                        story.append(Spacer(1, 0.5 * inch))
                        
                        # Notes
                        story.append(Paragraph("Notes", subtitle_style))
                        
                        notes = [
                            "• Thread prices are based on Madeira Polyneon 5500yd spools at $9.69 each",
                            "• Bobbin prices are based on 144-count boxes at $35.85 ($0.25 per bobbin)",
                            f"• Machine: Barudan BEKS-S1515C with {'Coloreel' if settings['coloreel_enabled'] else 'standard'} setup",
                            f"• Runtime calculated at {DEFAULT_STITCH_SPEED_40WT if settings['thread_weight'] == 40 else DEFAULT_STITCH_SPEED_60WT} RPM for {settings['thread_weight']}wt thread",
                            f"• Report generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        ]
                        
                        for note in notes:
                            story.append(Paragraph(note, normal_style))
                        
                        # Build the PDF
                        doc.build(story)
                        
                        buffer.seek(0)
                        return buffer
                    
                    # PDF export button
                    settings = {
                        "quantity": quantity,
                        "thread_weight": thread_weight,
                        "use_foam": use_foam,
                        "active_heads": max_heads,
                        "coloreel_enabled": coloreel_enabled,
                        "num_colors": num_colors
                    }
                    
                    pdf_buffer = generate_pdf_report(design_info, cost_info, settings)
                    
                    st.download_button(
                        label="Export PDF Report",
                        data=pdf_buffer,
                        file_name=f"embroidery_report_{uploaded_file.name.split('.')[0]}.pdf",
                        mime="application/pdf"
                    )

with tab2:
    # History tab content
    st.markdown('<div class="section-header">Calculation History</div>', unsafe_allow_html=True)
    
    if not st.session_state.history:
        st.info("No calculations saved yet. Complete a calculation and click 'Save Calculation' to add it to your history.")
    else:
        # Display history in reverse chronological order
        for i, entry in enumerate(reversed(st.session_state.history)):
            with st.expander(f"{entry['filename']} - {entry['timestamp'].strftime('%Y-%m-%d %H:%M')}"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### Design Information")
                    st.markdown(f"**Stitch Count:** {entry['design_info']['stitch_count']:,}")
                    st.markdown(f"**Colors:** {entry['settings']['num_colors']}")
                    st.markdown(f"**Dimensions:** {entry['design_info']['width_mm']:.1f}mm × {entry['design_info']['height_mm']:.1f}mm")
                    st.markdown(f"**Complexity:** {entry['design_info']['complexity_score']:.1f}/100")
                    st.markdown(f"**Quantity:** {entry['settings']['quantity']}")
                
                with col2:
                    st.markdown("### Cost Summary")
                    st.markdown(f"**Thread Cost:** ${entry['cost_info']['thread_cost']:.2f}")
                    st.markdown(f"**Bobbin Cost:** ${entry['cost_info']['bobbin_cost']:.2f}")
                    if entry['settings']['use_foam']:
                        st.markdown(f"**Foam Cost:** ${entry['cost_info']['foam_cost']:.2f}")
                    st.markdown(f"**Total Cost:** ${entry['cost_info']['total_material_cost']:.2f}")
                    st.markdown(f"**Runtime:** {entry['cost_info']['total_runtime_minutes']:.1f} minutes")
                
                # Regenerate PDF for this history entry
                settings = entry['settings']
                
                # Generate PDF report
                def generate_history_pdf(design_info, cost_info, settings):
                    buffer = io.BytesIO()
                    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
                    
                    # Define styles
                    styles = getSampleStyleSheet()
                    title_style = styles["Heading1"]
                    title_style.fontName = "Helvetica-Bold"
                    
                    subtitle_style = styles["Heading2"]
                    subtitle_style.fontName = "Helvetica-Bold"
                    
                    normal_style = styles["Normal"]
                    normal_style.fontName = "Helvetica"
                    
                    # Build the story
                    story = []
                    
                    # Title
                    story.append(Paragraph("Embroidery Price Calculator Report", title_style))
                    story.append(Spacer(1, 0.25 * inch))
                    
                    # Design information
                    story.append(Paragraph("Design Information", subtitle_style))
                    
                    design_data = [
                        ["Stitch Count", f"{design_info['stitch_count']}"],
                        ["Colors", f"{settings['num_colors']}"],
                        ["Dimensions", f"{design_info['width_mm']:.1f}mm × {design_info['height_mm']:.1f}mm"],
                        ["Thread Length", f"{design_info['thread_length_yards']:.1f} yards"],
                        ["Complexity Score", f"{design_info['complexity_score']:.1f}/100"],
                        ["Quantity", f"{settings['quantity']}"],
                        ["Thread Weight", f"{settings['thread_weight']}wt"],
                        ["3D Foam", "Yes" if settings['use_foam'] else "No"],
                        ["Active Heads", f"{settings['active_heads']}"],
                        ["Coloreel Enabled", "Yes" if settings['coloreel_enabled'] else "No"]
                    ]
                    
                    design_table = Table(design_data, colWidths=[2 * inch, 3 * inch])
                    design_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ]))
                    
                    story.append(design_table)
                    story.append(Spacer(1, 0.25 * inch))
                    
                    # Production information
                    story.append(Paragraph("Production Information", subtitle_style))
                    
                    production_data = [
                        ["Total Cycles", f"{cost_info['total_cycles']}"],
                        ["Pieces per Cycle", f"{cost_info['pieces_per_cycle']}"],
                        ["Stitch Time", f"{cost_info['stitch_time_per_piece_minutes']:.1f} minutes"],
                        ["Hooping Time per Cycle", f"{cost_info['hooping_time_per_cycle_minutes']:.1f} minutes"],
                        ["Cycle Time", f"{cost_info['cycle_time_minutes']:.1f} minutes"],
                        ["Total Runtime", f"{cost_info['total_runtime_minutes']:.1f} minutes ({cost_info['total_runtime_minutes'] / 60:.1f} hours)"]
                    ]
                    
                    production_table = Table(production_data, colWidths=[2 * inch, 3 * inch])
                    production_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ]))
                    
                    story.append(production_table)
                    story.append(Spacer(1, 0.25 * inch))
                    
                    # Material costs
                    story.append(Paragraph("Cost Breakdown", subtitle_style))
                    
                    cost_data = [
                        ["Item", "Details", "Cost"],
                        ["Thread", f"{cost_info['spools_per_head']} spools per head × {settings['active_heads']} heads", f"${cost_info['thread_cost']:.2f}"],
                        ["Bobbin", f"{math.ceil(cost_info['bobbins_needed'])} bobbins", f"${cost_info['bobbin_cost']:.2f}"]
                    ]
                    
                    if settings['use_foam']:
                        cost_data.append(["3D Foam", f"{cost_info['foam_sheets_needed']} sheets", f"${cost_info['foam_cost']:.2f}"])
                    
                    cost_data.append(["Total", "", f"${cost_info['total_material_cost']:.2f}"])
                    
                    cost_table = Table(cost_data, colWidths=[1.5 * inch, 2.5 * inch, 1 * inch])
                    cost_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                    ]))
                    
                    story.append(cost_table)
                    story.append(Spacer(1, 0.5 * inch))
                    
                    # Build the PDF
                    doc.build(story)
                    
                    buffer.seek(0)
                    return buffer
                
                pdf_buffer = generate_history_pdf(entry['design_info'], entry['cost_info'], settings)
                
                st.download_button(
                    label="Export PDF for this calculation",
                    data=pdf_buffer,
                    file_name=f"embroidery_history_{entry['timestamp'].strftime('%Y%m%d_%H%M')}_{entry['filename'].split('.')[0]}.pdf",
                    mime="application/pdf"
                )
