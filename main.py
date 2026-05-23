"""
CLI entry point — runs the Flask web dashboard.
Open http://localhost:5000 in your browser after starting.
"""
from app import app
import os

if __name__ == "__main__":
    os.makedirs("jobs", exist_ok=True)
    print("\n🚀 GitHub Repo Analyzer is running!")
    print("   Open http://localhost:5000 in your browser\n")
    app.run(debug=False, port=5000, threaded=True)
