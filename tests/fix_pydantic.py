#!/usr/bin/env python
# Fix pydantic compatibility issue before importing mp-api

# Use a try-except block to handle the pydantic import migration
try:
    from pydantic import BaseSettings
except ImportError:
    from pydantic_settings import BaseSettings
    import pydantic
    # Add BaseSettings to pydantic module for backward compatibility
    pydantic.BaseSettings = BaseSettings

print("✓ Pydantic compatibility fix applied")

# Now we can import mp-api
import os
from dotenv import load_dotenv
load_dotenv()

from mp_api.client import MPRester
print("✓ Successfully imported MPRester")

api_key = os.environ.get('MP_KEY', '')
print(f"API Key length: {len(api_key)}")

mpr = MPRester(api_key)
print("✓ Successfully created MPRester instance")

# Test a simple query
result = mpr.get_structure_by_material_id("mp-149")
print(f"✓ Successfully got structure for mp-149: volume={result.volume:.4f}, density={result.density:.4f}")