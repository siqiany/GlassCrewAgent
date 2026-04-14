import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.GlassCrewAgent.tools.VAE_tools import generate_glass_composition


def test_vae_full_parameters():
    """Test VAE glass generation with all three optical parameters provided"""
    print("Testing VAE glass composition generation with all parameters...")
    print("=" * 60)

    try:
        # Test with typical optical glass parameters
        result = generate_glass_composition.func(
            refractive_index=1.52,
            abbe_number=50,
            mean_dispersion=0.010,
            num_samples=50,
            top_k=3
        )
        print(result)
        print("\n" + "=" * 60)
        print("Full parameters test completed successfully!")
        return True

    except Exception as e:
        print(f"\nError during full parameters test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vae_partial_parameters():
    """Test VAE glass generation with only refractive index provided"""
    print("\n\nTesting VAE glass generation with partial parameters (only refractive index)...")
    print("=" * 60)

    try:
        # Only provide refractive index, should use defaults for others
        result = generate_glass_composition.func(
            refractive_index=1.60,
            num_samples=30,
            top_k=2
        )
        print(result)
        print("\n" + "=" * 60)
        print("Partial parameters test completed successfully!")
        return True

    except Exception as e:
        print(f"\nError during partial parameters test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vae_out_of_range_warning():
    """Test VAE with parameter outside typical range to check warnings"""
    print("\n\nTesting VAE with out-of-range parameter (should show warning)...")
    print("=" * 60)

    try:
        # Refractive index outside typical range
        result = generate_glass_composition.func(
            refractive_index=1.90,  # This is above max typical 1.85
            abbe_number=30,
            num_samples=20,
            top_k=1
        )
        print(result)
        print("\n" + "=" * 60)
        print("Out-of-range warning test completed successfully!")
        return True

    except Exception as e:
        print(f"\nError during out-of-range warning test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vae_no_parameters_error():
    """Test error handling when no parameters are provided"""
    print("\n\nTesting VAE error handling with no parameters...")
    print("=" * 60)

    try:
        # No parameters provided should return error
        result = generate_glass_composition.func()
        print(result)
        print("\n" + "=" * 60)
        print("No parameters error handling test completed!")
        return True

    except Exception as e:
        print(f"\nError during no parameters test: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all VAE tool tests"""
    print("Starting all VAE glass generation tool tests...")
    print(f"PyTorch available: {__import__('torch').__version__ if 'torch' in sys.modules else 'Not loaded yet'}")
    print()

    tests = [
        test_vae_no_parameters_error,
        test_vae_full_parameters,
        test_vae_partial_parameters,
        test_vae_out_of_range_warning
    ]

    results = []
    for test in tests:
        try:
            success = test()
            results.append(success)
        except Exception as e:
            print(f"Unexpected error in {test.__name__}: {e}")
            results.append(False)

    print("\n\n" + "=" * 60)
    print("Test Summary:")
    print(f"Total tests: {len(results)}")
    print(f"Passed: {sum(results)}/{len(results)}")
    print(f"Failed: {len(results) - sum(results)}/{len(results)}")
    print("=" * 60)

    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)