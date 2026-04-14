"""
Meep (FDTD Electromagnetic Simulation) Tools for CrewAI

This module provides tools for running finite-difference time-domain (FDTD)
electromagnetic simulations using pymeep, particularly for optical glass
structures and devices.

Requirements:
- Install pymeep: conda install -c conda-forge pymeep
- Meep official documentation: https://meep.readthedocs.io/

Main functionality:
- Simulation cell creation and geometry setup
- Continuous wave and Gaussian pulse sources
- Transmittance/reflectance calculation
- Field profile extraction
- Resonant frequency analysis
- Dispersive materials for optical glass
"""

import os
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from crewai.tools import tool

# Global simulation context to maintain state across tool calls
_sim_context: Dict[str, Any] = {
    "sim": None,
    "geometry": [],
    "sources": [],
    "pml_layers": [],
    "dimensions": None,
    "cell_size": None,
    "current_filename": None,
    "output_dir": "output/meep_simulations"
}


def _reset_sim_context() -> None:
    """Reset the simulation context for a new simulation."""
    global _sim_context
    _sim_context = {
        "sim": None,
        "geometry": [],
        "sources": [],
        "pml_layers": [],
        "dimensions": None,
        "cell_size": None,
        "current_filename": None,
        "output_dir": "output/meep_simulations"
    }
    # Create output directory if it doesn't exist
    os.makedirs(_sim_context["output_dir"], exist_ok=True)


def _get_meep():
    """Import meep lazily to avoid issues when it's not installed."""
    try:
        import meep as mp
        return mp
    except ImportError:
        raise ImportError(
            "pymeep is not installed. Please install it using:\n"
            "conda install -c conda-forge pymeep\n"
            "For more details, see https://meep.readthedocs.io/en/latest/Installation/"
        )


# =============================================================================
# Simulation Setup Tools
# =============================================================================

@tool("Create Simulation Cell")
def create_simulation_cell(
    dimensions: int,
    size_x: float,
    size_y: float = 0.0,
    size_z: float = 0.0,
    pml_thickness: float = 1.0,
    pml_layers: Optional[str] = "all"
) -> str:
    """
    Create a new simulation computational cell for FDTD simulation.
    Must be called first before any other simulation commands.
    
    Args:
        dimensions: Number of dimensions (1, 2, or 3)
        size_x: Cell size in x direction (microns)
        size_y: Cell size in y direction (microns), required for 2d/3d
        size_z: Cell size in z direction (microns), required for 3d
        pml_thickness: Thickness of perfectly matched layer (PML) absorbing boundary (microns)
        pml_layers: Which sides to add PML - "all", "x", "y", or "z"
    
    Returns:
        Summary of the created simulation cell
    """
    # Convert string inputs to float/int if needed (handles LLM outputting strings)
    def to_float(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    def to_int(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 1
        return int(val)
    
    dimensions = to_int(dimensions)
    size_x = to_float(size_x)
    size_y = to_float(size_y)
    size_z = to_float(size_z)
    pml_thickness = to_float(pml_thickness)
    
    mp = _get_meep()
    _reset_sim_context()
    
    # Validate dimensions
    if dimensions not in [1, 2, 3]:
        return "Error: dimensions must be 1, 2, or 3"
    
    if dimensions >= 2 and size_y == 0:
        return "Error: size_y must be specified for 2D or 3D simulation"
    if dimensions == 3 and size_z == 0:
        return "Error: size_z must be specified for 3D simulation"
    
    # Check that PML thickness doesn't exceed available space
    # PML is on both sides, so total PML is 2*pml_thickness
    pml_warning = ""
    min_cell_size = 2 * pml_thickness + 0.1
    if dimensions == 1:
        if size_x < min_cell_size:
            max_pml = size_x / 2 - 0.05
            pml_thickness = max_pml
            pml_warning = f"\n- WARNING: PML thickness adjusted to {pml_thickness} μm (original value would exceed cell size)"
    elif dimensions == 2:
        if size_x < min_cell_size or size_y < min_cell_size:
            max_pml_x = size_x / 2 - 0.05
            max_pml_y = size_y / 2 - 0.05
            new_pml = min(max_pml_x, max_pml_y)
            if new_pml < pml_thickness:
                pml_thickness = new_pml
                pml_warning = f"\n- WARNING: PML thickness adjusted to {pml_thickness} μm (original value would exceed cell size)"
    else:  # 3D
        if size_x < min_cell_size or size_y < min_cell_size or size_z < min_cell_size:
            max_pml_x = size_x / 2 - 0.05
            max_pml_y = size_y / 2 - 0.05
            max_pml_z = size_z / 2 - 0.05
            new_pml = min(max_pml_x, max_pml_y, max_pml_z)
            if new_pml < pml_thickness:
                pml_thickness = new_pml
                pml_warning = f"\n- WARNING: PML thickness adjusted to {pml_thickness} μm (original value would exceed cell size)"
    
    # Create cell size vector
    if dimensions == 1:
        cell = mp.Vector3(size_x)
        _sim_context["cell_size"] = (size_x,)
    elif dimensions == 2:
        cell = mp.Vector3(size_x, size_y)
        _sim_context["cell_size"] = (size_x, size_y)
    else:  # 3D
        cell = mp.Vector3(size_x, size_y, size_z)
        _sim_context["cell_size"] = (size_x, size_y, size_z)
    
    _sim_context["dimensions"] = dimensions
    
    # Add PML layers
    # In Meep, we must explicitly specify direction for each dimension
    # One PML per direction covers both boundaries
    if pml_thickness > 0:
        pml = []
        if pml_layers == "all":
            # Add PML to all dimensions that exist in this simulation
            if dimensions >= 1:
                pml.append(mp.PML(pml_thickness, direction=mp.X))
            if dimensions >= 2:
                pml.append(mp.PML(pml_thickness, direction=mp.Y))
            if dimensions >= 3:
                pml.append(mp.PML(pml_thickness, direction=mp.Z))
        else:
            # Add PML only to specified directions
            if "x" in pml_layers:
                pml.append(mp.PML(pml_thickness, direction=mp.X))
            if "y" in pml_layers:
                pml.append(mp.PML(pml_thickness, direction=mp.Y))
            if "z" in pml_layers:
                pml.append(mp.PML(pml_thickness, direction=mp.Z))
        _sim_context["pml_layers"] = pml
    else:
        _sim_context["pml_layers"] = []
    
    response = f"""Created {dimensions}D simulation cell:
- Cell size: {size_x} μm × {size_y if dimensions >=2 else 'N/A'} μm × {size_z if dimensions ==3 else 'N/A'} μm
- PML thickness: {pml_thickness} μm on {pml_layers} sides
- PML layers added: {len(_sim_context["pml_layers"])}{pml_warning}
"""
    return response


@tool("Add Block Geometry")
def add_block_geometry(
    epsilon: float,
    center_x: float,
    center_y: float = 0.0,
    center_z: float = 0.0,
    size_x: Optional[float] = None,
    size_y: Optional[float] = None,
    size_z: Optional[float] = None
) -> str:
    """
    Add a block (rectangular parallelepiped) geometric object with specified dielectric constant.
    Common use case: waveguides, rectangular glass structures.
    
    Args:
        epsilon: Electric permittivity (ε = n² where n is refractive index)
        center_x: Center x coordinate (microns)
        center_y: Center y coordinate (microns), required for 2d/3d
        center_z: Center z coordinate (microns), required for 3d
        size_x: Block size in x direction (microns), default: infinite
        size_y: Block size in y direction (microns), default: infinite
        size_z: Block size in z direction (microns), default: infinite
    
    Returns:
        Confirmation of added block
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return None
        return float(val)
    
    epsilon = to_float(epsilon)
    center_x = to_float(center_x)
    center_y = to_float(center_y)
    center_z = to_float(center_z)
    size_x = to_float(size_x)
    size_y = to_float(size_y)
    size_z = to_float(size_z)
    
    mp = _get_meep()
    
    if _sim_context["dimensions"] is None:
        return "Error: Call create_simulation_cell first"
    
    # Convert None to inf for JSON compatibility
    size_x = size_x if size_x is not None else float('inf')
    size_y = size_y if size_y is not None else float('inf')
    size_z = size_z if size_z is not None else float('inf')
    
    # Create center vector
    center = mp.Vector3(center_x, center_y, center_z)
    size = mp.Vector3(size_x, size_y, size_z)
    
    material = mp.Medium(epsilon=epsilon)
    block = mp.Block(size, center=center, material=material)
    _sim_context["geometry"].append(block)
    
    dimensions = _sim_context["dimensions"]
    response = f"""Added block geometry:
- Position: center = ({center_x}, {center_y}, {center_z}) μm
- Size: ({size_x}, {size_y}, {size_z}) μm
- Permittivity (ε): {epsilon} (refractive index n ≈ {np.sqrt(epsilon):.3f})
- Total geometry objects: {len(_sim_context["geometry"])}
"""
    return response


@tool("Add Cylinder Geometry")
def add_cylinder_geometry(
    radius: float,
    height: float,
    epsilon: float,
    center_x: float,
    center_y: float,
    center_z: float = 0.0,
    axis: str = "z"
) -> str:
    """
    Add a cylinder geometric object with specified dielectric constant.
    Common use case: cylindrical fibers, waveguides, rod-shaped inclusions.
    
    Args:
        radius: Radius of the cylinder (microns)
        height: Height of the cylinder (microns), use mp.inf for infinite
        epsilon: Electric permittivity (ε = n² where n is refractive index)
        center_x: Center x coordinate (microns)
        center_y: Center y coordinate (microns)
        center_z: Center z coordinate (microns), required for 3d
        axis: Axis along which cylinder extends ("x", "y", or "z")
    
    Returns:
        Confirmation of added cylinder
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    radius = to_float(radius)
    height = to_float(height)
    epsilon = to_float(epsilon)
    center_x = to_float(center_x)
    center_y = to_float(center_y)
    center_z = to_float(center_z)
    
    mp = _get_meep()
    
    if _sim_context["dimensions"] is None:
        return "Error: Call create_simulation_cell first"
    
    center = mp.Vector3(center_x, center_y, center_z)
    
    # Map axis string to meep direction
    axis_map = {"x": mp.X, "y": mp.Y, "z": mp.Z}
    mp_axis = axis_map.get(axis.lower(), mp.Z)
    
    material = mp.Medium(epsilon=epsilon)
    cylinder = mp.Cylinder(radius, height=height, center=center, axis=mp_axis, material=material)
    _sim_context["geometry"].append(cylinder)
    
    response = f"""Added cylinder geometry:
- Position: center = ({center_x}, {center_y}, {center_z}) μm
- Radius: {radius} μm
- Height: {height} μm
- Axis: {axis}
- Permittivity (ε): {epsilon} (refractive index n ≈ {np.sqrt(epsilon):.3f})
- Total geometry objects: {len(_sim_context["geometry"])}
"""
    return response


@tool("Add Sphere Geometry")
def add_sphere_geometry(
    radius: float,
    epsilon: float,
    center_x: float,
    center_y: float,
    center_z: float = 0.0
) -> str:
    """
    Add a sphere geometric object with specified dielectric constant.
    Common use case: Mie scattering, spherical inclusions in glass.
    
    Args:
        radius: Radius of the sphere (microns)
        epsilon: Electric permittivity (ε = n² where n is refractive index)
        center_x: Center x coordinate (microns)
        center_y: Center y coordinate (microns)
        center_z: Center z coordinate (microns)
    
    Returns:
        Confirmation of added sphere
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    radius = to_float(radius)
    epsilon = to_float(epsilon)
    center_x = to_float(center_x)
    center_y = to_float(center_y)
    center_z = to_float(center_z)
    
    mp = _get_meep()
    
    if _sim_context["dimensions"] is None:
        return "Error: Call create_simulation_cell first"
    
    center = mp.Vector3(center_x, center_y, center_z)
    material = mp.Medium(epsilon=epsilon)
    sphere = mp.Sphere(radius, center=center, material=material)
    _sim_context["geometry"].append(sphere)
    
    response = f"""Added sphere geometry:
- Position: center = ({center_x}, {center_y}, {center_z}) μm
- Radius: {radius} μm
- Permittivity (ε): {epsilon} (refractive index n ≈ {np.sqrt(epsilon):.3f})
- Total geometry objects: {len(_sim_context["geometry"])}
"""
    return response


# =============================================================================
# Material Tools
# =============================================================================

@tool("Set Dispersive Material from Lorentzian")
def set_dispersive_material_lorentzian(
    epsilon_inf: float,
    lorentzian_frequencies: List[float],
    lorentzian_gammas: List[float],
    lorentzient_sigmas: List[float]
) -> str:
    """
    Create a dispersive material using Lorentzian model.
    This is for materials with frequency-dependent permittivity (optical glass).
    
    Args:
        epsilon_inf: Permittivity at infinite frequency
        lorentzian_frequencies: List of resonant frequencies (in Meep units)
        lorentzian_gammas: List of damping coefficients
        lorentzient_sigmas: List of oscillator strengths
    
    Returns:
        Summary of the created dispersive material
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    # Handle case where LLM might send strings instead of floats
    epsilon_inf = to_float(epsilon_inf)
    # Convert any string elements in lists
    lorentzian_frequencies = [to_float(f) if isinstance(f, str) else f for f in lorentzian_frequencies]
    lorentzian_gammas = [to_float(g) if isinstance(g, str) else g for g in lorentzian_gammas]
    lorentzient_sigmas = [to_float(s) if isinstance(s, str) else s for s in lorentzient_sigmas]
    
    mp = _get_meep()
    
    if len(lorentzian_frequencies) != len(lorentzian_gammas) or \
       len(lorentzian_frequencies) != len(lorentzient_sigmas):
        return "Error: All three lists must have the same length"
    
    susceptibility = []
    for f0, gamma, sigma in zip(lorentzian_frequencies, lorentzian_gammas, lorentzient_sigmas):
        susceptibility.append(mp.LorentzianSusceptibility(f0, gamma, sigma))
    
    material = mp.Medium(epsilon=epsilon_inf, E_susceptibilities=susceptibility)
    # Store material in context for use in next geometry addition
    _sim_context["current_dispersive_material"] = material
    
    response = f"""Created Lorentzian dispersive material:
- ε∞: {epsilon_inf} (n∞ ≈ {np.sqrt(epsilon_inf):.3f})
- Number of Lorentzian terms: {len(susceptibility)}
- Terms:
"""
    for i, (f0, gamma, sigma) in enumerate(zip(lorentzian_frequencies, lorentzian_gammas, lorentzient_sigmas)):
        response += f"  {i+1}: f₀={f0}, γ={gamma}, σ={sigma}\n"
    
    response += "\nUse this material for subsequent geometry additions"
    return response


@tool("Set Dispersive Material from Refractive Index")
def set_dispersive_material_from_n(
    n: float,
    frequency: float,
    f0: float = 0.0,
    gamma: float = 0.0
) -> str:
    """
    Create a simple dispersive material from a single refractive index at given frequency.
    Convenience wrapper for common optical glass with known n.
    
    Args:
        n: Refractive index at the specified frequency
        frequency: Operating frequency (in Meep units, 1/λ where λ is vacuum wavelength)
        f0: Resonant frequency (default: 0 for Drude model)
        gamma: Damping coefficient (default: 0 for no loss)
    
    Returns:
        Summary of the created dispersive material
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    n = to_float(n)
    frequency = to_float(frequency)
    f0 = to_float(f0)
    gamma = to_float(gamma)
    
    mp = _get_meep()
    
    epsilon_inf = n**2
    sigma = (n**2 - 1) * f0**2 / (frequency**2 - f0**2 + 1j*gamma*frequency) if f0 != 0 else 0
    
    material = mp.Medium(epsilon_diagonal=[epsilon_inf])
    
    if f0 > 0:
        susceptibility = [mp.LorentzianSusceptibility(f0, gamma, sigma.real)]
        material = mp.Medium(epsilon=epsilon_inf, E_susceptibilities=susceptibility)
    
    _sim_context["current_dispersive_material"] = material
    
    response = f"""Created dispersive material from refractive index:
- Refractive index n = {n} at frequency f = {frequency}
- ε∞ = {epsilon_inf}
- f0 = {f0}, gamma = {gamma}
"""
    return response


# =============================================================================
# Source Tools
# =============================================================================

@tool("Add Continuous Wave Source")
def add_continuous_wave_source(
    frequency: float,
    component: str,
    center_x: float,
    center_y: float = 0.0,
    center_z: float = 0.0
) -> str:
    """
    Add a continuous wave (CW) current source at fixed frequency.
    Good for steady-state field patterns at specific wavelength.
    
    Args:
        frequency: Source frequency (Meep units: f = 1/λ where λ is vacuum wavelength)
        component: Field component (Ez, Ex, Ey, Hz, Hx, Hy)
        center_x: Source center x coordinate (microns)
        center_y: Source center y coordinate (microns)
        center_z: Source center z coordinate (microns)
    
    Returns:
        Confirmation of added source
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    frequency = to_float(frequency)
    center_x = to_float(center_x)
    center_y = to_float(center_y)
    center_z = to_float(center_z)
    
    mp = _get_meep()
    
    if _sim_context["dimensions"] is None:
        return "Error: Call create_simulation_cell first"
    
    # Map component string to meep component
    component_map = {
        "ez": mp.Ez, "ex": mp.Ex, "ey": mp.Ey,
        "hz": mp.Hz, "hx": mp.Hx, "hy": mp.Hy
    }
    mp_component = component_map.get(component.lower(), mp.Ez)
    
    center = mp.Vector3(center_x, center_y, center_z)
    source = mp.Source(mp.ContinuousSource(frequency), component=mp_component, center=center)
    _sim_context["sources"].append(source)
    
    if frequency > 0:
        wavelength = 1.0 / frequency
        wavelength_str = f"{wavelength:.3f}"
    else:
        wavelength_str = "Infinite"
    response = f"""Added continuous wave (CW) source:
- Frequency: {frequency} (vacuum wavelength = {wavelength_str} μm)
- Field component: {component}
- Position: center = ({center_x}, {center_y}, {center_z}) μm
- Total sources: {len(_sim_context["sources"])}
"""
    return response


@tool("Add Gaussian Pulse Source")
def add_gaussian_pulse_source(
    center_frequency: float,
    frequency_width: float,
    component: str,
    center_x: float,
    center_y: float = 0.0,
    center_z: float = 0.0
) -> str:
    """
    Add a Gaussian pulsed source for broadband simulations.
    Good for calculating transmittance/reflection spectra over a range of frequencies.
    
    Meep frequency units: f = 1/λ where λ is vacuum wavelength in microns.
    For example: at wavelength 589nm = 0.589 μm → center_frequency ≈ 1/0.589 = 1.7.
    
    Args:
        center_frequency: Center frequency of the pulse (Meep units: f = 1/λ)
        frequency_width: Width of the frequency range (Meep units)
        component: Field component (Ez, Ex, Ey, Hz, Hx, Hy)
        center_x: Source center x coordinate (microns)
        center_y: Source center y coordinate (microns)
        center_z: Source center z coordinate (microns)
    
    Returns:
        Confirmation of added source
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    center_frequency = to_float(center_frequency)
    frequency_width = to_float(frequency_width)
    center_x = to_float(center_x)
    center_y = to_float(center_y)
    center_z = to_float(center_z)
    
    mp = _get_meep()
    
    if _sim_context["dimensions"] is None:
        return "Error: Call create_simulation_cell first"
    
    component_map = {
        "ez": mp.Ez, "ex": mp.Ex, "ey": mp.Ey,
        "hz": mp.Hz, "hx": mp.Hx, "hy": mp.Hy
    }
    mp_component = component_map.get(component.lower(), mp.Ez)
    
    center = mp.Vector3(center_x, center_y, center_z)
    source = mp.Source(mp.GaussianSource(center_frequency, frequency_width), 
                       component=mp_component, center=center)
    _sim_context["sources"].append(source)
    
    center_wavelength = 1.0 / center_frequency
    response = f"""Added Gaussian pulse source:
- Center frequency: {center_frequency} (center wavelength = {center_wavelength:.3f} μm)
- Frequency width: {frequency_width}
- Covers frequency range: {center_frequency - 2*frequency_width} to {center_frequency + 2*frequency_width}
- Field component: {component}
- Position: center = ({center_x}, {center_y}, {center_z}) μm
- Total sources: {len(_sim_context["sources"])}
"""
    return response


# =============================================================================
# Simulation Execution Tools
# =============================================================================

@tool("Initialize Simulation")
def initialize_simulation(
    resolution: int,
    default_material_epsilon: float = 1.0
) -> str:
    """
    Initialize the simulation object after geometry and sources are set up.
    Must be called before run_simulation.
    
    Args:
        resolution: Number of pixels per micron (higher = more accurate but slower)
        default_material_epsilon: Permittivity of default material (air = 1.0)
    
    Returns:
        Simulation initialization summary
    """
    # Convert string inputs to float/int if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 1.0
        return float(val)
    
    def to_int(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 10
        return int(val)
    
    resolution = to_int(resolution)
    default_material_epsilon = to_float(default_material_epsilon)
    
    mp = _get_meep()
    
    if _sim_context["dimensions"] is None:
        return "Error: Call create_simulation_cell first"
    
    if len(_sim_context["sources"]) == 0:
        return "Warning: No sources added to simulation"
    
    dimensions = _sim_context["dimensions"]
    cell_size = _sim_context["cell_size"]
    
    # Get cell vector
    if dimensions == 1:
        cell = mp.Vector3(cell_size[0])
    elif dimensions == 2:
        cell = mp.Vector3(cell_size[0], cell_size[1])
    else:
        cell = mp.Vector3(cell_size[0], cell_size[1], cell_size[2])
    
    # Create simulation object
    sim = mp.Simulation(
        cell_size=cell,
        geometry=_sim_context["geometry"],
        sources=_sim_context["sources"],
        boundary_layers=_sim_context["pml_layers"],
        resolution=resolution,
        default_material=mp.Medium(epsilon=default_material_epsilon)
    )
    
    _sim_context["sim"] = sim
    
    response = f"""Simulation initialized:
- Dimensions: {dimensions}D
- Resolution: {resolution} pixels/μm
- Default material ε: {default_material_epsilon} (n ≈ {np.sqrt(default_material_epsilon):.3f})
- Geometry objects: {len(_sim_context["geometry"])}
- Sources: {len(_sim_context["sources"])}
- PML layers: {len(_sim_context["pml_layers"])}
"""
    return response


@tool("Run Simulation Until Time")
def run_simulation_until_time(
    run_until: float
) -> str:
    """
    Run the FDTD simulation until the specified time.
    
    Args:
        run_until: Time to run simulation to (Meep units = c·t where c is speed of light)
    
    Returns:
        Simulation completion summary
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 100.0
        return float(val)
    
    run_until = to_float(run_until)
    
    mp = _get_meep()
    
    sim = _sim_context["sim"]
    if sim is None:
        return "Error: Call initialize_simulation first"
    
    sim.run(until=run_until)
    
    response = f"""Simulation completed:
 - Ran until time: {run_until}
 - Final simulation time: {sim.round_time}
"""
    return response


# =============================================================================
# Analysis and Output Tools
# =============================================================================

@tool("Add Flux Monitor")
def add_flux_monitor(
    plane_center_x: float,
    plane_center_y: float = 0.0,
    plane_center_z: float = 0.0,
    plane_size_y: float = 0.0,
    plane_size_z: float = 0.0,
    direction: str = "x",
    fcen: float = 0.0,
    df: float = 0.0,
    nfreq: int = 1
) -> str:
    """
    Add a flux monitor for calculating transmittance/reflectance.
    Must add this before running simulation.
    
    Meep frequency units: f = 1/λ where λ is vacuum wavelength in microns.
    For example: at wavelength 589nm = 0.589 μm → fcen ≈ 1/0.589 = 1.7.
    
    Args:
        plane_center_x: Center x coordinate of the monitor plane
        plane_center_y: Center y coordinate (required for 2D/3D)
        plane_center_z: Center z coordinate (required for 3D)
        plane_size_y: Size of monitor in y direction (required for 2D/3D)
        plane_size_z: Size of monitor in z direction (required for 3D)
        direction: Direction flux is traveling ("x", "y", "z")
        fcen: Center frequency for DFT calculation (Meep units: f = 1/λ)
        df: Frequency width (Meep units)
        nfreq: Number of frequency points to sample
    
    Returns:
        Monitor ID and summary
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    def to_int(val):
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 1
        return int(val)
    
    plane_center_x = to_float(plane_center_x)
    plane_center_y = to_float(plane_center_y)
    plane_center_z = to_float(plane_center_z)
    plane_size_y = to_float(plane_size_y)
    plane_size_z = to_float(plane_size_z)
    fcen = to_float(fcen)
    df = to_float(df)
    nfreq = to_int(nfreq)
    
    mp = _get_meep()
    
    sim = _sim_context["sim"]
    if sim is None:
        return "Error: Call initialize_simulation first"
    
    direction_map = {"x": mp.X, "y": mp.Y, "z": mp.Z}
    mp_dir = direction_map.get(direction.lower(), mp.X)
    
    center = mp.Vector3(plane_center_x, plane_center_y, plane_center_z)
    if _sim_context["dimensions"] == 1:
        # In 1D, the flux region is just a point
        size = mp.Vector3(0)
    elif _sim_context["dimensions"] == 2:
        if direction == "x":
            size = mp.Vector3(0, plane_size_y, 0)
        elif direction == "y":
            size = mp.Vector3(plane_size_y, 0, 0)
        else:
            size = mp.Vector3(plane_size_y, 0, 0)
    else:  # 3D
        if direction == "x":
            size = mp.Vector3(0, plane_size_y, plane_size_z)
        elif direction == "y":
            size = mp.Vector3(plane_size_y, 0, plane_size_z)
        else:
            size = mp.Vector3(plane_size_y, plane_size_z, 0)
    
    flux_region = mp.FluxRegion(center=center, size=size, direction=mp_dir)
    # Meep requires frequency parameters: fcen, df, nfreq
    # This sets up DFT flux calculation at nfreq points
    flux_id = sim.add_flux(fcen, df, nfreq, flux_region)
    if "flux_monitors" not in _sim_context:
        _sim_context["flux_monitors"] = {}
    
    monitor_name = f"flux_{flux_id}"
    _sim_context["flux_monitors"][monitor_name] = flux_id
    
    response = f"""Added flux monitor:
- Monitor ID: {flux_id}
- Center position: ({plane_center_x}, {plane_center_y}, {plane_center_z}) μm
- Direction: {direction}
- Plane size: y={plane_size_y}, z={plane_size_z}
- Frequency: center={fcen}, width={df}, points={nfreq}
"""
    return response


@tool("Calculate Transmittance Reflectance")
def calculate_transmittance_reflectance(
    incident_flux_id,
    transmitted_flux_id,
    reflected_flux_id = None,
    frequency_min: float = 0.0,
    frequency_max: float = 0.5,
    nfreq: int = 100,
    output_filename: str = "spectrum.txt"
) -> str:
    """
    Calculate transmittance and reflectance spectrum from flux monitors.
    
    Args:
        incident_flux_id: Flux monitor object for incident flux
        transmitted_flux_id: Flux monitor object for transmitted flux
        reflected_flux_id: Optional flux monitor object for reflected flux
        frequency_min: Minimum frequency to calculate
        frequency_max: Maximum frequency to calculate
        nfreq: Number of frequency points
        output_filename: Filename to save spectrum data
    
    Returns:
        Summary with transmittance values at key frequencies
    """
    # Convert string inputs to float/int if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    def to_int(val):
        # If it's already a DftFlux object (from direct API call), just return it
        # Check if it's not a basic type - it's likely already the flux object
        if not isinstance(val, (str, int, float, type(None))):
            return val
        if val is None:
            return None
        if isinstance(val, str):
            # Check if this looks like a string representation of an object
            if '<meep.' in val and 'object at' in val:
                # This is just the repr string from LLM output - we can't use it directly
                # but we expect the actual object is stored in our context
                # Return None and the error will indicate this
                return None
            try:
                return int(val.strip())
            except ValueError:
                return 100
        if isinstance(val, float):
            return int(val)
        return val
    
    incident_flux_id = to_int(incident_flux_id)
    transmitted_flux_id = to_int(transmitted_flux_id)
    if reflected_flux_id is not None:
        reflected_flux_id = to_int(reflected_flux_id)
    
    frequency_min = to_float(frequency_min)
    frequency_max = to_float(frequency_max)
    nfreq = to_int(nfreq)
    
    mp = _get_meep()
    
    sim = _sim_context["sim"]
    if sim is None:
        return "Error: Simulation not initialized or run"
    
    output_path = os.path.join(_sim_context["output_dir"], output_filename)
    
    # Get flux data
    frequencies = np.linspace(frequency_min, frequency_max, nfreq)
    incident_flux = mp.get_fluxes(incident_flux_id)
    transmitted_flux = mp.get_fluxes(transmitted_flux_id)
    
    # Check if we got frequency data from DFT flux
    # In newer versions of meep, get_fluxes returns for each frequency
    if len(incident_flux) != len(frequencies):
        # If we have one value per monitor, duplicate for all frequencies
        if len(incident_flux) == 1:
            incident_flux = [incident_flux[0]] * len(frequencies)
            transmitted_flux = [transmitted_flux[0]] * len(frequencies)
    
    # Calculate transmittance
    transmittance = []
    reflectance = []
    res_lines = ["frequency wavelength transmittance reflectance"]
    
    for f, inc, trans in zip(frequencies, incident_flux, transmitted_flux):
        t = abs(trans / inc) if inc != 0 else 0
        transmittance.append(t)
        r = 0.0
        if reflected_flux_id is not None:
            refl_flux = mp.get_fluxes(reflected_flux_id)[0]
            r = abs(refl_flux / inc) if inc != 0 else 0
            reflectance.append(r)
        res_lines.append(f"{f:.6f} {1.0/f:.6f} {t:.6f} {r:.6f}")
    
    # Save to file
    with open(output_path, "w") as f:
        f.write("\n".join(res_lines))
    
    # Return summary
    mid_idx = nfreq // 2
    response = f"""Transmittance/reflectance calculation completed:
- Frequency range: {frequency_min} to {frequency_max} ({nfreq} points)
- Output saved to: {output_path}
- Summary:
  - At minimum frequency {frequency_min}: T = {transmittance[0]:.4f}
  - At center frequency {(frequency_min + frequency_max)/2}: T = {transmittance[mid_idx]:.4f}
  - At maximum frequency {frequency_max}: T = {transmittance[-1]:.4f}
"""
    if reflected_flux_id is not None:
        response += f"  - At center frequency: R = {reflectance[mid_idx]:.4f}\n"
    
    response += f"  - Sum T+R at center: {transmittance[mid_idx] + (reflectance[mid_idx] if reflected_flux_id is not None else 0):.4f}\n\n"
    
    # Include the full data in the response for agent access (no file reading needed)
    response += "Full data (frequency wavelength transmittance reflectance):\n"
    response += "----------------------------------------\n"
    # Limit output to avoid too long text, show key points if nfreq is large
    if nfreq <= 20:
        # Show all points
        for line in res_lines[1:]:  # skip header
            response += line + "\n"
    else:
        # Show first 5, middle 5, last 5 points to keep response manageable
        for line in res_lines[1:6]:
            response += line + "\n"
        response += "             ...\n"
        start_mid = max(1, nfreq // 2 - 2)
        end_mid = min(nfreq, nfreq // 2 + 3)
        for line in res_lines[start_mid+1:end_mid+1]:  # +1 for header
            response += line + "\n"
        response += "             ...\n"
        for line in res_lines[-5:]:
            response += line + "\n"
    
    return response


@tool("Extract Electric Field Profile")
def extract_electric_field_profile(
    component: str,
    output_filename: str = "field_profile.txt",
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None
) -> str:
    """
    Extract the electric field profile along a line or plane.
    Must be called after simulation has run.
    
    Args:
        component: Field component to extract (Ex, Ey, Ez)
        output_filename: Filename to save field data
        x: Fixed x coordinate (extract yz plane), leave None (don't include) to vary x
        y: Fixed y coordinate (extract xz plane), leave None (don't include) to vary y
        z: Fixed z coordinate (extract xy plane), leave None (don't include) to vary z
    
    Returns:
        Extraction summary with output file location
    """
    # Convert string inputs to float if needed (handles LLM outputting strings)
    def to_float(val):
        if val is None:
            return None
        if isinstance(val, str):
            val = val.strip().lower()
            if val == "null" or val == "none" or val == "":
                return None
            try:
                return float(val)
            except ValueError:
                return None
        return float(val)
    
    x = to_float(x)
    y = to_float(y)
    z = to_float(z)
    
    mp = _get_meep()
    
    sim = _sim_context["sim"]
    if sim is None:
        return "Error: Simulation not initialized or run"
    
    component_map = {"ex": mp.Ex, "ey": mp.Ey, "ez": mp.Ez}
    mp_component = component_map.get(component.lower(), mp.Ez)
    
    output_path = os.path.join(_sim_context["output_dir"], output_filename)
    
    # Get field data
    field_data = sim.get_array(center=mp.Vector3(x or 0, y or 0, z or 0),
                              size=sim.cell_size,
                              component=mp_component)
    
    # Save to text file
    with open(output_path, "w") as f:
        # Write header
        dims = field_data.shape
        f.write(f"# {component} field extracted from Meep simulation\n")
        f.write(f"# Dimensions: {dims}\n")
        f.write(f"# Fixed: x={x}, y={y}, z={z}\n")
        
        # Write data
        if len(dims) == 1:
            for i, val in enumerate(field_data):
                f.write(f"{i} {val:.6e}\n")
        elif len(dims) == 2:
            for i in range(dims[0]):
                for j in range(dims[1]):
                    f.write(f"{i} {j} {field_data[i,j]:.6e}\n")
        else:
            # 3D - just save summary stats
            f.write(f"# 3D field has {dims[0]} × {dims[1]} × {dims[2]} points\n")
            f.write(f"# Min: {np.min(field_data):.6e}, Max: {np.max(field_data):.6e}\n")
    
    response = f"""Field profile extraction completed:
- Component: {component}
- Output saved to: {output_path}
- Data shape: {field_data.shape}
- Minimum value: {np.min(field_data):.6e}
- Maximum value: {np.max(field_data):.6e}
- Mean absolute value: {np.mean(np.abs(field_data)):.6e}
"""

    # Include sample data in response for agent access (no file reading needed)
    # Show a sampling of the data
    response += "\nSample data (sampled points):\n"
    response += "----------------------------------------\n"
    
    if len(field_data.shape) == 1:
        # 1D - sample every N points
        step = max(1, len(field_data) // 20)
        count = 0
        for i in range(0, len(field_data)):
            if count < 20 and i % step == 0:
                response += f"  {i} {field_data[i]:.6e}\n"
                count += 1
        if len(field_data) // step > 20:
            response += "             ...\n"
    elif len(field_data.shape) == 2:
        # 2D - sample center line
        ny, nx = field_data.shape
        center_y = ny // 2
        step = max(1, nx // 20)
        for x in range(0, nx, step):
            response += f"  {center_y} {x} {field_data[center_y, x]:.6e}\n"
    else:
        # 3D - just show stats already done
        pass

    return response


@tool("Find Resonant Frequencies")
def find_resonant_frequencies(
    flux_monitor_id: int,
    frequency_min: float,
    frequency_max: float,
    number_of_modes: int = 3,
    output_filename: str = "resonances.txt"
) -> str:
    """
    Find resonant frequencies using harmonic inversion (Harminv).
    
    Args:
        flux_monitor_id: Flux monitor ID to analyze
        frequency_min: Minimum frequency to search
        frequency_max: Maximum frequency to search
        number_of_modes: Maximum number of modes to find
        output_filename: Filename to save results
    
    Returns:
        List of found resonant frequencies and their Q factors
    """
    # Convert string inputs to float/int if needed (handles LLM outputting strings)
    def to_float(val):
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                return 0.0
        return float(val)
    
    def to_int(val):
        # If it's already a DftFlux object (from direct API call), just return it
        # Check if it's not a basic type - it's likely already the flux object
        if not isinstance(val, (str, int, float, type(None))):
            return val
        if val is None:
            return None
        if isinstance(val, str):
            # Check if this looks like a string representation of an object
            if '<meep.' in val and 'object at' in val:
                # This is just the repr string from LLM output - we can't use it directly
                # but we expect the actual object is stored in our context
                # Return None and the error will indicate this
                return None
            try:
                return int(val.strip())
            except ValueError:
                return 3
        if isinstance(val, float):
            return int(val)
        return val
    
    flux_monitor_id = to_int(flux_monitor_id)
    frequency_min = to_float(frequency_min)
    frequency_max = to_float(frequency_max)
    number_of_modes = to_int(number_of_modes)
    
    mp = _get_meep()
    
    sim = _sim_context["sim"]
    if sim is None:
        return "Error: Simulation not initialized or run"
    
    output_path = os.path.join(_sim_context["output_dir"], output_filename)
    
    # Get Harminv results
    results = sim.harminv(flux_monitor_id, frequency_min, frequency_max, number_of_modes)
    
    # Save results
    with open(output_path, "w") as f:
        f.write("frequency Q factor\n")
        for res in results:
            f.write(f"{res.freq:.6f} {res.Q:.2f}\n")
    
    response = f"""Resonance analysis completed:
- Searched frequency range: {frequency_min} to {frequency_max}
- Found {len(results)} resonant modes:
"""
    for i, res in enumerate(results):
        response += f"  {i+1}: f = {res.freq:.6f}, Q = {res.Q:.2f}\n"
    
    response += f"\nResults saved to: {output_path}"
    return response


@tool("Save Simulation to HDF5")
def save_simulation_to_hdf5(
    output_filename: str = "simulation.h5",
    include_fields: bool = True
) -> str:
    """
    Save the current simulation state to HDF5 file.
    
    Args:
        output_filename: Output HDF5 filename
        include_fields: Whether to include field data in the save
    
    Returns:
        Confirmation of save location
    """
    mp = _get_meep()
    
    sim = _sim_context["sim"]
    if sim is None:
        return "Error: Simulation not initialized"
    
    output_path = os.path.join(_sim_context["output_dir"], output_filename)
    sim.output_hdf5(output_path, include_fields=include_fields)
    
    response = f"""Simulation saved to HDF5:
- File: {output_path}
- Included fields: {include_fields}
"""
    return response


@tool("Clear Current Simulation")
def clear_current_simulation() -> str:
    """
    Clear the current simulation context and prepare for a new simulation.
    Call this before starting a completely new simulation.
    
    Returns:
        Confirmation that context was cleared
    """
    _reset_sim_context()
    return f"""Simulation context cleared. Output directory for new simulations: {_sim_context["output_dir"]}
"""


@tool("Get Simulation Output Directory")
def get_simulation_output_directory() -> str:
    """
    Get the current simulation output directory path where all output files are saved.
    
    Returns:
        Output directory path
    """
    return f"Simulation output directory: {_sim_context['output_dir']}"
