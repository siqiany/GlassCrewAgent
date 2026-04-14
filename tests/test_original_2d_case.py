import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.GlassCrewAgent.tools.meep_tools import (
    create_simulation_cell,
    add_block_geometry,
    add_gaussian_pulse_source,
    initialize_simulation,
    add_flux_monitor,
    clear_current_simulation
)


def test_original_2d_case():
    """Test the original problematic case from the user's error - 2.0 x 2.0 um with PML 0.5 um"""
    print("Testing original problematic 2D case: 2.0 μm × 2.0 μm cell, PML 0.5 μm, 1 μm glass slab")
    print("=" * 60)

    try:
        # Clear any existing simulation
        print("\n1. Clearing simulation context...")
        result = clear_current_simulation.func()
        print(result)

        # Create 2D simulation cell - original problematic case
        print("\n2. Creating 2D simulation cell (2.0 μm × 2.0 μm, PML 0.5 μm)...")
        result = create_simulation_cell.func(
            dimensions=2,
            size_x=2.0,
            size_y=2.0,
            pml_thickness=0.5,
            pml_layers="all"
        )
        print(result)

        # Add the glass slab - 1.0 μm thick centered at (0,0)
        print("\n3. Adding glass slab (nd=2.50)...")
        # epsilon = n^2 = 2.5^2 = 6.25
        result = add_block_geometry.func(
            epsilon=6.25,
            center_x=0.0,
            center_y=0.0,
            size_x=1.0,
            size_y=float('inf')
        )
        print(result)

        # Add Gaussian pulse source centered at 589nm (1/0.589 ≈ 1.7)
        print("\n4. Adding Gaussian pulse source (589nm = 1.7 μm^-1)...")
        # wavelength 589nm = 0.589 μm, frequency = 1/0.589 ≈ 1.7
        # width 1.0 to cover 0.7 - 2.7 (≈ 400-1400 nm)
        result = add_gaussian_pulse_source.func(
            center_frequency=1.7,
            frequency_width=1.0,
            component="Ez",
            center_x=-0.5,
            center_y=0.0
        )
        print(result)

        # Initialize simulation with 20 pixels/μm
        print("\n5. Initializing simulation...")
        result = initialize_simulation.func(
            resolution=20,
            default_material_epsilon=1.0
        )
        print(result)

        # Add flux monitors
        print("\n6. Adding flux monitors (incident and transmitted)...")
        # Incident before slab
        result_incident = add_flux_monitor.func(
            plane_center_x=-0.6,
            plane_center_y=0.0,
            plane_size_y=2.0,
            direction="x",
            fcen=1.7,
            df=1.0,
            nfreq=50
        )
        print("Incident monitor:")
        print(result_incident)

        # Transmitted after slab
        result_transmitted = add_flux_monitor.func(
            plane_center_x=0.6,
            plane_center_y=0.0,
            plane_size_y=2.0,
            direction="x",
            fcen=1.7,
            df=1.0,
            nfreq=50
        )
        print("\nTransmitted monitor:")
        print(result_transmitted)

        print("\n" + "=" * 60)
        print("✓ All steps completed successfully without errors!")
        print("The original error 'invalid boundary absorbers' has been fixed.")

    except ImportError as e:
        print("\nError: Could not import meep.")
        print("Make sure pymeep is installed in your conda environment:")
        print("    conda install -c conda-forge pymeep")
        print(f"Detailed error: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Error during simulation: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = test_original_2d_case()
    sys.exit(0 if success else 1)