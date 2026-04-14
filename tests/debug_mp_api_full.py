#!/usr/bin/env python
"""Full debugging with complete patching"""

# Apply all patches before any imports
# 1. BaseSettings
import pydantic
from pydantic_settings import BaseSettings
if not hasattr(pydantic, 'BaseSettings'):
    setattr(pydantic, 'BaseSettings', BaseSettings)

# 2. Missing schema functions
import pydantic.schema
if not hasattr(pydantic.schema, 'get_flat_models_from_model'):
    def get_flat_models_from_model(model):
        return [model]
    pydantic.schema.get_flat_models_from_model = get_flat_models_from_model

    def get_model_name_map(models):
        return {model: model.__name__ for model in models}
    pydantic.schema.get_model_name_map = get_model_name_map

# 3. Patch FieldInfo to add type_ property to ALL instances
from pydantic.fields import FieldInfo

# Add property getter that dynamically gets it from annotation
if not hasattr(FieldInfo, 'type_'):
    @property
    def type_(self):
        return self.annotation
    setattr(FieldInfo, 'type_', type_)

print("✓ All pydantic compatibility patches applied")

# Now import
import os
from dotenv import load_dotenv
load_dotenv()

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