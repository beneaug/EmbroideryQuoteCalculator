"""
Multi-process runner for Embroidery Quoting Tool

This script runs both the Streamlit application and the Flask OAuth server
in separate processes, allowing them to work together while remaining isolated.
"""

import os
import sys
import logging
import subprocess
import time
from threading import Thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('embroidery_runner')

def run_streamlit_app():
    """Run the Streamlit application on port 5000"""
    logger.info("Starting Streamlit application...")
    cmd = ["streamlit", "run", "app.py", "--server.port", "5000", "--server.address", "0.0.0.0"]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Stream the output to the console
    for line in process.stdout:
        sys.stdout.write(f"[Streamlit] {line}")
    
    # If we get here, the process has terminated
    logger.warning("Streamlit process terminated")
    return process.wait()

def run_oauth_server():
    """Run the Flask OAuth server on port 8000"""
    logger.info("Starting OAuth callback server...")
    
    # Import the Flask app from oauth_server and run it
    from oauth_server import app
    
    # Run the Flask app without the built-in reloader (since we're managing it)
    app.run(host='0.0.0.0', port=8000, use_reloader=False, debug=False)

if __name__ == "__main__":
    logger.info("Starting Embroidery Quoting Tool...")
    
    # Create and start the Streamlit thread
    streamlit_thread = Thread(target=run_streamlit_app)
    streamlit_thread.daemon = True  # Allow the thread to be terminated when main thread exits
    streamlit_thread.start()
    
    # Run the OAuth server in the main thread
    run_oauth_server()