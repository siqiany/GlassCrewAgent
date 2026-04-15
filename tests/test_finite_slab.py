import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.GlassCrewAgent.tools.meep_tools import (
    create_simulation_cell,
    add_block_geometry,
    add_gaussian_pulse_source,
    initialize_simulation,
    add_flux_monitor,
    run_simulation_until_time,
    calculate_transmittance_reflectance,
    extract_electric_field_profile,
    clear_current_simulation,
    plot_transmittance_spectrum,
    plot_field_profile_1d,
)

clear_current_simulation.func()
print("1. Cleared simulation context")
print()

# Create cell: total 10 microns
result = create_simulation_cell.func(dimensions=1, size_x=10.0)
print(result)
print()

# Add finite slab: thickness 2 microns, centered at 0, epsilon=2.25 (n=1.5)
result = add_block_geometry.func(epsilon=2.25, center_x=0.0, size_x=2.0)
print(result)
print()

# Add source
result = add_gaussian_pulse_source.func(
    center_frequency=0.15,
    frequency_width=0.3,
    component="Ez",
    center_x=-3.5
)
print(result)
print()

# Initialize
result = initialize_simulation.func(resolution=20, default_material_epsilon=1.0)
print(result)
print()

# Add flux monitors: incident before slab, transmitted after slab
from src.GlassCrewAgent.tools.meep_tools import _sim_context
result_incident = add_flux_monitor.func(
    plane_center_x=-1.5,
    fcen=0.15,
    df=0.3,
    nfreq=100
)
print("Incident flux monitor:")
print(result_incident)
print()

result_transmitted = add_flux_monitor.func(
    plane_center_x=1.5,
    fcen=0.15,
    df=0.3,
    nfreq=100
)
print("Transmitted flux monitor:")
print(result_transmitted)
print()

# Run
result = run_simulation_until_time.func(run_until=200.0)
print(result)
print()

# Calculate
flux_monitors = _sim_context.get("flux_monitors", {})
if flux_monitors:
    flux_ids = list(flux_monitors.values())
    incident_id = flux_ids[0]
    transmitted_id = flux_ids[1]

    result = calculate_transmittance_reflectance.func(
        incident_flux_id=incident_id,
        transmitted_flux_id=transmitted_id,
        frequency_min=0.0,
        frequency_max=0.3,
        nfreq=100,
        output_filename="finite_slab_2um_transmittance.txt"
    )
    print(result)
    print()

    # Extract field
    result = extract_electric_field_profile.func(
        component="Ez",
        output_filename="finite_slab_2um_field.txt"
    )
    print(result)
