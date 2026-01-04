#!/bin/bash

# Setup script to install git hooks

echo "🔧 Setting up git hooks..."

# Configure git to use .githooks directory
git config core.hooksPath .githooks

# Make hooks executable
chmod +x .githooks/*

echo "✅ Git hooks configured!"
echo ""
echo "The following hooks are now active:"
echo "  - post-merge: Automatically runs migrations after git pull"
