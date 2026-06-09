#!/usr/bin/env bash
# Run the LuaTools Ultimate test suite (stdlib unittest, no dependencies).
# Usage: bash run_tests.sh
set -uo pipefail
cd "$(dirname "$0")"
echo "LuaTools Ultimate — test suite"
echo "=============================="
python3 -m unittest discover -s tests -p "test_*.py" -v
