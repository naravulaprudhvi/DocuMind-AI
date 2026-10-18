"""
Production WSGI entry point for DocuMind AI.
Runs using Waitress on Windows / Linux for high-concurrency production serving.

Usage:
    python wsgi.py
"""
import os
import sys

# Ensure application directory takes top priority in module resolution
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")

    try:
        from waitress import serve
        print(f"Starting DocuMind AI Production Server on http://{host}:{port} with Waitress...")
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        print(f"Waitress not installed. Falling back to development server on http://{host}:{port}...")
        app.run(host=host, port=port, debug=False)
