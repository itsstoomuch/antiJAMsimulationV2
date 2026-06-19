"""
run_viz.py — NAVGUARD visualization launcher.

Usage:
    python run_viz.py

Starts the Flask backend on port 5000.
Open frontend/index.html in your browser to use the visualizer.
"""

import os
import sys

# Ensure backend directory is on the path
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, BACKEND_DIR)

from app import app

if __name__ == "__main__":
    print("=" * 50)
    print("  NAVGUARD — GPS Anti-Jam Visualization Server")
    print("=" * 50)
    print("Backend running at http://localhost:5001")
    print("Open frontend/index.html in your browser")
    print("Press Ctrl+C to stop")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5001, debug=False)
