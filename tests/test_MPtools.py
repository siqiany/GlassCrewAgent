import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

from src.GlassCrewAgent.tools.MPtools import (
    get_structure_info,
    get_band_gap_by_formula,
    get_band_gap_by_material_id,
    get_dielectric_by_material_id,
    get_volume_by_formula,
    get_density_by_formula,
    search_materials_containing_elements,
    calculate_density,
    calculate_symmetry
)


def test_mp_api_config():
    """Test if MP_KEY is configured in environment"""
    print("Testing Materials Project API configuration...")
    print("=" * 60)
    
    mp_key = os.environ.get("MP_KEY", "")
    if not mp_key or mp_key == "Your Materials Project Key":
        print("WARNING: MP_KEY not configured in .env file!")
        print("Please set your Materials Project API key to run full tests.")
        print("=" * 60)
        return False
    else:
        print(f"✓ MP_KEY found: {mp_key[:8]}... ({len(mp_key)} characters)")
        print("=" * 60)
        return True


def test_get_band_gap_by_formula():
    """Test getting band gap by chemical formula"""
    print("\n\nTesting get_band_gap_by_formula with SiO2...")
    print("=" * 60)
    
    try:
        result = get_band_gap_by_formula.func("SiO2")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Band gap by formula test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during band gap by formula test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_band_gap_by_material_id():
    """Test getting band gap by material ID"""
    print("\n\nTesting get_band_gap_by_material_id with mp-149 (SiO2)...")
    print("=" * 60)
    
    try:
        result = get_band_gap_by_material_id.func("mp-149")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Band gap by material ID test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during band gap by material ID test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_structure_info():
    """Test getting crystal structure information"""
    print("\n\nTesting get_structure_info with mp-149 (SiO2, quartz)...")
    print("=" * 60)
    
    try:
        result = get_structure_info.func("mp-149")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Structure info test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during structure info test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_calculate_density():
    """Test calculating density by material ID"""
    print("\n\nTesting calculate_density with mp-149 (SiO2)...")
    print("=" * 60)
    
    try:
        result = calculate_density.func("mp-149")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Calculate density test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during calculate density test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_calculate_symmetry():
    """Test calculating symmetry information"""
    print("\n\nTesting calculate_symmetry with mp-149 (SiO2)...")
    print("=" * 60)
    
    try:
        result = calculate_symmetry.func("mp-149")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Calculate symmetry test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during calculate symmetry test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_dielectric_by_material_id():
    """Test getting dielectric properties (important for optical glass)"""
    print("\n\nTesting get_dielectric_by_material_id with mp-149 (SiO2)...")
    print("=" * 60)
    
    try:
        result = get_dielectric_by_material_id.func("mp-149")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Dielectric properties test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during dielectric properties test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_volume_by_formula():
    """Test getting unit cell volume by formula"""
    print("\n\nTesting get_volume_by_formula with TiO2...")
    print("=" * 60)
    
    try:
        result = get_volume_by_formula.func("TiO2")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Volume by formula test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during volume by formula test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_density_by_formula():
    """Test getting density by formula"""
    print("\n\nTesting get_density_by_formula with TiO2...")
    print("=" * 60)
    
    try:
        result = get_density_by_formula.func("TiO2")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Density by formula test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during density by formula test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_search_materials_containing_elements():
    """Test searching materials containing specific elements"""
    print("\n\nTesting search_materials_containing_elements with Si, O...")
    print("=" * 60)
    
    try:
        result = search_materials_containing_elements.func(
            elements="Si,O",
            nelements=2,
            max_results=5
        )
        print(result)
        print("\n" + "=" * 60)
        print("✓ Element search test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Error during element search test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_invalid_material_id():
    """Test error handling with invalid material ID"""
    print("\n\nTesting error handling with invalid material ID...")
    print("=" * 60)
    
    try:
        result = get_structure_info.func("invalid-id")
        print(result)
        print("\n" + "=" * 60)
        print("✓ Invalid material ID error handling test completed!")
        return True
    except Exception as e:
        print(f"\n✗ Unexpected error during invalid ID test: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all MP tools tests"""
    print("Starting all Materials Project (MP) tools tests...")
    print(f"Python version: {sys.version}")
    print()
    
    # First check API configuration
    api_configured = test_mp_api_config()
    
    tests = [
        test_invalid_material_id,
        test_get_band_gap_by_formula,
        test_get_band_gap_by_material_id,
        test_get_structure_info,
        test_calculate_density,
        test_calculate_symmetry,
        test_get_dielectric_by_material_id,
        test_get_volume_by_formula,
        test_get_density_by_formula,
        test_search_materials_containing_elements
    ]
    
    # Only run full API tests if key is configured
    results = []
    
    # Always run invalid ID test (should work without API key)
    try:
        success = test_invalid_material_id()
        results.append(success)
    except Exception as e:
        print(f"Unexpected error in test_invalid_material_id: {e}")
        results.append(False)
    
    # Only run the rest if API is configured
    if api_configured:
        for test in tests[1:]:
            try:
                success = test()
                results.append(success)
            except Exception as e:
                print(f"Unexpected error in {test.__name__}: {e}")
                results.append(False)
    else:
        print("\n\nSkipping API-dependent tests because MP_KEY is not configured.")
        print("Please add your Materials Project API key to .env file to run full tests.")
    
    print("\n\n" + "=" * 60)
    print("Test Summary:")
    print(f"Total tests: {len(results)}")
    print(f"Passed: {sum(results)}/{len(results)}")
    print(f"Failed: {len(results) - sum(results)}/{len(results)}")
    
    if not api_configured:
        print("\nNote: API-dependent tests were skipped because MP_KEY is not configured.")
    print("=" * 60)
    
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)