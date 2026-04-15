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
    # Get project root directory (parent of tools directory)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    output_dir = os.path.join(project_root, "output", "meep_simulations")

    _sim_context = {
        "sim": None,
        "geometry": [],
        "sources": [],
        "pml_layers": [],
        "dimensions": None,
        "cell_size": None,
        "current_filename": None,
        "output_dir": output_dir
    }
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)


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

    # Validate geometry is within simulation cell
    dimensions = _sim_context["dimensions"]
    cell_size = _sim_context["cell_size"]

    # Calculate half sizes for the block
    # Check boundaries: if size is inf, it means the block extends across entire cell (no boundary check needed)
    validation_errors = []
    cell_half_x = cell_size[0] / 2.0
    if size_x != float('inf'):
        half_x = size_x / 2.0
        if (center_x - half_x < -cell_half_x) or (center_x + half_x > cell_half_x):
            validation_errors.append(f"Block extends beyond x boundaries: [{-cell_half_x}, {cell_half_x}]")

    if dimensions >= 2:
        cell_half_y = cell_size[1] / 2.0
        if size_y != float('inf'):
            half_y = size_y / 2.0
            if (center_y - half_y < -cell_half_y) or (center_y + half_y > cell_half_y):
                validation_errors.append(f"Block extends beyond y boundaries: [{-cell_half_y}, {cell_half_y}]")

    if dimensions >= 3:
        cell_half_z = cell_size[2] / 2.0
        if size_z != float('inf'):
            half_z = size_z / 2.0
            if (center_z - half_z < -cell_half_z) or (center_z + half_z > cell_half_z):
                validation_errors.append(f"Block extends beyond z boundaries: [{-cell_half_z}, {cell_half_z}]")

    if validation_errors:
        error_msg = "Error: Block geometry is outside simulation cell:\n"
        error_msg += "\n".join(f"- {err}" for err in validation_errors)
        error_msg += f"\nCell size: {cell_size} μm"
        return error_msg

    # Create center vector
    center = mp.Vector3(center_x, center_y, center_z)
    size = mp.Vector3(size_x, size_y, size_z)

    material = mp.Medium(epsilon=epsilon)
    block = mp.Block(size, center=center, material=material)
    _sim_context["geometry"].append(block)

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

    # Validate geometry is within simulation cell
    dimensions = _sim_context["dimensions"]
    cell_size = _sim_context["cell_size"]

    # Cylinder extends along axis, radius is perpendicular to axis
    # Check that the entire cylinder (radius + center offset) is within cell
    validation_errors = []
    axis_lower = axis.lower()

    if axis_lower != "x":
        cell_half_x = cell_size[0] / 2.0
        if abs(center_x) + radius > cell_half_x:
            validation_errors.append(f"Cylinder extends beyond x boundaries: [{-cell_half_x}, {cell_half_x}]")

    if dimensions >= 2 and axis_lower != "y":
        cell_half_y = cell_size[1] / 2.0
        if abs(center_y) + radius > cell_half_y:
            validation_errors.append(f"Cylinder extends beyond y boundaries: [{-cell_half_y}, {cell_half_y}]")

    if dimensions >= 3 and axis_lower != "z":
        cell_half_z = cell_size[2] / 2.0
        if abs(center_z) + radius > cell_half_z:
            validation_errors.append(f"Cylinder extends beyond z boundaries: [{-cell_half_z}, {cell_half_z}]")

    # Check height along axis
    if height != float('inf'):
        half_height = height / 2.0
        if axis_lower == "x":
            cell_half_x = cell_size[0] / 2.0
            if (center_x - half_height < -cell_half_x) or (center_x + half_height > cell_half_x):
                validation_errors.append(f"Cylinder extends beyond x boundaries: [{-cell_half_x}, {cell_half_x}]")
        elif axis_lower == "y" and dimensions >= 2:
            cell_half_y = cell_size[1] / 2.0
            if (center_y - half_height < -cell_half_y) or (center_y + half_height > cell_half_y):
                validation_errors.append(f"Cylinder extends beyond y boundaries: [{-cell_half_y}, {cell_half_y}]")
        elif axis_lower == "z" and dimensions >= 3:
            cell_half_z = cell_size[2] / 2.0
            if (center_z - half_height < -cell_half_z) or (center_z + half_height > cell_half_z):
                validation_errors.append(f"Cylinder extends beyond z boundaries: [{-cell_half_z}, {cell_half_z}]")
    # If height is inf, cylinder extends across entire cell - no boundary check needed

    if validation_errors:
        error_msg = "Error: Cylinder geometry is outside simulation cell:\n"
        error_msg += "\n".join(f"- {err}" for err in validation_errors)
        error_msg += f"\nCell size: {cell_size} μm"
        return error_msg

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

    # Validate geometry is within simulation cell
    dimensions = _sim_context["dimensions"]
    cell_size = _sim_context["cell_size"]

    validation_errors = []
    cell_half_x = cell_size[0] / 2.0
    if (abs(center_x) + radius) > cell_half_x:
        validation_errors.append(f"Sphere extends beyond x boundaries: [{-cell_half_x}, {cell_half_x}]")

    if dimensions >= 2:
        cell_half_y = cell_size[1] / 2.0
        if (abs(center_y) + radius) > cell_half_y:
            validation_errors.append(f"Sphere extends beyond y boundaries: [{-cell_half_y}, {cell_half_y}]")

    if dimensions >= 3:
        cell_half_z = cell_size[2] / 2.0
        if (abs(center_z) + radius) > cell_half_z:
            validation_errors.append(f"Sphere extends beyond z boundaries: [{-cell_half_z}, {cell_half_z}]")

    if validation_errors:
        error_msg = "Error: Sphere geometry is outside simulation cell:\n"
        error_msg += "\n".join(f"- {err}" for err in validation_errors)
        error_msg += f"\nCell size: {cell_size} μm"
        return error_msg

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
        susceptibility = [mp.LorentzianSusceptibility(f0, gamma, sigma)]
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

    **IMPORTANT: Correct Placement Instructions**:
    - For a structure along the x-axis (most common):
      - **Incident flux monitor**: Place BEFORE the structure, on the incident side
      - **Transmitted flux monitor**: Place AFTER the structure, on the transmitted side
      - **Reflected flux monitor**: Place BEFORE the structure, on the incident side opposite from transmission
    - Example for 1D finite slab of thickness 2μm centered at 0:
      - Incident: plane_center_x = -1.5
      - Transmitted: plane_center_x = +1.5
      - Reflected: plane_center_x = -4.0

    Meep frequency units: f = 1/λ where λ is vacuum wavelength in microns.
    For example: at wavelength 589nm = 0.589 μm → fcen ≈ 1/0.589 = 1.7.

    Args:
        plane_center_x: Center x coordinate of the monitor plane
        plane_center_y: Center y coordinate (required for 2D/3D)
        plane_center_z: Center z coordinate (required for 3D)
        plane_size_y: Size of monitor in y direction (required for 2D/3D, must be > 0)
        plane_size_z: Size of monitor in z direction (required for 3D, must be > 0)
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

    # Validate plane size parameters based on dimension
    dimensions = _sim_context["dimensions"]
    validation_errors = []
    if dimensions >= 2 and plane_size_y <= 0:
        validation_errors.append("- For 2D/3D simulation, plane_size_y must be > 0")
    if dimensions >= 3 and plane_size_z <= 0:
        validation_errors.append("- For 3D simulation, plane_size_z must be > 0")

    if validation_errors:
        error_msg = "Error: Missing or invalid plane size parameters:\n"
        error_msg += "\n".join(validation_errors)
        error_msg += f"\nCurrent dimensions: {dimensions}D"
        return error_msg

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

    **Normalization Method**:
    This implementation uses the **one-simulation method**:
    - Place incident flux monitor BEFORE the structure
    - Place transmitted flux monitor AFTER the structure
    - Transmittance is calculated as: T = transmitted_flux / incident_flux
    - Reflectance (if provided) is: R = reflected_flux / incident_flux
    - This is correct when all monitors are in the same simulation

    Alternative (not implemented here): **two-simulation method**
    - Run one simulation WITHOUT the structure to get reference flux
    - Run another simulation WITH the structure
    - T = P_with_structure / P_reference
    - The one-simulation method used here is simpler and works for most cases

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

    # Get actual frequencies from Meep's flux monitor
    frequencies = mp.get_flux_freqs(incident_flux_id)
    incident_flux = mp.get_fluxes(incident_flux_id)
    transmitted_flux = mp.get_fluxes(transmitted_flux_id)

    # If frequencies is empty (older Meep versions or wrong flux id), fall back to manual linspace
    if len(frequencies) == 0:
        frequencies = np.linspace(frequency_min, frequency_max, nfreq).tolist()

    # Calculate transmittance
    transmittance = []
    reflectance = []
    res_lines = ["frequency wavelength transmittance reflectance"]

    # Ensure all arrays have matching length
    n_freqs = len(frequencies)
    if len(incident_flux) != n_freqs and len(incident_flux) == 1:
        incident_flux = [incident_flux[0]] * n_freqs
    if len(transmitted_flux) != n_freqs and len(transmitted_flux) == 1:
        transmitted_flux = [transmitted_flux[0]] * n_freqs

    for f, inc, trans in zip(frequencies, incident_flux, transmitted_flux):
        t = abs(trans / inc) if inc != 0 else 0
        transmittance.append(t)
        r = 0.0
        if reflected_flux_id is not None:
            refl_flux = mp.get_fluxes(reflected_flux_id)[0]
            r = abs(refl_flux / inc) if inc != 0 else 0
            reflectance.append(r)
        wavelength = 1.0 / f if f != 0 else 0.0
        res_lines.append(f"{f:.6f} {wavelength:.6f} {t:.6f} {r:.6f}")
    
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


# =============================================================================
# File Reading Tools (for accessing saved outputs from other agents)
# =============================================================================

@tool("Read Transmittance/Reflectance Spectrum File")
def read_spectrum_file(
    file_path: str
) -> str:
    """
    Read a transmittance/reflectance spectrum data file saved from a previous simulation.
    Enables other agents to load the full spectrum data for analysis.

    Args:
        file_path: Path to the spectrum text file (e.g. output/meep_simulations/spectrum.txt)

    Returns:
        Parsed spectrum data with all frequency, transmittance, and reflectance values
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        with open(file_path, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        if len(lines) == 0:
            return f"Error: File {file_path} is empty"

        # First line is header
        if lines[0].startswith('frequency'):
            data_lines = lines[1:]
        else:
            data_lines = lines

        frequencies = []
        wavelengths = []
        transmittances = []
        reflectances = []

        for line in data_lines:
            parts = line.split()
            if len(parts) >= 3:
                f = float(parts[0])
                wl = float(parts[1])
                t = float(parts[2])
                r = float(parts[3]) if len(parts) >= 4 else 0.0
                frequencies.append(f)
                wavelengths.append(wl)
                transmittances.append(t)
                reflectances.append(r)

        if len(frequencies) == 0:
            return f"Error: No valid data found in {file_path}"

        # Calculate statistics
        min_t = min(transmittances)
        max_t = max(transmittances)
        avg_t = sum(transmittances) / len(transmittances)

        response = f"""Successfully read spectrum file: {file_path}
- Number of frequency points: {len(frequencies)}
- Frequency range: {min(frequencies):.6f} to {max(frequencies):.6f}
- Wavelength range: {min(wavelengths):.6f} to {max(wavelengths):.6f} μm
- Transmittance: min={min_t:.4f}, max={max_t:.4f}, avg={avg_t:.4f}

Data (showing first 10 points):
frequency  wavelength  transmittance  reflectance
"""
        for f, wl, t, r in zip(frequencies[:10], wavelengths[:10], transmittances[:10], reflectances[:10]):
            response += f"{f:.6f}  {wl:.4f}  {t:.4f}  {r:.4f}\n"

        if len(frequencies) > 10:
            response += f"... ({len(frequencies) - 10} more points)\n"

        return response

    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


@tool("Read Electric Field Profile File")
def read_field_profile(
    file_path: str
) -> str:
    """
    Read an electric field profile data file saved from a previous simulation.
    Enables other agents to load the full field data for analysis.

    Args:
        file_path: Path to the field profile text file (e.g. output/meep_simulations/field_profile.txt)

    Returns:
        Parsed field profile with dimensions and sample data
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        with open(file_path, 'r') as f:
            lines = [line.rstrip('\n') for line in f]

        # Parse header comments for dimensions
        dims = None
        for line in lines:
            if line.startswith('# Dimensions:'):
                # Extract shape tuple
                import re
                match = re.search(r'# Dimensions:\s*\((.*?)\)', line)
                if match:
                    # Split by commas, skip any empty strings (for trailing comma case)
                    parts = [x.strip() for x in match.group(1).split(',') if x.strip()]
                    dims = tuple(int(x) for x in parts)
                break

        # Get data lines (non-comment, non-empty)
        data_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                data_lines.append(stripped)

        if dims is None:
            # Try to infer from data
            if len(data_lines) == 0:
                return f"Error: No valid dimensions found in {file_path}"
            first_line = data_lines[0].split()
            if len(first_line) == 2:
                dims = (len(data_lines),)
            elif len(first_line) == 3:
                # Count unique i and j
                i_vals = set()
                j_vals = set()
                for line in data_lines:
                    parts = line.split()
                    i_vals.add(int(float(parts[0])))
                    j_vals.add(int(float(parts[1])))
                dims = (len(i_vals), len(j_vals))

        if not dims:
            return f"Error: Could not determine dimensions from {file_path}"

        # Read data
        if len(dims) == 1:
            # 1D field
            values = []
            for line in data_lines:
                parts = line.split()
                if len(parts) >= 2:
                    val = float(parts[1])
                    values.append(val)
            values = np.array(values)
            min_val = np.min(values)
            max_val = np.max(values)
            mean_val = np.mean(np.abs(values))

            response = f"""Successfully read 1D field profile: {file_path}
- Number of points: {len(values)}
- Field range: {min_val:.6e} to {max_val:.6e}
- Mean absolute value: {mean_val:.6e}

Sample data (first 20 points):
index  value
"""
            for i, val in enumerate(values[:20]):
                response += f"{i}  {val:.6e}\n"
            if len(values) > 20:
                response += f"... ({len(values) - 20} more points)\n"

            return response

        elif len(dims) == 2:
            # 2D field
            ny, nx = dims
            field = np.zeros(dims)
            for line in data_lines:
                parts = line.split()
                if len(parts) >= 3:
                    i = int(float(parts[0]))
                    j = int(float(parts[1]))
                    val = float(parts[2])
                    if i < ny and j < nx:
                        field[i, j] = val
            min_val = np.min(field)
            max_val = np.max(field)
            mean_val = np.mean(np.abs(field))

            response = f"""Successfully read 2D field profile: {file_path}
- Grid dimensions: {ny} × {nx}
- Field range: {min_val:.6e} to {max_val:.6e}
- Mean absolute value: {mean_val:.6e}

Sample data (center row):
position  value
"""
            center_y = ny // 2
            for j in range(0, nx, max(1, nx // 20)):
                response += f"{center_y},{j}  {field[center_y, j]:.6e}\n"

            return response

        else:
            # 3D field - just show statistics
            response = f"""Successfully read 3D field profile: {file_path}
- Grid dimensions: {dims[0]} × {dims[1]} × {dims[2]}
"""
            # Find statistics from header
            for line in lines:
                if 'Min:' in line and 'Max:' in line:
                    response += line.lstrip('# ') + '\n'
            return response

    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


@tool("Read Resonant Frequencies File")
def read_resonance_file(
    file_path: str
) -> str:
    """
    Read a resonant frequencies results file saved from a previous simulation.
    Enables other agents to load the resonance data for analysis.

    Args:
        file_path: Path to the resonance text file (e.g. output/meep_simulations/resonances.txt)

    Returns:
        List of resonant frequencies with their Q factors
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        with open(file_path, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        if len(lines) == 0:
            return f"Error: File {file_path} is empty"

        # First line is header
        if lines[0].startswith('frequency'):
            data_lines = lines[1:]
        else:
            data_lines = lines

        resonances = []
        for line in data_lines:
            parts = line.split()
            if len(parts) >= 2:
                freq = float(parts[0])
                q = float(parts[1])
                resonances.append((freq, q))

        if len(resonances) == 0:
            return f"Error: No valid resonance data found in {file_path}"

        response = f"""Successfully read resonance file: {file_path}
- Number of resonant modes: {len(resonances)}

Resonant modes (frequency, Q factor):
"""
        for i, (freq, q) in enumerate(resonances, 1):
            wavelength = 1.0 / freq if freq > 0 else 0
            response += f"  {i}: f = {freq:.6f}, λ = {wavelength:.4f} μm, Q = {q:.2f}\n"

        return response

    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


# =============================================================================
# Visualization Tools (plot meep outputs to PNG images)
# =============================================================================

def _get_matplotlib():
    """Import matplotlib lazily to avoid issues when it's not installed."""
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend for saving to file
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        raise ImportError(
            "matplotlib is not installed. Please install it using:\n"
            "pip install matplotlib\n"
            "For more details, see https://matplotlib.org/stable/installation/"
        )


@tool("Plot Transmittance/Reflectance Spectrum")
def plot_transmittance_spectrum(
    spectrum_file_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot transmittance (and reflectance if available) versus frequency/wavelength from a saved spectrum file.
    Creates a PNG image of the spectrum.

    Args:
        spectrum_file_path: Path to the saved spectrum text file
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(spectrum_file_path):
        return f"Error: Spectrum file not found at {spectrum_file_path}"

    try:
        # Read the spectrum data
        with open(spectrum_file_path, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        if lines and lines[0].startswith('frequency'):
            lines = lines[1:]

        frequencies = []
        wavelengths = []
        transmittance = []
        reflectance = []

        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                frequencies.append(float(parts[0]))
                wavelengths.append(float(parts[1]))
                transmittance.append(float(parts[2]))
                if len(parts) >= 4:
                    reflectance.append(float(parts[3]))

        if len(frequencies) == 0:
            return "Error: No valid data found in spectrum file"

        # Determine output path
        if not output_png_path:
            base, _ = os.path.splitext(spectrum_file_path)
            output_png_path = f"{base}_spectrum.png"

        # Create the plot
        fig, ax1 = plt.subplots(figsize=(10, 6))

        # Plot transmittance
        color = 'blue'
        ax1.set_xlabel('Frequency (Meep units, f = 1/λ)')
        ax1.set_ylabel('Transmittance', color=color)
        ax1.plot(frequencies, transmittance, color=color, linewidth=2, label='T')
        ax1.tick_params(axis='y', labelcolor=color)
        ax1.set_ylim(0, 1.05)
        ax1.grid(True, alpha=0.3)

        # Plot reflectance if available
        if len(reflectance) == len(frequencies):
            color = 'red'
            ax2 = ax1.twinx()
            ax2.set_ylabel('Reflectance', color=color)
            ax2.plot(frequencies, reflectance, color=color, linewidth=2, linestyle='--', label='R')
            ax2.tick_params(axis='y', labelcolor=color)
            ax2.set_ylim(0, 1.05)

        # Add wavelength on top x-axis
        ax_top = ax1.twiny()
        ax_top.set_xlim(ax1.get_xlim())

        # Set ticks
        xticks = ax1.get_xticks()
        xticks_valid = [x for x in xticks if x > 0]
        wl_ticks = [1.0 / x for x in xticks_valid]
        ax_top.set_xticks(xticks_valid)
        ax_top.set_xticklabels([f"{wl:.2f}" for wl in wl_ticks])
        ax_top.set_xlabel('Wavelength (μm)')

        # Add title and legend
        if len(reflectance) == len(frequencies):
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='best')
        else:
            ax1.legend(loc='best')

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created spectrum plot:\n- Input: {spectrum_file_path}\n- Output PNG: {output_png_path}\n- Data points: {len(frequencies)}"

    except Exception as e:
        return f"Error creating plot: {str(e)}"


@tool("Plot 1D Electric Field Profile")
def plot_field_profile_1d(
    field_file_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot a 1D electric field profile as a line plot. Creates a PNG image.

    Args:
        field_file_path: Path to the saved 1D field profile text file
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(field_file_path):
        return f"Error: Field file not found at {field_file_path}"

    try:
        # Read the data
        with open(field_file_path, 'r') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        x_coords = []
        values = []
        for i, line in enumerate(lines):
            parts = line.split()
            if len(parts) >= 2:
                x_coords.append(float(parts[0]))
                values.append(float(parts[1]))

        if len(values) == 0:
            return "Error: No valid field data found"

        # Determine output path
        if not output_png_path:
            base, _ = os.path.splitext(field_file_path)
            output_png_path = f"{base}_field.png"

        # Create plot
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(x_coords, values, linewidth=1.5)
        ax.set_xlabel('Grid Point Index')
        ax.set_ylabel('Electric Field Amplitude')
        ax.set_title('1D Electric Field Profile')
        ax.grid(True, alpha=0.3)

        # Add statistics text
        min_val = min(values)
        max_val = max(values)
        rms = np.sqrt(np.mean(np.array(values)**2))
        stats = f"Min: {min_val:.3e}\nMax: {max_val:.3e}\nRMS: {rms:.3e}"
        ax.text(0.02, 0.98, stats, transform=ax.transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created 1D field plot:\n- Input: {field_file_path}\n- Output PNG: {output_png_path}\n- Data points: {len(values)}"

    except Exception as e:
        return f"Error creating plot: {str(e)}"


@tool("Plot 2D Electric Field Profile")
def plot_field_profile_2d(
    field_file_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot a 2D electric field profile as a heatmap. Creates a PNG image.

    Args:
        field_file_path: Path to the saved 2D field profile text file
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(field_file_path):
        return f"Error: Field file not found at {field_file_path}"

    try:
        # Read the data and parse dimensions
        with open(field_file_path, 'r') as f:
            all_lines = [line.rstrip('\n') for line in f]

        # Parse dimensions from header
        dims = None
        for line in all_lines:
            if line.startswith('# Dimensions:'):
                import re
                match = re.search(r'# Dimensions:\s*\((.*?)\)', line)
                if match:
                    dims = tuple(int(x) for x in match.group(1).split(','))
                break

        if dims is None or len(dims) != 2:
            return "Error: File does not contain valid 2D field data"

        ny, nx = dims
        field = np.zeros(dims)

        # Read data lines
        data_lines = [line for line in all_lines if line.strip() and not line.startswith('#')]
        for line in data_lines:
            parts = line.split()
            if len(parts) >= 3:
                i = int(float(parts[0]))
                j = int(float(parts[1]))
                val = float(parts[2])
                if 0 <= i < ny and 0 <= j < nx:
                    field[i, j] = val

        # Determine output path
        if not output_png_path:
            base, _ = os.path.splitext(field_file_path)
            output_png_path = f"{base}_field.png"

        # Create heatmap plot
        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(field, cmap='viridis', aspect='auto')
        ax.set_xlabel('X Grid Index')
        ax.set_ylabel('Y Grid Index')
        ax.set_title('2D Electric Field Profile')

        # Add colorbar
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label('Electric Field Amplitude')

        # Add statistics text
        min_val = np.min(field)
        max_val = np.max(field)
        mean_abs = np.mean(np.abs(field))
        stats = f"Min: {min_val:.3e}\nMax: {max_val:.3e}\nMean|E|: {mean_abs:.3e}"
        ax.text(0.02, 0.98, stats, transform=ax.transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created 2D field heatmap:\n- Input: {field_file_path}\n- Output PNG: {output_png_path}\n- Grid: {ny} × {nx}"

    except Exception as e:
        return f"Error creating plot: {str(e)}"


@tool("Visualize Meep Output (Auto-detect)")
def visualize_meep_output(
    file_path: str
) -> str:
    """
    Auto-detect the type of meep output file and create an appropriate visualization.
    Automatically creates a PNG image in the same directory.

    Args:
        file_path: Path to any meep output file (spectrum, field profile, or resonance)

    Returns:
        Path to the saved PNG image file, or error message if cannot visualize
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    # Try to detect file type by content
    try:
        with open(file_path, 'r') as f:
            first_line = f.readline()

        # Check if it's a spectrum file
        if 'frequency wavelength transmittance' in first_line.lower() or first_line.startswith('frequency'):
            result = plot_transmittance_spectrum.func(file_path)
            return f"Auto-detected as spectrum file.\n{result}"

        # Check if it's a resonance file
        if 'frequency q factor' in first_line.lower():
            # Resonance file is just a table - can't really plot without more info
            return f"Auto-detected as resonance file. Resonance files list modes - visualization not needed. Use read_resonance_file to read the data."

        # Check if it's a field profile
        with open(file_path, 'r') as f:
            for line in f:
                if line.startswith('# Dimensions:'):
                    import re
                    match = re.search(r'# Dimensions:\s*\((.*?)\)', line)
                    if match:
                        # Split by commas, skip any empty strings (for trailing comma case)
                        parts = [x.strip() for x in match.group(1).split(',') if x.strip()]
                        dims = tuple(int(x) for x in parts)
                        if len(dims) == 1:
                            result = plot_field_profile_1d.func(file_path)
                            return f"Auto-detected as 1D field profile.\n{result}"
                        elif len(dims) == 2:
                            result = plot_field_profile_2d.func(file_path)
                            return f"Auto-detected as 2D field profile.\n{result}"
                        else:
                            return f"Detected 3D field profile. 3D visualization not supported - use read_field_profile to read the data."
                    break

        # If we get here, try guessing from filename
        filename = os.path.basename(file_path).lower()
        if 'spectrum' in filename:
            result = plot_transmittance_spectrum(file_path)
            return f"Guessed as spectrum file from filename.\n{result}"
        elif 'field' in filename or 'profile' in filename:
            # Try to read and determine dimensions
            # Just read first few lines to check
            with open(file_path, 'r') as f:
                for line in f:
                    if line.startswith('# Dimensions:'):
                        import re
                        match = re.search(r'# Dimensions:\s*\((.*?)\)', line)
                        if match:
                            dims = tuple(int(x) for x in match.group(1).split(','))
                            if len(dims) == 1:
                                result = plot_field_profile_1d(file_path)
                                return f"Guessed as 1D field profile from filename.\n{result}"
                            elif len(dims) == 2:
                                result = plot_field_profile_2d(file_path)
                                return f"Guessed as 2D field profile from filename.\n{result}"

        return f"Could not automatically detect file type. Please use the specific visualization tool:\n- plot_transmittance_spectrum for spectrum files\n- plot_field_profile_1d for 1D field profiles\n- plot_field_profile_2d for 2D field profiles"

    except Exception as e:
        return f"Error during auto-detection: {str(e)}"
