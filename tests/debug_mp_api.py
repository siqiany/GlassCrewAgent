#!/usr/bin/env python
"""Debug script to fix pydantic compatibility issues for mp-api"""

# Fix multiple pydantic v1 -> v2 compatibility issues before importing mp-api
import sys
import pydantic
from pydantic_settings import BaseSettings

# Add BaseSettings to pydantic module
pydantic.BaseSettings = BaseSettings

# Add get_flat_models_from_model and other schema utilities
try:
    from pydantic.schema import get_flat_models_from_model
except ImportError:
    # pydantic v2 doesn't have this anymore, but we need to provide it
    # This is a simplified mock for compatibility
    def get_flat_models_from_model(model):
        return [model]

    import pydantic.schema
    pydantic.schema.get_flat_models_from_model = get_flat_models_from_model

    # Also add other missing functions that mp-api might expect
    def get_model_name_map(models):
        return {model: model.__name__ for model in models}

    pydantic.schema.get_model_name_map = get_model_name_map

    def get_encoding_def(model):
        return {}

    pydantic.schema.get_encoding_def = get_encoding_def

print("✓ Pydantic compatibility fixes applied")

# Now continue with imports
import os
from dotenv import load_dotenv
load_dotenv()

try:
    from mp_api.client import MPRester
    print("✓ Successfully imported MPRester")

    api_key = os.environ.get('MP_KEY', '')
    print(f"API Key length: {len(api_key)}")

    if api_key:
        mpr = MPRester(api_key)
        print("✓ Successfully created MPRester instance")

        # Test a simple query
        result = mpr.get_structure_by_material_id("mp-149")
        print(f"✓ Successfully got structure for mp-149: volume={result.volume:.4f}, density={result.density:.4f}")
    else:
        print("⚠ No API key found, skipping actual API query")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()