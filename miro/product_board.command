#!/bin/bash
cd "$(dirname "$0")"
echo "Enter product page URL:"
read -r URL
python3 product_board.py "$URL"
echo
read -r -p "Finished. Press Enter to close." _
