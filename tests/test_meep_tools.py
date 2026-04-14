import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.GlassCrewAgent.tools.meep_tools import (
    create_simulation_cell,
    add_block_geometry,
    set_dispersive_material_from_n,
    add_gaussian_pulse_source,
    initialize_simulation,
    add_flux_monitor,
    run_simulation_until_time,
    calculate_transmittance_reflectance,
    extract_electric_field_profile,
    clear_current_simulation,
    get_simulation_output_directory
)


def test_meep_simulation_1d():
    """Test a simple 1D simulation: normal incidence on a dielectric slab"""
    print("Starting Meep 1D simulation test...")
    print("=" * 60)

    try:
        # Clear any existing simulation
        print("\n1. Clearing simulation context...")
        result = clear_current_simulation.func()
        print(result)

        # Create 1D simulation cell
        print("\n2. Creating 1D simulation cell...")
        # Total length 10 microns, PML thickness 1 micron on all sides
        result = create_simulation_cell.func(
            dimensions=1,
            size_x=10.0
        )
        print(result)

        # Add a dielectric block in the center
        print("\n3. Adding dielectric block (n = 1.5, glass)...")
        # Block from -1 to 1 micron centered at x=0, epsilon = n^2 = 2.25
        result = add_block_geometry.func(
            epsilon=2.25,
            center_x=0.0
        )
        print(result)

        # Add Gaussian pulse source
        print("\n4. Adding Gaussian pulse source...")
        # Center frequency 0.15 (wavelength ~6.67 microns), width 0.1
        # Source is at x = -3.5 microns, Ez component
        result = add_gaussian_pulse_source.func(
            center_frequency=0.15,
            frequency_width=0.1,
            component="Ez",
            center_x=-3.5
        )
        print(result)

        # Initialize simulation
        print("\n5. Initializing simulation...")
        # Resolution 20 pixels/micron, default material air (epsilon=1)
        result = initialize_simulation.func(
            resolution=20,
            default_material_epsilon=1.0
        )
        print(result)

        # Add flux monitors
        print("\n6. Adding flux monitors...")
        # Incident flux before the slab
        # For the frequency range 0.05-0.25 we set fcen=0.15, df=0.2, nfreq=50
        result_incident = add_flux_monitor.func(
            plane_center_x=-2.0,
            fcen=0.15,
            df=0.2,
            nfreq=50
        )
        print("Incident flux monitor:")
        print(result_incident)

        # Transmitted flux after the slab
        result_transmitted = add_flux_monitor.func(
            plane_center_x=2.0,
            fcen=0.15,
            df=0.2,
            nfreq=50
        )
        print("\nTransmitted flux monitor:")
        print(result_transmitted)

        # Run simulation
        print("\n7. Running simulation until time 100...")
        result = run_simulation_until_time.func(
            run_until=100.0
        )
        print(result)

        # Calculate transmittance
        print("\n8. Calculating transmittance spectrum...")
        # The result already gives us the flux object which is what we need directly
        def extract_flux_id(result_str):
            # In the current implementation, flux_id is already the DftFlux object
            # We need to extract it from the string - actually it's already returned, so hack:
            # The result is from add_flux_monitor which returns the text, and we need the actual object
            # So let's get it from the simulation context
            # Looking at meep_tools.py, it stores the flux_id in _sim_context
            from src.GlassCrewAgent.tools.meep_tools import _sim_context
            # Get the last one added
            flux_monitors = _sim_context.get("flux_monitors", {})
            if flux_monitors:
                # Just return the last value which is the flux object
                return list(flux_monitors.values())[-1]
            return None

        incident_id = extract_flux_id(result_incident)
        transmitted_id = extract_flux_id(result_transmitted)

        result = calculate_transmittance_reflectance.func(
            incident_flux_id=incident_id,
            transmitted_flux_id=transmitted_id,
            frequency_min=0.05,
            frequency_max=0.25,
            nfreq=50,
            output_filename="1d_slab_transmittance.txt"
        )
        print(result)

        # Extract electric field profile
        print("\n9. Extracting electric field profile...")
        result = extract_electric_field_profile.func(
            component="Ez",
            output_filename="1d_slab_field.txt"
        )
        print(result)

        # Get output directory
        print("\n10. Getting output directory...")
        result = get_simulation_output_directory.func()
        print(result)

        print("\n" + "=" * 60)
        print("Simulation completed successfully! Check output directory for results.")

    except ImportError as e:
        print("\nError: Could not import meep.")
        print("Make sure pymeep is installed in your conda environment:")
        print("    conda install -c conda-forge pymeep")
        print(f"Detailed error: {e}")
        return False
    except Exception as e:
        print(f"\nError during simulation: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = test_meep_simulation_1d()
    sys.exit(0 if success else 1)