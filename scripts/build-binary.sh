#!/bin/bash

set -e

VERSION="1.4.1"

echo "=== Codex Session Patcher Build ==="
echo "Version: $VERSION"

echo "Cleaning previous build artifacts..."
rm -rf build/ dist/ *.egg-info

echo "Installing build dependency..."
pip install pyinstaller

echo "Building CLI executable..."
pyinstaller codex-patcher.spec --clean -y

echo "Building Web Launcher executable..."
pyinstaller codex-web-launcher.spec --clean -y

if [ -d "dist/codex-patcher" ]; then
  echo "CLI build output:"
  ls -la dist/codex-patcher/
fi

if [ -d "dist/codex-patcher-launcher" ]; then
  echo "Web Launcher build output:"
  ls -la dist/codex-patcher-launcher/
fi

echo "=== Build complete ==="
