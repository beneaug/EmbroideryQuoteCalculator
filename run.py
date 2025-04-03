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
        universal_newlines=True,
        bufsize=1  # Line buffered
    )
    
    # Stream the output to the console
    def stream_output():
        if not process or not process.stdout:
            logger.error("Streamlit process or stdout is None, cannot stream output")
            return
            
        while True:
            try:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    sys.stdout.write(f"[Streamlit] {line}")
                    sys.stdout.flush()
            except Exception as e:
                logger.error(f"Error reading Streamlit output: {str(e)}")
                break
    
    # Create a thread to handle the output streaming
    import threading
    output_thread = threading.Thread(target=stream_output)
    output_thread.daemon = True
    output_thread.start()
    
    # Return the process object so it can be monitored
    return process

def run_oauth_server():
    """Run the Flask OAuth server on port 8000"""
    logger.info("Starting OAuth callback server...")
    
    try:
        # Import the Flask app from oauth_server
        from oauth_server import app
        
        # First, ensure the database has the required QuickBooks settings table
        import database
        database.create_quickbooks_table_if_missing()
        logger.info("QuickBooks settings table verified")
        
        # Run the Flask app without the built-in reloader (since we're managing it)
        logger.info("Starting OAuth server on port 8000")
        app.run(host='0.0.0.0', port=8000, use_reloader=False, debug=False)
    except Exception as e:
        logger.error(f"Error starting OAuth server: {str(e)}", exc_info=True)
        # Sleep briefly to prevent immediate restart if there's a critical error
        import time
        time.sleep(2)
        raise

if __name__ == "__main__":
    logger.info("Starting Embroidery Quoting Tool...")
    
    # Create and start the Streamlit thread
    streamlit_thread = Thread(target=run_streamlit_app)
    streamlit_thread.daemon = True  # Allow the thread to be terminated when main thread exits
    streamlit_thread.start()
    
    # Run the OAuth server in the main thread
    run_oauth_server()