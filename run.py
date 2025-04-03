"""
Streamlit-only runner for Embroidery Quoting Tool

This script runs the Streamlit application on port 5000.
OAuth callbacks are handled directly by Streamlit via callback.py.
"""

import os
import sys
import logging
import subprocess
import time
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('embroidery_runner')

def run_streamlit_app():
    """Run the Streamlit application on port 5000"""
    logger.info("Starting Embroidery Quoting Tool...")
    
    # First, ensure the database has the required QuickBooks settings table
    import database
    database.create_quickbooks_table_if_missing()
    logger.info("QuickBooks settings table verified")
    
    # Start the Streamlit application
    logger.info("Starting Streamlit application on port 5000...")
    cmd = ["streamlit", "run", "app.py", "--server.port", "5000", "--server.address", "0.0.0.0"]
    
    # Run Streamlit with output streaming to console
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1  # Line buffered
    )
    
    # Monitor and stream the output
    while True:
        try:
            # Read output from the process
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                logger.error("Streamlit process terminated unexpectedly with code {}".format(process.returncode))
                break
            if output:
                # Print the output
                sys.stdout.write(f"[Streamlit] {output}")
                sys.stdout.flush()
        except KeyboardInterrupt:
            # Handle keyboard interrupt (Ctrl+C)
            logger.info("Keyboard interrupt received, terminating Streamlit...")
            process.terminate()
            break
        except Exception as e:
            # Handle other exceptions
            logger.error(f"Error monitoring Streamlit output: {str(e)}")
            logger.error(traceback.format_exc())
            break
    
    # Wait for process to terminate
    try:
        process.wait()
    except:
        pass
    
    logger.info("Streamlit application has terminated.")

if __name__ == "__main__":
    try:
        run_streamlit_app()
    except Exception as e:
        logger.error(f"Unhandled exception in main: {str(e)}")
        logger.error(traceback.format_exc())