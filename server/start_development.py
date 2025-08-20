#!/usr/bin/env python3
"""
Development startup script for Baymax Assistant.

This script starts the servers in development mode with hot reload
and debug features enabled.
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path

# Set development environment
os.environ["DEBUG"] = "true"
os.environ["ENVIRONMENT"] = "development"

# Ensure we're in the correct directory
script_dir = Path(__file__).parent
os.chdir(script_dir)

def start_dev_server(module, port, name):
    """Start a server with development settings."""
    cmd = [
        sys.executable, "-m", "uvicorn",
        f"{module}:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--reload",
        "--reload-dir", "."
    ]
    
    print(f"Starting {name} on port {port} (with hot reload)...")
    return subprocess.Popen(cmd)

def main():
    """Main startup function."""
    print("🔧 Starting Baymax Assistant in Development Mode")
    print("=" * 50)
    
    # Check if .env file exists
    env_file = Path(".env")
    if not env_file.exists():
        print("⚠️  Warning: .env file not found!")
        print("   Please copy .env.production to .env and configure your API keys.")
        return 1
    
    processes = []
    
    try:
        # Start TTS server
        tts_process = start_dev_server("tts_server", 5050, "TTS Server")
        processes.append(tts_process)
        time.sleep(2)  # Give TTS server time to start
        
        # Start main API server
        api_process = start_dev_server("app", 8000, "Main API Server")
        processes.append(api_process)
        
        print("\n✅ All servers started successfully!")
        print("📡 Main API: http://localhost:8000")
        print("🔊 TTS API: http://localhost:5050")
        print("🔄 Hot reload enabled - files will auto-restart on changes")
        print("\nPress Ctrl+C to stop all servers...")
        
        # Wait for processes
        while True:
            time.sleep(1)
            # Check if any process died
            for i, process in enumerate(processes):
                if process.poll() is not None:
                    print(f"❌ Process {i} died with code {process.returncode}")
                    return 1
                    
    except KeyboardInterrupt:
        print("\n🛑 Shutting down servers...")
        
    finally:
        # Cleanup processes
        for process in processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        
        print("✅ All servers stopped.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())