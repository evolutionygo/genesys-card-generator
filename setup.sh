#!/bin/bash

# Setup script for Yu-Gi-Oh! Card Downloader
# This script sets up the Python environment

echo "🚀 Setting up Yu-Gi-Oh! Card Downloader..."

# Check if Python 3 is available
if command -v python3 &> /dev/null; then
    echo "✅ Python 3 found"
    
    # Create Python virtual environment
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
    
    # Activate and install dependencies
    echo "📥 Installing Python dependencies..."
    source venv/bin/activate
    pip install -r requirements.txt
    
    echo "✅ Python environment ready"
else
    echo "❌ Python 3 not found. Please install Python 3.6+ to use the script."
    exit 1
fi

echo ""
echo "🎉 Setup completed!"
echo ""
echo "🚀 Quick Start:"
echo "  source venv/bin/activate && python3 card_downloader.py"
echo ""
echo "📝 The script will download images as {card_code}.jpg (e.g., 21044178.jpg)"
echo "⚡ Fast downloads - no API calls needed!"
echo ""
echo "For help:"
echo "  python3 card_downloader.py --help"