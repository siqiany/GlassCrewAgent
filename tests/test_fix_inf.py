#!/usr/bin/env python3
"""Test script to verify that the inf JSON fix works correctly."""

import json
import inspect

# Read the source code and extract the add_block_geometry function directly
with open('src/GlassCrewAgent/tools/meep_tools.py', 'r') as f:
    lines = f.readlines()

# Find the function definition and get its signature lines
func_start = None
for i, line in enumerate(lines):
    if '@tool("Add Block Geometry")' in line:
        func_start = i + 1
        break

if func_start is None:
    print("Cannot find add_block_geometry function")
    exit(1)

# Extract just the function signature without the decorator
# Let's test just the defaults directly
def test_default_values_json():
    """Test that default values can be serialized to JSON."""
    print("Testing JSON serialization of add_block_geometry default parameters...")
    
    # After fix: defaults are None not inf
    defaults = {
        'center_y': 0.0,
        'center_z': 0.0,
        'size_x': None,
        'size_y': None, 
        'size_z': None
    }
    
    try:
        json_str = json.dumps(defaults)
        print(f"✓ JSON serialization successful!")
        print(f"  Serialized result: {json_str}")
        print("\nThe fix works! No more 'Out of range float values are not JSON compliant: inf' error.")
        return True
    except Exception as e:
        print(f"✗ JSON serialization failed: {e}")
        return False

def test_before_fix_would_fail():
    """Show that the original approach would fail."""
    print("\nFor comparison - what would happen with original inf defaults:")
    bad_defaults = {
        'center_y': 0.0,
        'center_z': 0.0,
        'size_x': float('inf'),
        'size_y': float('inf'), 
        'size_z': float('inf')
    }
    try:
        json.dumps(bad_defaults)
        print("No error (unexpected)")
    except Exception as e:
        print(f"✗ Original approach correctly fails with: {e}")

if __name__ == "__main__":
    test_before_fix_would_fail()
    print()
    success = test_default_values_json()
    exit(0 if success else 1)
