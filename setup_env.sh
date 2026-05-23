#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

PROJECT_DIR="/Users/simonbs/code/jukebox5"
VENV_DIR="$PROJECT_DIR/.venv"
LIBUSB_PATH="/usr/local/lib/libusb-1.0.dylib"

echo "=== 1. Verifying Homebrew Libusb ==="
if [ ! -f "$LIBUSB_PATH" ]; then
    echo "Error: Homebrew libusb not found at $LIBUSB_PATH."
    echo "Please run: brew install libusb"
    exit 1
fi
echo "Found libusb at $LIBUSB_PATH"

echo "=== 2. Cleaning and Recreating Venv ==="
if [ -d "$VENV_DIR" ]; then
    echo "Removing existing .venv..."
    rm -rf "$VENV_DIR"
fi

echo "Creating new virtual environment..."
python3 -m venv "$VENV_DIR"

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "=== 3. Installing Dependencies without Cache ==="
pip install --upgrade pip
pip install --no-cache-dir pyftdi pyusb adafruit-blinka

# Get the exact python version directory name (e.g., python3.14)
PYTHON_VERSION=$(python3 -c "import sys; 
print(f'python{sys.version_info.major}.{sys.version_info.minor}')")
PATCH_TARGET="$VENV_DIR/lib/$PYTHON_VERSION/site-packages/usb/backend/libusb1.py"

echo "=== 4. Patching PyUSB Backend for Intel macOS ==="
if [ ! -f "$PATCH_TARGET" ]; then
    echo "Error: Target file for patch not found at $PATCH_TARGET"
    exit 1
fi

# Locate the exact line of 'def get_backend' and inject the find_library 
override on the next line
sed -i '' "/def get_backend(find_library=None):/a\\
    find_library = lambda x: \"$LIBUSB_PATH\"
" "$PATCH_TARGET"

echo "PyUSB backend patched successfully at: $PATCH_TARGET"

echo "=== 5. Setting up Environment Variables ==="
export BLINKA_FT232H=1

echo "=== 6. Validating Blinka Connection ==="
python3 -c 'import board; import digitalio; print("🎉 Success! Blinka 
successfully initialized!")'


