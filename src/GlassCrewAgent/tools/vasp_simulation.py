"""
VASP Simulation Setup Module
=============================

This module handles VASP simulation setup and orchestration, including:
- Crystal structure retrieval (from Materials Project)
- Structure file I/O (POSCAR reading)
- VASP input file generation (INCAR, POSCAR, KPOINTS, POTCAR)
- Slurm job script generation
- Complete end-to-end calculation workflow

This is the mid-level orchestration module in the VASP toolchain.
It depends on:
- vasp_platform: for job submission and result download
- vasp_analysis: for result parsing and plotting
"""

import os
import re
import time
import numpy as np
from typing import Optional
from datetime import datetime
from crewai.tools import tool


def _call_tool(tool_func, *args, **kwargs):
    """Helper to call the underlying function of a CrewAI @tool decorated function."""
    if hasattr(tool_func, 'func'):
        return tool_func.func(*args, **kwargs)
    try:
        return tool_func(*args, **kwargs)
    except TypeError:
        # Fallback: try different access patterns for CrewAI
        for attr in ['__wrapped__', '_func', 'original_func']:
            if hasattr(tool_func, attr):
                return getattr(tool_func, attr)(*args, **kwargs)
        raise


# =============================================================================
# Structure Handling (Materials Project Integration)
# =============================================================================

@tool("Get Structure from Materials Project")
def get_structure_from_mp_by_id(material_id: str) -> str:
    """
    Retrieve crystal structure from Materials Project by material ID.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-149' for Si)

    Returns:
        Structure information and saves to local for VASP input generation
    """
    try:
        from mp_api.client import MPRester
    except ImportError:
        return "Error: Required packages not installed: mp-api and pymatgen"

    api_key = os.environ.get("MP_KEY", "")
    if not api_key:
        return "Error: MP_KEY not set in environment"

    try:
        with MPRester(api_key) as mpr:
            structure = mpr.get_structure_by_material_id(material_id)

            lattice = structure.lattice
            info = "Successfully retrieved structure for " + material_id + ":\n\n"
            info += "Formula: " + structure.composition.reduced_formula + "\n"
            info += "Number of sites: " + str(len(structure)) + "\n"
            info += "Lattice parameters:\n"
            info += "  a = " + f"{lattice.a:.4f}" + " Å\n"
            info += "  b = " + f"{lattice.b:.4f}" + " Å\n"
            info += "  c = " + f"{lattice.c:.4f}" + " Å\n"
            info += "  alpha = " + f"{lattice.alpha:.2f}" + "°\n"
            info += "  beta = " + f"{lattice.beta:.2f}" + "°\n"
            info += "  gamma = " + f"{lattice.gamma:.2f}" + "°\n"
            info += "Volume: " + f"{structure.volume:.4f}" + " Å³\n"
            info += "Density: " + f"{structure.density:.4f}" + " g/cm³\n"

            # Import here to avoid circular import
            from src.GlassCrewAgent.tools.vasp_platform import _get_local_job_dir
            job_dir = _get_local_job_dir()
            structure_file = os.path.join(job_dir, material_id + "_structure.json")
            structure.to_file(structure_file, fmt="json")

            info += "\nStructure saved to: " + structure_file

            return info
    except Exception as e:
        return "Error retrieving structure from Materials Project: " + str(e)


@tool("Read POSCAR from Local File")
def read_poscar_from_file(file_path: str) -> str:
    """
    Read a POSCAR file from local disk and parse it using pymatgen.

    Args:
        file_path: Full path to the POSCAR file

    Returns:
        Structure information parsed from POSCAR
    """
    try:
        from pymatgen.io.vasp import Poscar
    except ImportError:
        return "Error: pymatgen not installed"

    if not os.path.exists(file_path):
        return "Error: File not found: " + file_path

    try:
        poscar = Poscar.from_file(file_path)
        structure = poscar.structure

        lattice = structure.lattice
        info = "Successfully read POSCAR:\n\n"
        info += "Formula: " + structure.composition.reduced_formula + "\n"
        info += "Number of sites: " + str(len(structure)) + "\n"
        info += "Lattice parameters:\n"
        info += "  a = " + f"{lattice.a:.4f}" + " Å\n"
        info += "  b = " + f"{lattice.b:.4f}" + " Å\n"
        info += "  c = " + f"{lattice.c:.4f}" + " Å\n"
        info += "Volume: " + f"{structure.volume:.4f}" + " Å³\n"

        return info
    except Exception as e:
        return "Error reading POSCAR: " + str(e)


# =============================================================================
# VASP Input File Generation
# =============================================================================

@tool("Generate VASP Input from Structure")
def generate_vasp_input_from_structure(
    structure_file_path: str,
    calculation_type: str = "structure_relaxation",
    kpoints_density: float = 0.5
) -> str:
    """
    Generate complete set of VASP input files (INCAR, POSCAR, KPOINTS, POTCAR) from a pymatgen structure file.

    Args:
        structure_file_path: Path to the structure file (JSON format from get_structure_from_mp_by_id)
        calculation_type: Type of calculation - available options:
            - "structure_relaxation": Full atomic and cell relaxation (ISIF=3)
            - "static": Static self-consistent calculation (for DOS/band properties)
            - "band": Band structure calculation
            - "dos": Density of states calculation
        kpoints_density: k-point density in 1/Å (default 0.5, lower for larger cells)

    Returns:
        Summary of generated input files
    """
    try:
        from pymatgen.core.structure import Structure
        from pymatgen.io.vasp.sets import MPRelaxSet, MPStaticSet, MPNonSCFSet
    except ImportError as e:
        return f"Error: pymatgen not installed. Details: {str(e)}"

    # Check if POTCAR directory is configured
    psp_dir = os.environ.get("PMG_VASP_PSP_DIR")
    if not psp_dir:
        return "Error: PMG_VASP_PSP_DIR environment variable not set. Please set it to your POTCAR (VASP pseudopotential) directory."

    if not os.path.exists(psp_dir):
        return f"Error: POTCAR directory not found at {psp_dir}. Please check your PMG_VASP_PSP_DIR configuration."

    if not os.path.exists(structure_file_path):
        return "Error: Structure file not found: " + structure_file_path

    job_dir = os.path.dirname(structure_file_path)
    input_dir = os.path.join(job_dir, "input")
    os.makedirs(input_dir, exist_ok=True)

    try:
        structure = Structure.from_file(structure_file_path)

        # Create kpoints object manually for maximum pymatgen compatibility
        # This avoids issues with different parameter names across pymatgen versions
        from pymatgen.io.vasp import Kpoints
        kpoints = Kpoints.automatic_density(structure, kpoints_density)

        # Our POTCAR directory has elements directly in the root (no extra POT_GGA_PAW_PBE layer)
        # user_potcar_functional=None disables the extra directory layer
        # Use user_kpoints_settings (correct parameter name in modern pymatgen)
        if calculation_type == "structure_relaxation":
            vis = MPRelaxSet(structure, user_kpoints_settings=kpoints, user_potcar_functional=None)
        elif calculation_type == "static":
            vis = MPStaticSet(structure, user_kpoints_settings=kpoints, user_potcar_functional=None)
        elif calculation_type in ["dos", "band"]:
            vis = MPNonSCFSet(structure, user_kpoints_settings=kpoints, user_potcar_functional=None)
        else:
            return "Error: Unknown calculation type: " + calculation_type + ". Available: structure_relaxation, static, dos, band"

        vis.write_input(input_dir)

        files = os.listdir(input_dir)
        summary = "Successfully generated VASP input files for " + calculation_type + ":\n\n"
        summary += "System: " + structure.composition.reduced_formula + "\n"
        summary += "Number of atoms: " + str(len(structure)) + "\n"
        summary += "k-point density: " + str(kpoints_density) + " 1/Å\n"
        summary += "\nGenerated files:\n"
        for f in files:
            f_path = os.path.join(input_dir, f)
            size = os.path.getsize(f_path)
            summary += "  - " + f + " (" + str(size) + " bytes)\n"
        summary += "\nDirectory: " + input_dir + "\n"

        return summary
    except Exception as e:
        return "Error generating VASP input: " + str(e)


@tool("Generate SLURM Script")
def generate_slurm_script(
    input_dir: str,
    partition: str,
    nodes: int = 1,
    tasks_per_node: int = 32,
    job_name: Optional[str] = None,
    wall_time: str = "24:00:00",
    api_mode: Optional[bool] = None
) -> str:
    """
    Generate SLURM submission script for VASP calculation.

    Args:
        input_dir: Local input directory containing VASP input files
        partition: Partition (queue) name to use (use list_available_partitions to get options)
        nodes: Number of nodes to request (default 1)
        tasks_per_node: Number of MPI tasks per node (default 32 for typical compute node)
        job_name: Optional job name (defaults to vasp_calculation)
        wall_time: Wall time limit (default 24:00:00)
        api_mode: If None, auto-detect from VASP_CONNECTION_MODE env var.
                  If True, generate pure command fragment for API submission
                  (no #!/bin/bash, no #SBATCH - platform template handles those).
                  If False, generate full SLURM script for SSH sbatch.

    Returns:
        Path to generated script file
    """
    # Auto-detect api_mode from environment if not explicitly set
    if api_mode is None:
        api_mode = os.environ.get("VASP_CONNECTION_MODE", "ssh") == "api"

    vasp_module = os.environ.get("VASP_MODULE_NAME", "vasp-5.4.4-ioptcell_intelmpi2017_hdf5_libxc")

    if not job_name:
        job_name = "vasp_calculation"

    # Get VASP installation path from environment variable
    # Example: VASP_INSTALL_PATH=/public/home/scniv4a4go/apprepo/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc
    vasp_path = os.environ.get("VASP_INSTALL_PATH", "")

    # If not set, try to construct from module name (fallback)
    if not vasp_path:
        vasp_dir = vasp_module.split(' ', 1)[-1] if ' ' in vasp_module else vasp_module
        if vasp_dir.startswith('vasp-'):
            vasp_dir = vasp_dir[5:]
        username = os.environ.get("SUPERCOMPUTING_USERNAME", "") or os.environ.get("SCNET_API_USER", "")
        vasp_path = f"/public/home/{username}/apprepo/vasp/{vasp_dir}"

    # ---- common command block used by both modes ----
    common_commands = f"""echo "=== Job started at $(date) ==="
echo "Job ID: $SLURM_JOB_ID"
echo "Working directory: $(pwd)"

module purge
module load {vasp_module}
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to load VASP module"
    exit 1
fi

source {vasp_path}/scripts/env.sh

# Check input files
for f in INCAR POSCAR POTCAR KPOINTS; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing input file: $f"
        exit 1
    fi
done

# Set environment
export MKL_DEBUG_CPU_TYPE=5
export MKL_CBWR=AVX2
export I_MPI_PIN_DOMAIN=numa
ulimit -l unlimited
ulimit -s unlimited

echo "=== Running VASP with srun ==="
srun --mpi=pmi2 vasp_std
exit_code=$?

echo "VASP finished with exit code: $exit_code"
echo "=== Job completed at $(date) ==="
exit $exit_code
"""

    if api_mode:
        # API mode: pure command fragment only.
        # Platform embeds this between # MARK_CMD / # MARK_BASH in its BASE template.
        # Job parameters (queue, nodes, cores, wall_time) come from API JSON payload.
        slurm_content = common_commands
    else:
        # SSH mode: full SLURM script with shebang and #SBATCH directives.
        slurm_content = f"""#!/bin/bash
#SBATCH -J {job_name}
#SBATCH -p {partition}
#SBATCH -N {nodes}
#SBATCH --ntasks-per-node={tasks_per_node}
#SBATCH --time={wall_time}
#SBATCH -o vasp_job_%j.out
#SBATCH -e vasp_job_%j.err

{common_commands}"""

    script_path = os.path.join(input_dir, "vasp.slurm")
    with open(script_path, 'w') as f:
        f.write(slurm_content)

    mode_label = "API mode (pure commands, no SBATCH)" if api_mode else "SSH mode (full SLURM script)"
    summary = "Successfully generated SLURM script:\n\n"
    summary += "Mode: " + mode_label + "\n"
    summary += "Path: " + script_path + "\n"
    summary += "Job name: " + job_name + "\n"
    summary += "Partition: " + partition + "\n"
    summary += "Nodes: " + str(nodes) + "\n"
    summary += "Total tasks: " + str(nodes * tasks_per_node) + "\n"
    summary += "Wall time: " + wall_time + "\n"
    summary += "VASP module: " + vasp_module + "\n"

    return summary


# =============================================================================
# End-to-end Complete Calculation Workflow
# =============================================================================

@tool("Complete VASP Calculation from MP ID")
def run_complete_vasp_calculation_from_mp(
    material_id: str,
    partition: str,
    calculation_type: str = "structure_relaxation",
    kpoints_density: float = 0.5,
    nodes: int = 1,
    tasks_per_node: int = 32,
    poll_interval: int = 60
) -> str:
    """
    End-to-end complete VASP calculation starting from Materials Project ID.
    This automates the entire workflow: get structure → generate input → submit → wait → download → parse.

    Args:
        material_id: Materials Project ID (e.g., 'mp-149')
        partition: Partition (queue) name to use
        calculation_type: Type of calculation (structure_relaxation, static, dos, band)
        kpoints_density: k-point density in 1/Å
        nodes: Number of nodes
        tasks_per_node: Tasks per node
        poll_interval: Seconds between status checks (default 60)

    Returns:
        Complete calculation summary with parsed results
    """
    start_time = datetime.now()

    # Step 1: Get structure from MP
    step1_result = _call_tool(get_structure_from_mp_by_id, material_id)
    if "Error" in step1_result:
        return step1_result

    # Extract structure file path from result
    import re
    match = re.search(r'Structure saved to: (.+)$', step1_result, re.MULTILINE)
    if not match:
        return f"Could not find structure file path in result:\n{step1_result}"
    structure_file = match.group(1)
    job_dir = os.path.dirname(structure_file)

    # Step 2: Generate VASP input
    step2_result = _call_tool(
        generate_vasp_input_from_structure,
        structure_file_path=structure_file,
        calculation_type=calculation_type,
        kpoints_density=kpoints_density
    )
    if "Error" in step2_result:
        return step2_result

    # Extract input directory
    match = re.search(r'Directory: (.+)$', step2_result, re.MULTILINE)
    if not match:
        return f"Could not find input directory in result:\n{step2_result}"
    input_dir = match.group(1)

    # Step 3: Generate SLURM script
    job_name = f"vasp_{material_id}"
    step3_result = _call_tool(
        generate_slurm_script,
        input_dir=input_dir,
        partition=partition,
        nodes=nodes,
        tasks_per_node=tasks_per_node,
        job_name=job_name,
        wall_time="24:00:00"
    )
    if "Error" in step3_result:
        return step3_result

    # Import platform tools for job submission and status checking
    from src.GlassCrewAgent.tools.vasp_platform import (
        submit_vasp_job,
        check_job_status,
        download_vasp_results
    )

    # Step 4: Submit job
    step4_result = _call_tool(submit_vasp_job, input_dir)
    if "error" in step4_result.lower():
        return step4_result

    # Extract job ID and remote directory using robust patterns
    match_id = re.search(r'Job ID: (\d+)', step4_result)
    if not match_id:
        return f"Could not find job ID in result:\n{step4_result}"
    job_id = int(match_id.group(1))

    # Use a more robust regex that handles different line endings
    match_dir = re.search(r'Remote directory:\s*(.+?)(?:\n|$)', step4_result)
    if match_dir:
        remote_job_dir = match_dir.group(1).strip()
    else:
        # Fallback to default if not found
        remote_job_dir = os.environ.get("VASP_REMOTE_DIR", "~/apprepo/vasp/6.4.2-intelmpi2017_ioptcell/case")

    # Step 5: Wait for completion
    summary = f"===== VASP Calculation Started =====\n\n"
    summary += f"Material ID: {material_id}\n"
    summary += f"Job ID: {job_id}\n"
    summary += f"Calculation type: {calculation_type}\n"
    summary += f"Partition: {partition}\n"
    summary += f"Nodes: {nodes}, Total tasks: {nodes * tasks_per_node}\n"
    summary += f"Remote directory: {remote_job_dir}\n"
    summary += f"\nWaiting for job completion...\n"

    # Polling loop
    while True:
        status_result = _call_tool(check_job_status, job_id)
        if "Error" in status_result:
            summary += f"\n{status_result}\n"
            break

        if "COMPLETED" in status_result:
            summary += f"✓ Job completed\n"
            break
        elif "FAILED" in status_result or "CANCELLED" in status_result:
            summary += f"✗ Job {status_result}\n"
            return summary + "\nJob did not complete successfully."
        else:
            # Still running/pending
            status_line = status_result.split('\n')[0]
            summary += f"  {status_line} - checking again in {poll_interval}s...\n"
            time.sleep(poll_interval)

    # Step 6: Download results
    step6_result = _call_tool(download_vasp_results, job_id, job_dir, remote_job_dir)
    if "Error" in step6_result:
        return summary + "\n" + step6_result

    # Import analysis tools for result parsing
    from src.GlassCrewAgent.tools.vasp_analysis import parse_vasp_output

    # Step 7: Parse results if OUTCAR exists
    output_dir = os.path.join(job_dir, "output")
    outcar_path = os.path.join(output_dir, "OUTCAR")
    parsed_results = ""
    if os.path.exists(outcar_path):
        parsed_results = _call_tool(parse_vasp_output, outcar_path)

    # Complete summary
    end_time = datetime.now()
    duration = end_time - start_time
    duration_min = duration.total_seconds() / 60

    final_summary = f"===== VASP Calculation Complete =====\n\n"
    final_summary += f"Material ID: {material_id}\n"
    final_summary += f"Job ID: {job_id}\n"
    final_summary += f"Calculation type: {calculation_type}\n"
    final_summary += f"Total duration: {duration_min:.1f} minutes\n"
    final_summary += f"Local working directory: {job_dir}\n"
    final_summary += f"\n--- Intermediate Steps ---\n"
    final_summary += step1_result + "\n"
    final_summary += step2_result + "\n"
    final_summary += step3_result + "\n"
    final_summary += step4_result + "\n"
    final_summary += step6_result + "\n"

    if parsed_results:
        final_summary += "\n--- Parsed Results ---\n"
        final_summary += parsed_results

    return final_summary


# =============================================================================
# Module Exports
# =============================================================================

# List of all tools and functions to export
__all__ = [
    # Structure handling
    'get_structure_from_mp_by_id',
    'read_poscar_from_file',

    # Input generation
    'generate_vasp_input_from_structure',
    'generate_slurm_script',

    # End-to-end workflow
    'run_complete_vasp_calculation_from_mp',
    'run_band_gap_calculation_from_mp',
]


# =============================================================================
# Band Gap Calculation (3-step workflow)
# =============================================================================

@tool("Run VASP Band Gap Calculation")
def run_band_gap_calculation_from_mp(
    material_id: str,
    partition: str = "all_normal",
    nodes: int = 1,
    tasks_per_node: int = 32,
    poll_interval: int = 30,
    kpoints_density: float = 0.5
) -> str:
    """
    Run complete 3-step VASP band gap calculation from Materials Project.

    Workflow:
    1. Structure relaxation (geometry optimization)
    2. Static self-consistent calculation (generate CHGCAR and WAVECAR)
    3. Non-selfconsistent band structure calculation (on high-symmetry k-path)

    Args:
        material_id: Materials Project ID (e.g., "mp-149" for Si)
        partition: SLURM partition name
        nodes: Number of nodes
        tasks_per_node: MPI tasks per node
        poll_interval: Seconds between status checks
        kpoints_density: k-point density for relaxation/static steps

    Returns:
        Complete summary including band gap value
    """
    start_time = datetime.now()

    # =========================================
    # Step 1: Get structure from Materials Project
    # =========================================
    step1_result = _call_tool(get_structure_from_mp_by_id, material_id)
    if "Error" in step1_result:
        return step1_result

    # Extract structure file path
    match = re.search(r'Structure saved to: (.+)$', step1_result, re.MULTILINE)
    if not match:
        return f"Could not find structure file in result:\n{step1_result}"
    structure_file = match.group(1)
    job_dir = os.path.dirname(structure_file)

    summary = f"===== VASP Band Gap Calculation Started =====\n\n"
    summary += f"Material ID: {material_id}\n"
    summary += f"Partition: {partition}\n"
    summary += f"Nodes: {nodes}, Total tasks: {nodes * tasks_per_node}\n\n"

    # =========================================
    # Step 2: Structure Relaxation
    # =========================================
    summary += "--- Step 1/3: Structure Relaxation ---\n"

    # Generate relaxation input
    relax_input_dir = os.path.join(job_dir, "relax", "input")
    os.makedirs(relax_input_dir, exist_ok=True)

    try:
        from pymatgen.core.structure import Structure
        from pymatgen.io.vasp.sets import MPRelaxSet
        from pymatgen.io.vasp import Kpoints

        structure = Structure.from_file(structure_file)
        kpoints = Kpoints.automatic_density(structure, kpoints_density)

        vis = MPRelaxSet(
            structure,
            user_kpoints_settings=kpoints,
            user_potcar_functional=None,
            user_incar_settings={
                "LWAVE": True,  # Save wavecar for continuation
                "LCHARG": True,  # Save charge density
            }
        )
        vis.write_input(relax_input_dir)

        summary += f"  Generated relaxation input files\n"
        summary += f"  Directory: {relax_input_dir}\n"
    except Exception as e:
        return summary + f"Error generating relaxation input: {str(e)}"

    # Generate SLURM script and submit
    step2_slurm = _call_tool(generate_slurm_script, relax_input_dir, partition, nodes, tasks_per_node, f"{material_id}_relax", "24:00:00")
    if "Error" in step2_slurm:
        return summary + step2_slurm

    from src.GlassCrewAgent.tools.vasp_platform import submit_vasp_job, check_job_status, download_vasp_results

    step2_submit = _call_tool(submit_vasp_job, relax_input_dir)
    if "error" in step2_submit.lower():
        return summary + step2_submit

    match_id = re.search(r'Job ID: (\d+)', step2_submit)
    job_id_relax = int(match_id.group(1)) if match_id else None
    match_dir = re.search(r'Remote directory:\s*(.+?)(?:\n|$)', step2_submit)
    remote_dir_relax = match_dir.group(1).strip() if match_dir else None

    # Wait for relaxation completion
    summary += f"  Relaxation job submitted (Job ID: {job_id_relax})\n"
    summary += "  Waiting for relaxation to complete...\n"

    while True:
        status = _call_tool(check_job_status, job_id_relax)
        if "COMPLETED" in status:
            summary += "  ✓ Relaxation completed\n"
            break
        elif "FAILED" in status or "CANCELLED" in status:
            return summary + f"  ✗ Relaxation {status}\n"
        time.sleep(poll_interval)

    # Download relaxation results
    _call_tool(download_vasp_results, job_id_relax, os.path.join(job_dir, "relax"), remote_dir_relax)

    # =========================================
    # Step 3: Static SCF Calculation
    # =========================================
    summary += "\n--- Step 2/3: Static SCF Calculation ---\n"

    relaxed_poscar = os.path.join(job_dir, "relax", "output", "CONTCAR")
    if not os.path.exists(relaxed_poscar):
        relaxed_poscar = os.path.join(job_dir, "relax", "output", "POSCAR")  # Fallback

    static_input_dir = os.path.join(job_dir, "static", "input")
    os.makedirs(static_input_dir, exist_ok=True)

    try:
        from pymatgen.io.vasp.sets import MPStaticSet

        relaxed_structure = Structure.from_file(relaxed_poscar)
        kpoints = Kpoints.automatic_density(relaxed_structure, kpoints_density)

        vis = MPStaticSet(
            relaxed_structure,
            user_kpoints_settings=kpoints,
            user_potcar_functional=None,
            user_incar_settings={
                "LWAVE": True,  # Save wavecar for band calculation
                "LCHARG": True,  # Save charge density CHGCAR
                "NSW": 0,  # No ionic steps
                "LORBIT": 11,  # Projected DOS
            }
        )
        vis.write_input(static_input_dir)

        summary += f"  Generated static SCF input files\n"
        summary += f"  Directory: {static_input_dir}\n"
    except Exception as e:
        return summary + f"Error generating static input: {str(e)}"

    # Submit static calculation
    step3_slurm = _call_tool(generate_slurm_script, static_input_dir, partition, nodes, tasks_per_node, f"{material_id}_static", "24:00:00")
    step3_submit = _call_tool(submit_vasp_job, static_input_dir)

    match_id = re.search(r'Job ID: (\d+)', step3_submit)
    job_id_static = int(match_id.group(1)) if match_id else None
    match_dir = re.search(r'Remote directory:\s*(.+?)(?:\n|$)', step3_submit)
    remote_dir_static = match_dir.group(1).strip() if match_dir else None

    summary += f"  Static job submitted (Job ID: {job_id_static})\n"
    summary += "  Waiting for static calculation to complete...\n"

    while True:
        status = _call_tool(check_job_status, job_id_static)
        if "COMPLETED" in status:
            summary += "  ✓ Static SCF completed\n"
            break
        elif "FAILED" in status or "CANCELLED" in status:
            return summary + f"  ✗ Static {status}\n"
        time.sleep(poll_interval)

    _call_tool(download_vasp_results, job_id_static, os.path.join(job_dir, "static"), remote_dir_static)

    # =========================================
    # Step 4: Band Structure Calculation
    # =========================================
    summary += "\n--- Step 3/3: Band Structure Calculation ---\n"

    band_input_dir = os.path.join(job_dir, "band", "input")
    os.makedirs(band_input_dir, exist_ok=True)

    # Copy CHGCAR from static calculation
    chgcar_src = os.path.join(job_dir, "static", "output", "CHGCAR")
    if os.path.exists(chgcar_src):
        import shutil
        shutil.copy(chgcar_src, os.path.join(band_input_dir, "CHGCAR"))
        summary += "  Copied CHGCAR from static calculation\n"

    try:
        from pymatgen.symmetry.bandstructure import HighSymmKpath
        from pymatgen.io.vasp.sets import MPNonSCFSet
        from pymatgen.io.vasp import Kpoints as KpointsCls

        # Get high-symmetry k-path
        kpath = HighSymmKpath(relaxed_structure)

        # Use Line-mode KPOINTS (VASP built-in band structure mode)
        # This avoids issues with explicit k-point format (fixed-width parsing)
        band_kpoints = KpointsCls.automatic_linemode(divisions=20, ibz=kpath)

        # Estimate NBANDS: MPNonSCFSet default is usually 32 for small systems.
        # Use 1.5x the default for band structure to get enough empty bands.
        default_nbands = 32
        nbands_estimate = max(default_nbands, 3 * len(relaxed_structure) * 8 // 2)

        vis = MPNonSCFSet(
            relaxed_structure,
            user_kpoints_settings=band_kpoints,
            user_potcar_functional=None,
            user_incar_settings={
                "ICHARG": 11,  # Read CHGCAR, non-SCF calculation
                "LORBIT": 11,  # Projected bands
                "NBANDS": nbands_estimate,
            }
        )
        vis.write_input(band_input_dir)

        summary += f"  Generated band structure input files\n"
        summary += f"  High-symmetry k-path: {kpath.__class__.__name__}\n"
        summary += f"  Directory: {band_input_dir}\n"
    except Exception as e:
        return summary + f"Error generating band input: {str(e)}"

    # Submit band calculation
    step4_slurm = _call_tool(generate_slurm_script, band_input_dir, partition, nodes, tasks_per_node, f"{material_id}_band", "24:00:00")
    step4_submit = _call_tool(submit_vasp_job, band_input_dir)

    match_id = re.search(r'Job ID: (\d+)', step4_submit)
    job_id_band = int(match_id.group(1)) if match_id else None
    match_dir = re.search(r'Remote directory:\s*(.+?)(?:\n|$)', step4_submit)
    remote_dir_band = match_dir.group(1).strip() if match_dir else None

    summary += f"  Band structure job submitted (Job ID: {job_id_band})\n"
    summary += "  Waiting for band calculation to complete...\n"

    while True:
        status = _call_tool(check_job_status, job_id_band)
        if "COMPLETED" in status:
            summary += "  ✓ Band structure completed\n"
            break
        elif "FAILED" in status or "CANCELLED" in status:
            return summary + f"  ✗ Band {status}\n"
        time.sleep(poll_interval)

    _call_tool(download_vasp_results, job_id_band, os.path.join(job_dir, "band"), remote_dir_band)

    # =========================================
    # Parse band gap from EIGENVAL
    # =========================================
    summary += "\n--- Band Gap Analysis ---\n"

    static_vasprun_path = os.path.join(job_dir, "static", "output", "vasprun.xml")
    eigenval_path = os.path.join(job_dir, "band", "output", "EIGENVAL")
    outcar_path = os.path.join(job_dir, "band", "output", "OUTCAR")

    from src.GlassCrewAgent.tools.vasp_analysis import _parse_vasp_output_structured

    # First parse OUTCAR for energy and Fermi level
    band_data = _parse_vasp_output_structured(outcar_path)

    # Try to get band gap from static SCF vasprun.xml (most reliable)
    band_gap = band_data.get('band_gap')
    if band_gap is None and os.path.exists(static_vasprun_path):
        try:
            from pymatgen.io.vasp import Vasprun
            vr = Vasprun(static_vasprun_path)
            bs = vr.get_band_structure()
            if bs and not bs.is_metal():
                bg_info = bs.get_band_gap()
                band_gap = bg_info.get('energy', 0)
                if band_gap and band_gap > 0:
                    band_data['band_gap'] = float(band_gap)
                    vbm_info = bs.get_vbm()
                    cbm_info = bs.get_cbm()
                    if vbm_info.get('energy') is not None:
                        band_data['vbm'] = float(vbm_info['energy'])
                    if cbm_info.get('energy') is not None:
                        band_data['cbm'] = float(cbm_info['energy'])
                    summary += f"  Band gap from static SCF: {band_gap:.4f} eV\n"
        except Exception as e:
            summary += f"  Note: Static band gap parsing failed: {str(e)[:50]}\n"

    # Fallback: try to get band gap from non-SCF band structure vasprun.xml
    if band_gap is None:
        band_vasprun_path = os.path.join(job_dir, "band", "output", "vasprun.xml")
        if os.path.exists(band_vasprun_path):
            try:
                from pymatgen.io.vasp import Vasprun
                vr = Vasprun(band_vasprun_path)
                bs = vr.get_band_structure()
                if bs and not bs.is_metal():
                    bg_info = bs.get_band_gap()
                    band_gap = bg_info.get('energy', 0)
                    if band_gap and band_gap > 0:
                        band_data['band_gap'] = float(band_gap)
                        vbm_info = bs.get_vbm()
                        cbm_info = bs.get_cbm()
                        if vbm_info.get('energy') is not None:
                            band_data['vbm'] = float(vbm_info['energy'])
                        if cbm_info.get('energy') is not None:
                            band_data['cbm'] = float(cbm_info['energy'])
                        summary += f"  Band gap from band structure: {band_gap:.4f} eV\n"
            except Exception as e:
                summary += f"  Note: Band structure parsing failed: {str(e)[:50]}\n"

    # Final summary
    end_time = datetime.now()
    duration_min = (end_time - start_time).total_seconds() / 60

    summary += f"\n===== Band Gap Calculation Complete =====\n\n"
    summary += f"Total duration: {duration_min:.1f} minutes\n"
    summary += f"Working directory: {job_dir}\n\n"

    if 'band_gap' in band_data:
        bg = band_data['band_gap']
        summary += f"✓ Band gap: {bg:.4f} eV\n"
        if bg > 0.01:
            summary += f"  Material classification: {'Insulator' if bg > 4 else 'Semiconductor'}\n"
        else:
            summary += f"  Material classification: Metal/Semi-metal\n"
    else:
        summary += "⚠ Band gap not available in calculation output\n"

    if 'final_energy' in band_data:
        summary += f"Final energy: {band_data['final_energy']:.4f} eV\n"
    if 'fermi_level' in band_data:
        summary += f"Fermi level: {band_data['fermi_level']:.4f} eV\n"

    # Generate band structure plot
    try:
        from src.GlassCrewAgent.tools.vasp_analysis import plot_band_structure_projected
        vasprun_path = os.path.join(job_dir, "band", "output", "vasprun.xml")
        if os.path.exists(vasprun_path):
            plot_path = _call_tool(plot_band_structure_projected, vasprun_path, os.path.join(job_dir, "band", "band_structure.png"))
            summary += f"\nBand structure plot: {plot_path}\n"
    except Exception:
        pass

    return summary
