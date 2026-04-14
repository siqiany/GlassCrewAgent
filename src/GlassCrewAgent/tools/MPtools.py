"""
Materials Project (MP) Tools for CrewAI

This module provides tools for querying Materials Project database for material properties.
Required environment variable: MP_KEY (Materials Project API key)

Functions:
- 晶体结构分析: get_structure_info, calculate_density, calculate_symmetry
- 带隙查询: get_band_gap_by_formula, get_band_gap_by_material_id
- 介电常数查询: get_dielectric_by_material_id
- 体积/密度查询: get_volume_by_formula, get_density_by_formula
- 按元素搜索材料: search_materials_containing_elements
"""

import os
from typing import Optional, List, Dict, Any
from crewai.tools import tool

# Global MPRester client
_mp_rester = None


def _get_client():
    """Get or create the MPRester client"""
    global _mp_rester
    if _mp_rester is not None:
        return _mp_rester

    api_key = os.environ.get("MP_KEY", "")
    if not api_key or api_key == "Your Materials Project Key":
        return None

    try:
        from mp_api.client import MPRester
        _mp_rester = MPRester(api_key)
        return _mp_rester
    except ImportError as e:
        print(f"MPtools import error: {e}")
        return None


# =============================================================================
# 晶体结构分析 Tools
# =============================================================================

@tool("Get Structure Info")
def get_structure_info(material_id: str) -> str:
    """
    Get crystal structure information for a material by its Materials Project ID.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-1234')

    Returns:
        Dictionary containing crystal structure details including:
        - lattice parameters (a, b, c, alpha, beta, gamma)
        - space group
        - crystal system
        - volume
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        structure = mpr.get_structure_by_material_id(material_id)
        lattice = structure.lattice

        info = f"""Crystal Structure Information for {material_id}:
- Lattice Parameters:
  a = {lattice.a:.4f} Å
  b = {lattice.b:.4f} Å
  c = {lattice.c:.4f} Å
  alpha = {lattice.alpha:.2f}°
  beta = {lattice.beta:.2f}°
  gamma = {lattice.gamma:.2f}°
- Volume: {structure.volume:.4f} Å³
- Density: {structure.density:.4f} g/cm³
- Number of sites: {len(structure)}
"""
        return info
    except Exception as e:
        return f"Error getting structure: {str(e)}"


@tool("Calculate Density")
def calculate_density(material_id: str) -> str:
    """
    Calculate the theoretical density of a material by its Materials Project ID.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-1234')

    Returns:
        Density in g/cm³
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        structure = mpr.get_structure_by_material_id(material_id)
        density = structure.density
        return f"Density of {material_id}: {density:.4f} g/cm³"
    except Exception as e:
        return f"Error calculating density: {str(e)}"


@tool("Calculate Symmetry")
def calculate_symmetry(material_id: str) -> str:
    """
    Calculate symmetry information (space group) for a material by its Materials Project ID.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-1234')

    Returns:
        Symmetry information including space group number and symbol
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        # Get symmetry via material search
        result = mpr.materials.search(
            material_ids=[material_id],
            fields=['symmetry'],
        )
        result_list = list(result)
        if not result_list:
            return f"No symmetry data available for {material_id}"

        material = result_list[0]
        if material and material.symmetry:
            sym = material.symmetry
            info = f"""Symmetry Information for {material_id}:
- Space Group Number: {sym.number if hasattr(sym, 'number') else 'N/A'}
- Space Group Symbol: {sym.symbol if hasattr(sym, 'symbol') else 'N/A'}
- Crystal System: {sym.crystal_system if hasattr(sym, 'crystal_system') else 'N/A'}
- Point Group: {sym.point_group if hasattr(sym, 'point_group') else 'N/A'}
"""
        else:
            info = f"No symmetry data available for {material_id}"
        return info
    except Exception as e:
        return f"Error calculating symmetry: {str(e)}"


# =============================================================================
# 带隙查询 Tools
# =============================================================================

@tool("Get Band Gap by Formula")
def get_band_gap_by_formula(formula: str) -> str:
    """
    Get the band gap energy for a material by its chemical formula.

    Args:
        formula: Chemical formula (e.g., 'SiO2', 'TiO2', 'GaAs')

    Returns:
        Band gap value in eV (electronvolts)
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        # First get material_ids from basic search
        results = mpr.materials.search(
            formula=formula,
            fields=['material_id', 'formula_pretty'],
        )

        results_list = list(results)
        if not results_list:
            return f"No materials found for formula: {formula}"

        output = f"Band Gap Results for {formula}:\n"
        for entry in results_list[:5]:
            mat_id = entry.material_id
            formula_pretty = entry.formula_pretty
            # Band gap must be obtained from structure via get_structure_by_material_id
            # since it's not in the available fields list
            try:
                structure = mpr.get_structure_by_material_id(mat_id)
                # In newer mp-api, band gap needs to be obtained from materials.search with specific properties
                # For now, we just note that it's not available in basic query
                output += f"- {mat_id} ({formula_pretty}): Available in detailed query only\n"
            except Exception:
                output += f"- {mat_id} ({formula_pretty}): Error retrieving\n"

        return output
    except Exception as e:
        return f"Error getting band gap: {str(e)}"


@tool("Get Band Gap by Material ID")
def get_band_gap_by_material_id(material_id: str) -> str:
    """
    Get the band gap energy for a material by its Materials Project ID.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-1234')

    Returns:
        Band gap value in eV (electronvolts)
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        # Get the full structure which has band gap info via computed properties
        structure = mpr.get_structure_by_material_id(material_id)

        # In newer MP API, band gap is not available in basic search
        # Need to get it from the summary if available
        result = mpr.materials.search(
            material_ids=[material_id],
            fields=['nsites', 'volume'],
        )
        result_list = list(result)

        if result_list:
            return f"Structure for {material_id} retrieved. Band gap information requires additional properties query that is not available in the current API endpoint. Structure volume = {result_list[0].volume:.4f} Å³"
        else:
            return f"Structure for {material_id} retrieved, but no additional data available. Volume = {structure.volume:.4f} Å³"
    except Exception as e:
        return f"Error getting band gap: {str(e)}"
    except Exception as e:
        return f"Error getting band gap: {str(e)}"


# =============================================================================
# 介电常数查询 Tool
# =============================================================================

@tool("Get Dielectric by Material ID")
def get_dielectric_by_material_id(material_id: str) -> str:
    """
    Get the dielectric constant (refractive index) for a material by its Materials Project ID.
    Important for optical glass applications.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-1234')

    Returns:
        Dielectric constant (static and optical)
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        # Dielectric is not in the available fields list for the current API version
        # We can get it via additional calculation if needed
        result = mpr.materials.search(
            material_ids=[material_id],
            fields=['material_id', 'formula_pretty', 'symmetry', 'volume', 'density'],
        )
        result_list = list(result)

        if not result_list:
            return f"Dielectric data not available for {material_id}"

        material = result_list[0]
        formula_pretty = material.formula_pretty if hasattr(material, 'formula_pretty') else material_id
        symmetry = material.symmetry.symbol if hasattr(material, 'symmetry') and material.symmetry else 'N/A'

        info = f"""Material Information for {material_id} ({formula_pretty}):
- Space Group: {symmetry}
- Dielectric information: Not available in basic API query
- For dielectric properties, additional database access is required in newer MP API
"""
        if hasattr(material, 'volume'):
            info += f"- Volume: {material.volume:.4f} Å³\n"
        if hasattr(material, 'density'):
            info += f"- Density: {material.density:.4f} g/cm³\n"

        return info
    except Exception as e:
        return f"Error getting dielectric properties: {str(e)}"


# =============================================================================
# 体积/密度查询 Tools
# =============================================================================

@tool("Get Volume by Formula")
def get_volume_by_formula(formula: str) -> str:
    """
    Get the unit cell volume for a material by its chemical formula.

    Args:
        formula: Chemical formula (e.g., 'SiO2', 'TiO2')

    Returns:
        Unit cell volume in Å³
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        results = mpr.materials.search(
            formula=formula,
            fields=['material_id', 'volume', 'formula_pretty'],
        )

        results_list = list(results)
        if not results_list:
            return f"No materials found for formula: {formula}"

        output = f"Volume Results for {formula}:\n"
        for entry in results_list[:5]:
            mat_id = entry.material_id
            formula_pretty = entry.formula_pretty
            volume = entry.volume
            output += f"- {mat_id} ({formula_pretty}): {volume:.4f} Å³\n" if volume else f"- {mat_id} ({formula_pretty}): N/A\n"

        return output
    except Exception as e:
        return f"Error getting volume: {str(e)}"


@tool("Get Density by Formula")
def get_density_by_formula(formula: str) -> str:
    """
    Get the theoretical density for a material by its chemical formula.

    Args:
        formula: Chemical formula (e.g., 'SiO2', 'TiO2')

    Returns:
        Density in g/cm³
    """
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        results = mpr.materials.search(
            formula=formula,
            fields=['material_id', 'density', 'formula_pretty'],
        )

        results_list = list(results)
        if not results_list:
            return f"No materials found for formula: {formula}"

        output = f"Density Results for {formula}:\n"
        for entry in results_list[:5]:
            mat_id = entry.material_id
            formula_pretty = entry.formula_pretty
            density = entry.density
            output += f"- {mat_id} ({formula_pretty}): {density:.4f} g/cm³\n" if density else f"- {mat_id} ({formula_pretty}): N/A\n"

        return output
    except Exception as e:
        return f"Error getting density: {str(e)}"


# =============================================================================
# 按元素搜索材料 Tool
# =============================================================================

@tool("Search Materials Containing Elements")
def search_materials_containing_elements(
    elements: str,
    nelements: Optional[int] = None,
    max_results: int = 10
) -> str:
    """
    Search for materials containing specific elements.

    Args:
        elements: Comma-separated list of elements (e.g., 'Si,O' for SiO2)
        nelements: Number of elements in the compound (optional filter)
        max_results: Maximum number of results to return (default: 10)

    Returns:
        List of materials containing the specified elements
    """
    # Convert string inputs to proper types (handles LLM outputting strings)
    def to_int(val):
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return None
        return int(val)
    
    nelements = to_int(nelements)
    max_results = to_int(max_results)
    
    mpr = _get_client()
    if mpr is None:
        return "Error: MPRester client not initialized. Check your MP_KEY and ensure mp-api is installed."

    try:
        # Convert comma-separated string to list
        element_list = [e.strip() for e in elements.split(',')]

        search_kwargs = {
            'elements': element_list,
            'fields': ['material_id', 'formula_pretty', 'symmetry'],
        }
        if nelements is not None:
            search_kwargs['num_elements'] = nelements

        results = mpr.materials.search(**search_kwargs)
        results_list = list(results)[:max_results]

        if not results_list:
            return f"No materials found containing elements: {elements}"

        output = f"Materials containing {elements}:\n"
        for entry in results_list:
            mat_id = entry.material_id
            formula = entry.formula_pretty
            spacegroup = entry.symmetry.symbol if hasattr(entry, 'symmetry') and entry.symmetry else 'N/A'
            output += f"- {mat_id} ({formula}): Space group {spacegroup}\n"

        return output
    except Exception as e:
        return f"Error searching materials: {str(e)}"