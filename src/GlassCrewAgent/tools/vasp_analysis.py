"""
VASP Analysis and Plotting Module
==================================

This module handles all VASP result analysis and visualization, including:
- OUTCAR parsing (energy, forces, band gap, magnetization, etc.)
- Convergence plots (energy, electronic SCF steps, forces/stress)
- Electronic structure plots (DOS, band structure, orbital projections)
- Crystal structure visualization
- HTML report generation

This is the highest-level visualization module in the VASP toolchain.
All plots use matplotlib with proper styling for publication quality.
"""

import os
import re
import json
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from crewai.tools import tool


# =============================================================================
# Matplotlib Utilities (lazy import to avoid installation issues)
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


# =============================================================================
# OUTCAR Parsing
# =============================================================================

def _parse_vasp_output_structured(outcar_path: str) -> dict:
    """
    Internal function: Parse VASP OUTCAR and return structured dictionary.

    Returns:
        Dictionary with keys: final_energy, energy_per_atom, band_gap,
        fermi_level, max_force, avg_force, total_magnetization, n_ionic_steps
    """
    try:
        from pymatgen.io.vasp import Outcar
    except ImportError:
        return {}

    if not os.path.exists(outcar_path):
        return {}

    result = {}
    try:
        outcar = Outcar(outcar_path)

        # Final energy
        if hasattr(outcar, 'final_energy'):
            result['final_energy'] = outcar.final_energy

        # Energy per atom
        if hasattr(outcar, 'final_energy') and hasattr(outcar, 'structure'):
            n_atoms = len(outcar.structure)
            result['energy_per_atom'] = outcar.final_energy / n_atoms
            result['n_atoms'] = n_atoms

        # Band gap
        try:
            bg = None
            if hasattr(outcar, 'bandgap'):
                bg = outcar.bandgap
            elif hasattr(outcar, 'bands') and outcar.bands is not None:
                bg = outcar.bands.get_gap()
            if bg is not None:
                result['band_gap'] = bg
                result['is_metal'] = bg <= 0
        except Exception:
            pass

        # Fermi level
        if hasattr(outcar, 'efermi'):
            result['fermi_level'] = outcar.efermi

        # Forces
        try:
            forces = None
            if hasattr(outcar, 'forces'):
                forces = outcar.forces
            elif hasattr(outcar, 'ionic_steps') and outcar.ionic_steps:
                last_step = outcar.ionic_steps[-1]
                forces = last_step.get('forces', None)
            if forces is not None and len(forces) > 0:
                force_norms = np.linalg.norm(forces, axis=1)
                result['max_force'] = np.max(force_norms)
                result['avg_force'] = np.mean(force_norms)
        except Exception:
            pass

        # Magnetic moments
        try:
            if hasattr(outcar, 'magnetization'):
                mag = outcar.magnetization
                if mag is not None and len(mag) > 0:
                    result['total_magnetization'] = sum(m[0] for m in mag)
        except Exception:
            pass

        # Ionic steps
        try:
            n_steps = None
            if hasattr(outcar, 'nionic_steps'):
                n_steps = outcar.nionic_steps
            elif hasattr(outcar, 'ionic_steps'):
                n_steps = len(outcar.ionic_steps)
            if n_steps is not None:
                result['n_ionic_steps'] = n_steps
        except Exception:
            pass

    except Exception:
        pass

    return result


@tool("Parse VASP Output")
def parse_vasp_output(outcar_path: str) -> str:
    """
    Parse VASP OUTCAR file and extract key results.

    Args:
        outcar_path: Path to OUTCAR file

    Returns:
        Human-readable summary AND structured JSON data with numerical values
        (energy, band gap, forces, Fermi level, etc.)
    """
    try:
        from pymatgen.io.vasp import Outcar
    except ImportError as e:
        return f"Error: Required package not installed. Details: {str(e)}"

    if not os.path.exists(outcar_path):
        return f"Error: OUTCAR file not found: {outcar_path}"

    try:
        # Get structured data first
        data = _parse_vasp_output_structured(outcar_path)

        # Build human-readable summary
        summary = "VASP OUTCAR Parsing Results:\n\n"
        summary += "--- Structured Data (JSON) ---\n"
        summary += json.dumps(data, indent=2, default=str) + "\n\n"
        summary += "--- Human Readable Summary ---\n\n"

        # Final energy
        if 'final_energy' in data:
            summary += f"Final energy: {data['final_energy']:.6f} eV\n"

        # Energy per atom
        if 'energy_per_atom' in data:
            summary += f"Final energy per atom: {data['energy_per_atom']:.6f} eV/atom\n"

        # Band gap
        if 'band_gap' in data:
            summary += f"Band gap: {data['band_gap']:.4f} eV\n"
            if data['band_gap'] > 0:
                summary += "  → Semiconductor/insulator\n"
            else:
                summary += "  → Metal\n"

        # Fermi level
        if 'fermi_level' in data:
            summary += f"Fermi level: {data['fermi_level']:.4f} eV\n"

        # Maximum force on atoms
        if 'max_force' in data:
            summary += f"Maximum force: {data['max_force']:.6f} eV/Å\n"
            summary += f"Average force: {data['avg_force']:.6f} eV/Å\n"

        # Magnetic moments
        if 'total_magnetization' in data:
            summary += f"Total magnetization: {data['total_magnetization']:.4f} μB\n"

        # Number of ionic steps
        if 'n_ionic_steps' in data:
            summary += f"Number of ionic steps: {data['n_ionic_steps']}\n"

        return summary
    except Exception as e:
        return f"Error parsing OUTCAR: {str(e)}"


# =============================================================================
# Convergence Plots
# =============================================================================

@tool("Plot Energy Convergence from OSZICAR")
def plot_energy_convergence(
    oszicar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot electronic step energy convergence from VASP OSZICAR file.
    Creates a PNG image showing energy versus ionic step iteration.

    Args:
        oszicar_path: Path to the OSZICAR file from VASP output
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(oszicar_path):
        return f"Error: OSZICAR file not found at {oszicar_path}"

    try:
        from pymatgen.io.vasp import Oszicar
    except ImportError:
        return "Error: pymatgen not installed"

    try:
        oszicar = Oszicar(oszicar_path)

        # Extract energy data from each ionic step
        energies = []
        for step in oszicar.ionic_steps:
            # pymatgen stores the final energy in 'E0' key
            energies.append(step["E0"])

        iterations = list(range(1, len(energies) + 1))

        # Determine output path
        if not output_png_path:
            base, _ = os.path.splitext(oszicar_path)
            output_png_path = f"{base}_energy_convergence.png"

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Create the plot
        fig, ax = plt.subplots(figsize=(10, 6))

        ax.plot(iterations, energies, 'b-o', linewidth=2, markersize=6)
        ax.set_xlabel('Ionic Step')
        ax.set_ylabel('Total Energy (eV)')
        ax.set_title('VASP Energy Convergence')
        ax.grid(True, alpha=0.3)

        # Set x-ticks to integer steps
        ax.set_xticks(iterations)

        # Add final energy annotation
        if len(energies) > 0:
            final_e = energies[-1]
            ax.text(0.02, 0.98, f'Final Energy: {final_e:.6f} eV',
                    transform=ax.transAxes, va='top',
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created energy convergence plot:\n- Input: {oszicar_path}\n- Output PNG: {output_png_path}\n- Ionic steps: {len(energies)}"

    except Exception as e:
        return f"Error creating energy convergence plot: {str(e)}"


@tool("Plot Electronic Steps Convergence")
def plot_electronic_convergence(
    oszicar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot detailed electronic SCF step convergence for EACH ionic step.
    Shows how the energy converges during each self-consistent field cycle.
    Much more detailed than just final energy per ionic step.

    Args:
        oszicar_path: Path to OSZICAR file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(oszicar_path):
        return f"Error: OSZICAR file not found at {oszicar_path}"

    try:
        from pymatgen.io.vasp import Oszicar
    except ImportError:
        return "Error: pymatgen not installed"

    try:
        oszicar = Oszicar(oszicar_path)

        if not output_png_path:
            base, _ = os.path.splitext(oszicar_path)
            output_png_path = f"{base}_electronic_convergence.png"
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Collect all electronic step energies
        all_energies = []
        step_markers = [0]  # Mark where ionic steps change
        current_pos = 0

        for ionic_step in oszicar.ionic_steps:
            if 'electronic_steps' in ionic_step and ionic_step['electronic_steps']:
                for e_step in ionic_step['electronic_steps']:
                    all_energies.append(e_step['E'])
                    current_pos += 1
                step_markers.append(current_pos)

        if len(all_energies) == 0:
            return "No electronic step data found in OSZICAR"

        # Create plot
        fig, ax = plt.subplots(figsize=(14, 7))
        ax.plot(range(len(all_energies)), all_energies, 'b-', linewidth=1.5, alpha=0.8)

        # Mark ionic step boundaries
        for marker in step_markers[1:-1]:
            ax.axvline(x=marker, color='r', linestyle='--', alpha=0.3)

        ax.set_xlabel('Electronic SCF Step (all ionic steps combined)')
        ax.set_ylabel('Energy (eV)')
        ax.set_title('Full Electronic SCF Convergence - All Ionic Steps')
        ax.grid(True, alpha=0.3)

        # Add ionic step markers
        ax.axvline(x=0, color='r', linestyle='--', alpha=0.3, label='Ionic step boundary')
        ax.legend()

        # Add energy change info
        delta_e = abs(all_energies[-1] - all_energies[0])
        ax.text(0.02, 0.98, f'Total energy change: {delta_e:.4f} eV\nFinal energy: {all_energies[-1]:.6f} eV\nIonic steps: {len(step_markers)-1}',
                transform=ax.transAxes, va='top', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created electronic convergence plot:\n- Output PNG: {output_png_path}\n- Total electronic steps: {len(all_energies)}\n- Ionic steps: {len(step_markers)-1}"

    except Exception as e:
        return f"Error creating electronic convergence plot: {str(e)}"


@tool("Plot Force and Stress Convergence")
def plot_force_stress_convergence(
    outcar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot maximum force and stress convergence during ionic relaxation.
    Shows how forces decrease as the structure relaxes to equilibrium.

    Args:
        outcar_path: Path to OUTCAR file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(outcar_path):
        return f"Error: OUTCAR file not found at {outcar_path}"

    try:
        from pymatgen.io.vasp import Outcar
    except ImportError:
        return "Error: pymatgen not installed"

    try:
        outcar = Outcar(outcar_path)

        if not output_png_path:
            base_dir = os.path.dirname(outcar_path)
            output_png_path = os.path.join(base_dir, "force_stress_convergence.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Extract forces from each ionic step
        max_forces = []
        avg_forces = []
        energies = []

        # Different pymatgen versions store ionic_steps differently
        if hasattr(outcar, 'ionic_steps'):
            ionic_steps = outcar.ionic_steps
        else:
            # Fallback: read forces from OUTCAR directly if attribute not available
            # Try to get from steps attribute or parse manually
            try:
                ionic_steps = outcar.steps
            except:
                # Last resort: use oszicar to get energy data
                from pymatgen.io.vasp import Oszicar
                try:
                    oszicar = Oszicar(outcar_path.replace('OUTCAR', 'OSZICAR'))
                    for step in oszicar.ionic_steps:
                        if 'E0' in step:
                            energies.append(step['E0'])
                    # If we got energy data from OSZICAR, just plot energy
                    if energies:
                        iterations = list(range(1, len(energies) + 1))
                        fig, ax = plt.subplots(figsize=(12, 7))
                        ax.plot(iterations, energies, 'g-o', linewidth=2, markersize=6)
                        ax.set_xlabel('Ionic Step')
                        ax.set_ylabel('Total Energy (eV)')
                        ax.set_title('Energy Convergence During Relaxation')
                        ax.grid(True, alpha=0.3)
                        fig.tight_layout()
                        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
                        plt.close(fig)
                        return f"Successfully created energy convergence plot (force data not available):\n- Output PNG: {output_png_path}\n- Ionic steps: {len(energies)}"
                except:
                    pass
                return "Error: Could not find ionic step data in OUTCAR. The calculation may be static (not a relaxation)."

        for step in ionic_steps:
            if isinstance(step, dict) and 'forces' in step and step['forces'] is not None:
                forces_np = np.array(step['forces'])
                force_norms = np.linalg.norm(forces_np, axis=1)
                max_forces.append(np.max(force_norms))
                avg_forces.append(np.mean(force_norms))
            if isinstance(step, dict) and 'E0' in step:
                energies.append(step['E0'])

        if not max_forces:
            return "No force data found in OUTCAR"

        iterations = list(range(1, len(max_forces) + 1))

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

        # Forces plot
        ax1.plot(iterations, max_forces, 'r-o', linewidth=2, markersize=6, label='Max force')
        ax1.plot(iterations, avg_forces, 'b-s', linewidth=2, markersize=6, label='Avg force')
        ax1.axhline(y=0.01, color='g', linestyle='--', alpha=0.5, label='Typical convergence (0.01 eV/Å)')
        ax1.set_xlabel('Ionic Step')
        ax1.set_ylabel('Force (eV/Å)')
        ax1.set_title('Force Convergence During Relaxation')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.set_yscale('log')

        # Energy plot
        energies = [step['E0'] for step in outcar.ionic_steps if 'E0' in step]
        if len(energies) == len(iterations):
            ax2.plot(iterations, energies, 'g-o', linewidth=2, markersize=6)
            ax2.set_xlabel('Ionic Step')
            ax2.set_ylabel('Total Energy (eV)')
            ax2.set_title('Energy Convergence')
            ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created force/stress convergence plot:\n- Output PNG: {output_png_path}\n- Ionic steps: {len(max_forces)}\n- Final max force: {max_forces[-1]:.6f} eV/Å"

    except Exception as e:
        return f"Error creating force convergence plot: {str(e)}"


# =============================================================================
# Electronic Structure Plots (DOS, Band Structure)
# =============================================================================

@tool("Plot Density of States from VASP Output")
def plot_density_of_states(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot total density of states (DOS) from VASP vasprun.xml file.
    Creates a publication-quality PNG image of the DOS.

    Args:
        vasprun_path: Path to vasprun.xml file from VASP output
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import DosPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly (missing electronic structure module)"

    try:
        vasprun = Vasprun(vasprun_path)
        complete_dos = vasprun.complete_dos

        # Determine output path
        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "density_of_states.png")

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Create plot - FIXED: use simpler API compatible with all pymatgen versions
        plotter = DosPlotter(sigma=0.1)
        plotter.add_dos("Total DOS", complete_dos)
        ax = plotter.get_plot(xlim=(-5, 5))  # Default energy range around Fermi

        # Save figure
        fig = ax.figure
        fig.set_size_inches(10, 6)
        fig.tight_layout()
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created density of states plot:\n- Output PNG: {output_png_path}\n- Fermi energy: {complete_dos.efermi:.4f} eV"

    except Exception as e:
        return f"Error creating density of states plot: {str(e)}"


@tool("Plot Total and Partial Density of States")
def plot_full_dos(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot total density of states AND elemental partial density of states from VASP.
    This is much more informative than just total DOS - shows element contributions.

    Args:
        vasprun_path: Path to vasprun.xml file from VASP output
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import DosPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
        complete_dos = vasprun.complete_dos

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "full_dos_with_elements.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        plotter = DosPlotter(sigma=0.1)
        plotter.add_dos("Total DOS", complete_dos)

        # Add partial DOS by element
        pdos = complete_dos.get_element_dos()
        for element, dos in pdos.items():
            plotter.add_dos(str(element), dos)

        ax = plotter.get_plot(xlim=(-8, 4))
        ax.legend(fontsize=10, loc='upper right')

        fig = ax.figure
        fig.set_size_inches(12, 7)
        fig.tight_layout()
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        elements = [str(e) for e in pdos.keys()]
        return f"Successfully created full PDOS plot:\n- Output PNG: {output_png_path}\n- Elements plotted: {', '.join(elements)}\n- Fermi level: {complete_dos.efermi:.4f} eV"

    except Exception as e:
        return f"Error creating full PDOS plot: {str(e)}"


@tool("Plot Orbital-resolved Partial DOS")
def plot_orbital_pdos(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot orbital-resolved density of states (s, p, d orbitals separated).
    Shows detailed contributions from different atomic orbitals.

    Args:
        vasprun_path: Path to vasprun.xml file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import DosPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
        complete_dos = vasprun.complete_dos

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "orbital_pdos.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        plotter = DosPlotter(sigma=0.05)
        plotter.add_dos("Total DOS", complete_dos)

        # Add orbital-resolved DOS (s, p, d orbitals)
        # get_spd_dos() doesn't take site argument in newer pymatgen
        # Instead, we just plot the overall spd DOS
        spd_dos = complete_dos.get_spd_dos()
        for orbital, dos in spd_dos.items():
            plotter.add_dos(orbital.name, dos)

        ax = plotter.get_plot(xlim=(-8, 4))
        ax.legend(fontsize=9, loc='upper right', ncol=2)

        fig = ax.figure
        fig.set_size_inches(14, 8)
        fig.tight_layout()
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created orbital-resolved PDOS plot:\n- Output PNG: {output_png_path}\n- Fermi level: {complete_dos.efermi:.4f} eV"

    except Exception as e:
        return f"Error creating orbital PDOS plot: {str(e)}"


@tool("Plot Band Structure with Projections")
def plot_band_structure_projected(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot electronic band structure from VASP vasprun.xml file.
    Uses manual plotting approach to avoid pymatgen version compatibility issues.

    Args:
        vasprun_path: Path to vasprun.xml file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        # Read vasprun.xml
        vasprun = Vasprun(vasprun_path)
        efermi = vasprun.efermi

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "band_structure.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Get eigen values - handle both spin-polarized and non-spin-polarized cases
        eigenvalues = vasprun.eigenvalues
        kpoints = vasprun.actual_kpoints

        # Calculate distances between consecutive k-points for the x-axis
        if len(kpoints) < 2:
            return "Error: Not enough k-points for band structure plot"

        lattice = vasprun.final_structure.lattice
        reciprocal_lattice = lattice.reciprocal_lattice

        x = [0]
        for i in range(1, len(kpoints)):
            dk = np.array(kpoints[i]) - np.array(kpoints[i-1])
            dk_cart = reciprocal_lattice.get_cartesian_coords(dk)
            dist = np.linalg.norm(dk_cart)
            x.append(x[-1] + dist)

        # Create plot
        fig, ax = plt.subplots(figsize=(12, 8))

        # Plot bands - handle both spin cases
        if isinstance(eigenvalues, dict):
            # Spin-polarized calculation
            for spin, eig_data in eigenvalues.items():
                if isinstance(eig_data, np.ndarray) and eig_data.ndim == 2:
                    nbands = eig_data.shape[1]
                    for band in range(nbands):
                        energies = eig_data[:, band] - efermi
                        label = f'{spin.name}' if band == 0 else ""
                        ax.plot(x, energies, color='blue' if spin.name == 'Up' else 'red',
                               linewidth=1.2, alpha=0.8, label=label)
        else:
            # Non-spin-polarized
            if isinstance(eigenvalues, np.ndarray) and eigenvalues.ndim == 2:
                nbands = eigenvalues.shape[1]
                for band in range(nbands):
                    energies = eigenvalues[:, band] - efermi
                    ax.plot(x, energies, color='darkblue', linewidth=1.2, alpha=0.8)

        # Add Fermi level line
        ax.axhline(y=0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='Fermi level')

        # Add vertical lines at high symmetry points
        # Find positions where k-point path changes direction (simple heuristic)
        if len(x) > 5:
            dists = np.diff(x)
            jumps = np.where(dists > np.mean(dists) * 1.5)[0]
            for jump in jumps:
                ax.axvline(x=x[jump+1], color='gray', linestyle=':', alpha=0.5)

        ax.set_xlabel('k-point path')
        ax.set_ylabel('Energy (E - E$_F$) [eV]')
        ax.set_title('Electronic Band Structure')
        ax.set_ylim(-8, 4)
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Hide x-tick labels since they don't have physical meaning without labels
        ax.set_xticks([])

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created band structure plot:\n- Output PNG: {output_png_path}\n- Fermi level: {efermi:.4f} eV\n- Number of bands: {nbands if 'nbands' in dir() else 'N/A'}\n- Number of k-points: {len(kpoints)}"

    except Exception as e:
        return f"Error creating band structure plot: {str(e)}"


# Legacy alias for backward compatibility
plot_band_structure = plot_band_structure_projected


@tool("Plot Band Structure + DOS Combined")
def plot_band_dos_combined(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Create a combined plot showing band structure (left) and density of states (right)
    on the same figure with aligned energy axes. This is the standard publication-style
    electronic structure plot.

    Args:
        vasprun_path: Path to vasprun.xml file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import BSDOSPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly (BSDOSPlotter not available)"

    try:
        vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
        bs = vasprun.get_band_structure(kpoints_filename=None, line_mode=True)
        dos = vasprun.complete_dos

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "band_dos_combined.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Parameter name is fig_size (with underscore), not figsize
        plotter = BSDOSPlotter(bs_projection=None, dos_projection=None, vb_energy_range=5, cb_energy_range=5, fig_size=(14, 10))
        fig = plotter.get_plot(bs, dos)
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created combined band structure + DOS plot:\n- Output PNG: {output_png_path}\n- This is publication-quality figure for papers!"

    except Exception as e:
        return f"Error creating band+DOS combined plot: {str(e)}"


# =============================================================================
# Crystal Structure Visualization
# =============================================================================

@tool("Plot Crystal Structure")
def plot_crystal_structure(
    poscar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot 3D crystal structure visualization from POSCAR or CONTCAR file.
    Uses pymatgen's powerful structure plotting capabilities to generate
    publication-quality crystal structure images with bonds and labels.

    Args:
        poscar_path: Path to POSCAR or CONTCAR file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(poscar_path):
        return f"Error: Structure file not found at {poscar_path}"

    try:
        from pymatgen.io.vasp import Poscar
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        poscar = Poscar.from_file(poscar_path)
        structure = poscar.structure

        if not output_png_path:
            base_dir = os.path.dirname(poscar_path)
            output_png_path = os.path.join(base_dir, "crystal_structure.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Use custom 3D plotting
        from mpl_toolkits.mplot3d import Axes3D

        fig = plt.figure(figsize=(12, 10))
        ax = fig.add_subplot(111, projection='3d')

        # Define colors for common elements
        element_colors = {
            'Si': '#d9d9d9', 'C': '#333333', 'O': '#ff0000', 'N': '#3050f8',
            'H': '#ffffff', 'Li': '#cc80ff', 'Na': '#ab5cf2', 'K': '#8f40d4',
            'Ge': '#666666', 'Ga': '#c28f8f', 'As': '#bd80e3', 'P': '#ffa100',
            'Al': '#bfa6a6', 'Mg': '#8aff00', 'Ca': '#3dff00', 'Sr': '#00ff00',
            'Ti': '#bf8f8f', 'Zr': '#e6e6e6', 'Hf': '#4dc2ff', 'V': '#a6a6ab',
            'Nb': '#73c2c9', 'Ta': '#4da6d9', 'Cr': '#8a99c7', 'Mo': '#54b5b5',
            'W': '#4da6a6', 'Mn': '#9c7ac7', 'Fe': '#e06633', 'Co': '#f090a0',
            'Ni': '#50d050', 'Cu': '#c88033', 'Zn': '#7d80b0', 'Ag': '#c0c0c0',
            'Au': '#ffd123', 'Cd': '#ffd98f', 'Hg': '#b8b8d0', 'In': '#a67573',
            'Tl': '#a6544d', 'Sn': '#668080', 'Pb': '#575961', 'Bi': '#9e4fb5',
            'S': '#ffff30', 'Se': '#ffa100', 'Te': '#d47a00', 'F': '#90e050',
            'Cl': '#1ff01f', 'Br': '#a62929', 'I': '#940094'
        }

        # Plot atoms
        coords = structure.cart_coords
        species = [str(s.specie) for s in structure.sites]

        for i, (x_coord, y_coord, z_coord) in enumerate(coords):
            elem = species[i]
            color = element_colors.get(elem, '#808080')
            size = 150 + (structure.sites[i].specie.number * 2)
            ax.scatter(x_coord, y_coord, z_coord, c=color, s=size, alpha=0.8, edgecolors='black', linewidths=1.5)
            ax.text(x_coord, y_coord, z_coord + 0.3, elem, fontsize=10, ha='center', va='bottom')

        # Draw unit cell box
        lattice = structure.lattice
        vertices = [
            [0, 0, 0], [lattice.a, 0, 0], [lattice.a, lattice.b, 0], [0, lattice.b, 0],
            [0, 0, lattice.c], [lattice.a, 0, lattice.c], [lattice.a, lattice.b, lattice.c], [0, lattice.b, lattice.c]
        ]
        vertices = np.dot(vertices, lattice.matrix)

        # Draw edges
        edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4),
                 (0,4), (1,5), (2,6), (3,7)]
        for i, j in edges:
            ax.plot([vertices[i][0], vertices[j][0]],
                   [vertices[i][1], vertices[j][1]],
                   [vertices[i][2], vertices[j][2]],
                   'k-', alpha=0.5, linewidth=2)

        ax.set_xlabel('X (Å)')
        ax.set_ylabel('Y (Å)')
        ax.set_zlabel('Z (Å)')
        ax.set_title(f'Crystal Structure: {structure.composition.reduced_formula}\n{len(structure)} atoms')

        # Add info text
        info_text = f"Formula: {structure.composition.reduced_formula}\n"
        info_text += f"Space group: {structure.get_space_group_info()[0]}\n"
        info_text += f"Volume: {structure.volume:.2f} Å³\n"
        info_text += f"a = {lattice.a:.3f} Å, b = {lattice.b:.3f} Å, c = {lattice.c:.3f} Å"
        ax.text2D(0.02, 0.02, info_text, transform=ax.transAxes,
                 bbox=dict(boxstyle='round', facecolor='white', alpha=0.9), fontsize=10)

        ax.grid(True, alpha=0.2)
        ax.view_init(elev=20, azim=45)

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight', transparent=False)
        plt.close(fig)

        return f"Successfully created crystal structure plot:\n- Output PNG: {output_png_path}\n- Formula: {structure.composition.reduced_formula}\n- {len(structure)} atoms\n- Space group: {structure.get_space_group_info()[0]}"

    except Exception as e:
        return f"Error creating crystal structure plot: {str(e)}"


# =============================================================================
# HTML Report Generation
# =============================================================================

@tool("Generate HTML Report with All Plots")
def generate_html_plot_report(
    vasp_output_dir: str,
    job_id: int
) -> str:
    """
    Generate a beautiful HTML report page displaying all the generated VASP plots.
    Creates an interactive gallery of all plots with descriptions and metadata.

    Args:
        vasp_output_dir: Local directory containing VASP output files
        job_id: Job ID

    Returns:
        Path to the generated HTML report file
    """
    # Need this import here for resolving directory path
    file_path_abs = os.path.abspath(__file__)
    tools_dir = os.path.dirname(file_path_abs)
    glass_agent_dir = os.path.dirname(tools_dir)
    src_dir = os.path.dirname(glass_agent_dir)
    project_root = os.path.dirname(src_dir)
    plots_dir = os.path.join(project_root, "output", "vasp_plots", f"job_{job_id}")

    if not os.path.exists(plots_dir):
        return f"Error: Plots directory not found: {plots_dir}"

    # Find all PNG files
    png_files = sorted([f for f in os.listdir(plots_dir) if f.endswith('.png')])

    if not png_files:
        return "Error: No PNG plot files found in the directory"

    # Parse OUTCAR for metadata
    outcar_path = os.path.join(vasp_output_dir, "OUTCAR")
    formula = "Unknown"
    final_energy = "N/A"

    if os.path.exists(outcar_path):
        try:
            from pymatgen.io.vasp import Outcar
            outcar = Outcar(outcar_path)
            if hasattr(outcar, 'structure') and outcar.structure:
                formula = outcar.structure.composition.reduced_formula
            if hasattr(outcar, 'final_energy'):
                final_energy = f"{outcar.final_energy:.4f} eV"
        except:
            pass

    # Create HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VASP Calculation Report - Job {job_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        .header h1 {{
            color: #333;
            font-size: 28px;
            margin-bottom: 20px;
        }}
        .metadata {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .meta-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }}
        .meta-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .meta-value {{
            font-size: 18px;
            font-weight: 600;
            color: #333;
            margin-top: 5px;
        }}
        .gallery {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 25px;
        }}
        .plot-card {{
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        .plot-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.25);
        }}
        .plot-card h3 {{
            color: #333;
            font-size: 18px;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }}
        .plot-card img {{
            width: 100%;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.3s ease;
        }}
        .plot-card img:hover {{
            transform: scale(1.02);
        }}
        .plot-desc {{
            margin-top: 12px;
            color: #666;
            font-size: 13px;
            line-height: 1.5;
        }}
        #lightbox {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }}
        #lightbox img {{
            max-width: 90%;
            max-height: 90%;
            border-radius: 10px;
        }}
        #lightbox.active {{ display: flex; }}
        #lightbox-close {{
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 40px;
            cursor: pointer;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔬 VASP Calculation Report - Job {job_id}</h1>
            <div class="metadata">
                <div class="meta-item">
                    <div class="meta-label">Material</div>
                    <div class="meta-value">{formula}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Job ID</div>
                    <div class="meta-value">{job_id}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Final Energy</div>
                    <div class="meta-value">{final_energy}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Total Plots</div>
                    <div class="meta-value">{len(png_files)} plots</div>
                </div>
            </div>
        </div>

        <div class="gallery">
"""

    # Plot descriptions
    plot_descriptions = {
        '01_energy_convergence': 'Energy convergence during ionic relaxation. Shows how the total energy decreases and stabilizes.',
        '02_electronic_convergence_detailed': 'Detailed electronic SCF convergence. Shows every self-consistent field step.',
        '03_force_stress_convergence': 'Maximum force on atoms during relaxation. Shows convergence to equilibrium geometry.',
        '04_total_dos': 'Total electronic density of states. Shows the distribution of electron energy levels in the material.',
        '05_elemental_pdos': 'Elemental partial density of states. Shows which elements contribute most to each energy level.',
        '06_orbital_pdos': 'Orbital-resolved partial density of states. Shows s, p, d orbital contributions.',
        '07_band_structure': 'Electronic band structure. Shows energy bands along high-symmetry k-point paths.',
        '08_band_dos_combined': '✭ Publication-quality combined band structure + DOS plot. Standard for scientific papers.',
        'crystal_structure': '3D visualization of the crystal structure showing atom positions and unit cell.',
    }

    for png_file in png_files:
        plot_name = png_file.replace('.png', '')
        title = plot_name.replace('_', ' ').title()
        description = ''
        for key, desc in plot_descriptions.items():
            if key in png_file:
                description = desc
                break

        html_content += f"""
            <div class="plot-card">
                <h3>{title}</h3>
                <img src="{png_file}" onclick="openLightbox('{png_file}')">
                <p class="plot-desc">{description}</p>
            </div>
"""

    html_content += """
        </div>
    </div>

    <div id="lightbox" onclick="closeLightbox()">
        <span id="lightbox-close">&times;</span>
        <img id="lightbox-img" src="" alt="">
    </div>

    <script>
        function openLightbox(src) {
            document.getElementById('lightbox-img').src = src;
            document.getElementById('lightbox').classList.add('active');
        }
        function closeLightbox() {
            document.getElementById('lightbox').classList.remove('active');
        }
    </script>
</body>
</html>
"""

    # Save HTML file
    html_path = os.path.join(plots_dir, "vasp_report.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return f"""✅ Beautiful HTML report generated!

📁 Report location: {html_path}
🖼️ Plots included: {len(png_files)}

You can now open the HTML file in your browser to see all plots in a beautiful interactive gallery!"""


# =============================================================================
# Summary Plot Generator (Master Function)
# =============================================================================

@tool("Generate All VASP Summary Plots")
def plot_vasp_summary_plots(
    vasp_output_dir: str,
    job_id: int
) -> str:
    """
    Generate ALL available summary plots from a completed VASP calculation.
    Creates organized output directory under output/vasp_plots/job_{job_id}/
    and generates ALL plots for which the required input files exist.

    Available plots:
    - Energy convergence (ionic steps)
    - Full electronic SCF convergence (detailed)
    - Force and stress convergence
    - Total density of states
    - Full elemental partial density of states
    - Orbital-resolved PDOS (s, p, d orbitals)
    - Band structure
    - Combined band structure + DOS (publication quality)
    - Crystal structure visualization

    Args:
        vasp_output_dir: Local directory containing VASP output files (OUTCAR, OSZICAR, etc.)
        job_id: Job ID (used for organizing output directory)

    Returns:
        Summary of all plots generated
    """
    # Create output directory
    current_file = os.path.abspath(__file__)
    tools_dir = os.path.dirname(current_file)
    glass_agent_dir = os.path.dirname(tools_dir)
    src_dir = os.path.dirname(glass_agent_dir)
    project_root = os.path.dirname(src_dir)
    output_dir = os.path.join(project_root, "output", "vasp_plots", f"job_{job_id}")
    os.makedirs(output_dir, exist_ok=True)

    summary = f"===== Generating ALL VASP Summary Plots for job {job_id} =====\n"
    summary += f"Output directory: {output_dir}\n\n"

    generated = []
    failed = []

    # 1. Energy convergence from OSZICAR
    oszicar_path = os.path.join(vasp_output_dir, "OSZICAR")
    if os.path.exists(oszicar_path):
        result = plot_energy_convergence.func(oszicar_path, os.path.join(output_dir, "01_energy_convergence.png"))
        if "Successfully" in result:
            generated.append("Energy convergence")
        else:
            failed.append(f"Energy convergence: {result}")
    else:
        failed.append("Energy convergence: OSZICAR not found")

    # 2. Detailed electronic SCF convergence
    if os.path.exists(oszicar_path):
        result = plot_electronic_convergence.func(oszicar_path, os.path.join(output_dir, "02_electronic_convergence_detailed.png"))
        if "Successfully" in result:
            generated.append("Detailed electronic SCF convergence")
        else:
            failed.append(f"Electronic convergence: {result}")

    # 3. Force and stress convergence
    outcar_path = os.path.join(vasp_output_dir, "OUTCAR")
    if os.path.exists(outcar_path):
        result = plot_force_stress_convergence.func(outcar_path, os.path.join(output_dir, "03_force_stress_convergence.png"))
        if "Successfully" in result:
            generated.append("Force & stress convergence")
        else:
            failed.append(f"Force convergence: {result}")

    # 3b. Crystal structure from CONTCAR or POSCAR
    contcar_path = os.path.join(vasp_output_dir, "CONTCAR")
    poscar_path = os.path.join(vasp_output_dir, "POSCAR")
    structure_path = contcar_path if os.path.exists(contcar_path) else poscar_path
    if os.path.exists(structure_path):
        result = plot_crystal_structure.func(structure_path, os.path.join(output_dir, "00_crystal_structure.png"))
        if "Successfully" in result:
            generated.append("Crystal structure (3D visualization)")
        else:
            failed.append(f"Crystal structure: {result}")

    # 4. Check vasprun.xml for electronic structure plots
    vasprun_path = os.path.join(vasp_output_dir, "vasprun.xml")
    if os.path.exists(vasprun_path):
        # 4a. Total DOS
        result = plot_density_of_states.func(vasprun_path, os.path.join(output_dir, "04_total_dos.png"))
        if "Successfully" in result:
            generated.append("Total density of states")
        else:
            failed.append(f"Total DOS: {result}")

        # 4b. Full elemental PDOS
        result = plot_full_dos.func(vasprun_path, os.path.join(output_dir, "05_elemental_pdos.png"))
        if "Successfully" in result:
            generated.append("Elemental partial DOS")
        else:
            failed.append(f"Elemental PDOS: {result}")

        # 4c. Orbital PDOS
        result = plot_orbital_pdos.func(vasprun_path, os.path.join(output_dir, "06_orbital_pdos.png"))
        if "Successfully" in result:
            generated.append("Orbital-resolved PDOS")
        else:
            failed.append(f"Orbital PDOS: {result}")

        # 4d. Band structure
        result = plot_band_structure_projected.func(vasprun_path, os.path.join(output_dir, "07_band_structure.png"))
        if "Successfully" in result:
            generated.append("Band structure")
        else:
            failed.append(f"Band structure: {result}")

        # 4e. Combined band + DOS (publication quality!)
        result = plot_band_dos_combined.func(vasprun_path, os.path.join(output_dir, "08_band_dos_combined.png"))
        if "Successfully" in result:
            generated.append("✭ Band + DOS combined (publication-quality!)")
        else:
            failed.append(f"Combined band+DOS: {result}")
    else:
        failed.append("Electronic structure plots: vasprun.xml not found")

    # Final summary
    summary += f"✅ SUCCESSFULLY GENERATED ({len(generated)} plots):\n"
    for i, plot in enumerate(generated, 1):
        summary += f"  {i}. {plot}\n"

    if failed:
        summary += f"\n⚠️ Not generated/missing ({len(failed)}):\n"
        for msg in failed:
            summary += f"  - {msg}\n"

    # Generate HTML report
    html_result = generate_html_plot_report.func(vasp_output_dir, job_id)
    summary += f"\n================================================================\n"
    summary += f"📁 All high-quality plots saved to: {output_dir}/\n"
    summary += f"🎨 Total plots generated: {len(generated)}\n\n"
    summary += html_result
    return summary


# =============================================================================
# Module Exports
# =============================================================================

# List of all tools and functions to export
__all__ = [
    # Parsing
    'parse_vasp_output',
    '_parse_vasp_output_structured',  # Structured data access

    # Convergence plots
    'plot_energy_convergence',
    'plot_electronic_convergence',
    'plot_force_stress_convergence',

    # Electronic structure plots
    'plot_density_of_states',
    'plot_full_dos',
    'plot_orbital_pdos',
    'plot_band_structure_projected',
    'plot_band_structure',  # Legacy alias
    'plot_band_dos_combined',

    # Structure visualization
    'plot_crystal_structure',

    # Report generation
    'generate_html_plot_report',
    'plot_vasp_summary_plots',

    # Internal utility
    '_get_matplotlib',
]
