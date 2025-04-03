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
import threading
from threading import Thread
import traceback

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
    output_thread = threading.Thread(target=stream_output)
    output_thread.daemon = True
    output_thread.start()
    
    # Return the process object so it can be monitored
    return process

def run_oauth_server():
    """Run the Flask OAuth server on port 5000 path /oauth/*"""
    logger.info("Starting OAuth callback server...")
    
    try:
        # First, ensure the database has the required QuickBooks settings table
        import database
        database.create_quickbooks_table_if_missing()
        logger.info("QuickBooks settings table verified")
        
        # Import the Flask app from oauth_server
        from oauth_server import app
        
        # Run the Flask app using Werkzeug server directly to avoid threading issues
        from werkzeug.serving import make_server
        
        # Create a proper HTTP server with Werkzeug
        http_server = make_server('0.0.0.0', 8000, app, threaded=True)
        logger.info("OAuth server created and ready to run on port 8000")
        
        # Start the server in a separate thread
        server_thread = threading.Thread(target=http_server.serve_forever)
        server_thread.daemon = True
        
        # Start the server thread
        server_thread.start()
        logger.info("OAuth server thread started successfully")
        
        # Return the thread for monitoring
        return server_thread
        
    except Exception as e:
        logger.error(f"Error starting OAuth server: {str(e)}")
        logger.error(traceback.format_exc())
        # Sleep briefly to prevent immediate restart if there's a critical error
        time.sleep(2)
        return None

# Monitor threads and restart if needed
def monitor_services(streamlit_process, oauth_thread):
    logger.info("Starting service monitoring...")
    
    try:
        while True:
            # Check Streamlit process
            if streamlit_process.poll() is not None:
                logger.error("Streamlit process died, restarting...")
                streamlit_process = run_streamlit_app()
            
            # Check OAuth thread (harder to detect if it's actually working)
            if oauth_thread and not oauth_thread.is_alive():
                logger.error("OAuth server thread died, restarting...")
                oauth_thread = run_oauth_server()
                
            # Sleep before checking again
            time.sleep(10)
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
        if streamlit_process:
            streamlit_process.terminate()
    except Exception as e:
        logger.error(f"Error in monitor loop: {str(e)}")
        logger.error(traceback.format_exc())
        
if __name__ == "__main__":
    logger.info("Starting Embroidery Quoting Tool...")
    
    # Start the Streamlit application
    streamlit_process = run_streamlit_app()
    
    # Start the OAuth server in a dedicated thread
    oauth_thread = run_oauth_server()
    
    # Monitor and restart services if needed
    monitor_thread = Thread(target=monitor_services, args=(streamlit_process, oauth_thread))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        if streamlit_process:
            streamlit_process.terminate()
    except Exception as e:
        logger.error(f"Error in main thread: {str(e)}")
        logger.error(traceback.format_exc())