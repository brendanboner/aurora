#!/bin/bash
set -e

echo "=============================================="
echo "Aurora Curator Service - Starting"
echo "=============================================="
echo ""

# Wait for digester to complete processing
echo "Step 1: Waiting for digester to complete..."
python wait_for_digester.py

# Check exit code from wait script
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to wait for digester completion"
    exit 1
fi

echo ""
echo "Step 2: Running curator to organize topic hierarchy..."
echo ""

# Run the main curator service
python main.py

# Check exit code
if [ $? -eq 0 ]; then
    echo ""
    echo "=============================================="
    echo "✓ Curator service completed successfully"
    echo "=============================================="
    exit 0
else
    echo ""
    echo "=============================================="
    echo "✗ Curator service failed"
    echo "=============================================="
    exit 1
fi
