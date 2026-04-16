"""
VASP First-Principles Calculation Tools for CrewAI with Supercomputing Internet Integration

This module provides tools for automated VASP calculations on the Supercomputing Internet platform
(https://www.scnet.cn/), integrated with Materials Project for structure retrieval and pymatgen for
structure processing.

Key Features:
- Retrieve crystal structures from Materials Project
- Automatically generate all VASP input files (POSCAR, INCAR, KPOINTS, POTCAR)
- SFTP upload to Supercomputing Internet
- Submit jobs via Slurm sbatch
- Monitor job status with squeue
- Download results upon completion
- Parse output and extract key properties (energy, band gap, forces, etc.)

Required environment variables:
- SUPERCOMPUTING_HOST: SSH host for Supercomputing Internet (default: login.scnet.cn)
- SUPERCOMPUTING_PORT: SSH port (default: 65023 for Supercomputing Internet)
- SUPERCOMPUTING_USERNAME: Your username
- SUPERCOMPUTING_PRIVATE_KEY_PATH: Path to your SSH private key
- PMG_VASP_PSP_DIR: Path to your VASP POTCAR (pseudopotential) directory (required by pymatgen)
- VASP_MODULE_NAME: VASP module name to load (default: vasp-6.4.2-intelmpi2017_ioptcell)
- VASP_JOBS_REMOTE_DIR: Base remote directory for all VASP jobs (default: ~/vasp_jobs) - each job gets its own timestamped subdirectory

Required dependencies:
- paramiko: SSH/SFTP connectivity
- pymatgen: Crystal structure processing and VASP input generation
"""

import os
import time
import paramiko
import re
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from crewai.tools import tool

# Global SSH client singleton
_ssh_client = None
_sftp_client = None


def _get_ssh() -> Tuple[Optional[paramiko.SSHClient], Optional[paramiko.SFTPClient]]:
    """Get or create SSH/SFTP connection using environment configuration"""
    global _ssh_client, _sftp_client

    if _ssh_client is not None:
        try:
            _ssh_client.exec_command("echo 1", timeout=5)
            return _ssh_client, _sftp_client
        except Exception:
            try:
                _sftp_client.close()
                _ssh_client.close()
            except:
                pass
            _ssh_client = None
            _sftp_client = None

    host = os.environ.get("SUPERCOMPUTING_HOST", "login.scnet.cn")
    username = os.environ.get("SUPERCOMPUTING_USERNAME", "")
    port = int(os.environ.get("SUPERCOMPUTING_PORT", "65023"))
    key_path = os.environ.get("SUPERCOMPUTING_PRIVATE_KEY_PATH", os.path.expanduser("~/.ssh/id_rsa"))

    if not username:
        return None, None

    key_path = os.path.expanduser(key_path)
    if not os.path.exists(key_path):
        print(f"Error: SSH private key not found at {key_path}")
        return None, None

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=host,
            username=username,
            key_filename=key_path,
            port=port,
            timeout=30
        )
        sftp = ssh.open_sftp()
        _ssh_client = ssh
        _sftp_client = sftp
        return ssh, sftp
    except Exception as e:
        print(f"SSH connection error: {str(e)}")
        return None, None


def _get_local_job_dir(job_id: Optional[int] = None) -> str:
    """Get or create local directory for VASP calculation"""
    base_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "vasp_calculations"
    )
    os.makedirs(base_dir, exist_ok=True)

    if job_id:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_dir = os.path.join(base_dir, f"job_{job_id}_{timestamp}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_dir = os.path.join(base_dir, f"job_{timestamp}")

    os.makedirs(job_dir, exist_ok=True)
    os.makedirs(os.path.join(job_dir, "input"), exist_ok=True)
    os.makedirs(os.path.join(job_dir, "output"), exist_ok=True)

    return job_dir


# =============================================================================
# SSH Connection and Information Tools
# =============================================================================

@tool("Test SSH Connection")
def test_ssh_connection() -> str:
    """
    Test the SSH connection to Supercomputing Internet.

    Returns:
        Connection status and basic information
    """
    ssh, sftp = _get_ssh()
    if ssh is None:
        return "Error: Could not establish SSH connection. Check your environment configuration (SUPERCOMPUTING_HOST, SUPERCOMPUTING_USERNAME, SUPERCOMPUTING_PRIVATE_KEY_PATH)."

    try:
        stdin, stdout, stderr = ssh.exec_command("hostname && whoami && sinfo -s")
        exit_code = stdout.channel.recv_exit_status()
        result = stdout.read().decode()
        error = stderr.read().decode()

        if exit_code != 0:
            return f"Connected but command failed:\nExit code: {exit_code}\nError: {error}"

        return f"✅ SSH connection successful!\n\nOutput:\n{result}"
    except Exception as e:
        return f"Error testing connection: {str(e)}"


@tool("List Available Partitions")
def list_available_partitions() -> str:
    """
    List all available partitions (queues) on the supercomputing cluster that can be used for VASP jobs.

    Returns:
        Formatted list of available partitions with their specifications
    """
    ssh, _ = _get_ssh()
    if ssh is None:
        return "Error: SSH connection not available."

    try:
        stdin, stdout, stderr = ssh.exec_command("sinfo -s")
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode()
        error = stderr.read().decode()

        if exit_code != 0:
            return f"Error listing partitions: {error}"

        return f"Available partitions (queues):\n\n{output}"
    except Exception as e:
        return f"Error: {str(e)}"


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
        from pymatgen.core.structure import Structure
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
        from pymatgen.core.structure import Structure
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
    Generate complete set of VASP input files (POSCAR, INCAR, KPOINTS, POTCAR) from a pymatgen structure file.

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

        # In modern pymatgen, kpoints_density -> reciprocal_density
        # reciprocal_density is typically ~ 100 for kpoints_density ~ 0.5 1/Å
        reciprocal_density = int(kpoints_density * 200)  # Convert 0.5 -> 100

        # Our POTCAR directory has elements directly in the root (no extra POT_GGA_PAW_PBE layer)
        # user_potcar_functional=None disables the extra directory layer
        if calculation_type == "structure_relaxation":
            vis = MPRelaxSet(structure, reciprocal_density=reciprocal_density, user_potcar_functional=None)
        elif calculation_type == "static":
            vis = MPStaticSet(structure, reciprocal_density=reciprocal_density, user_potcar_functional=None)
        elif calculation_type in ["dos", "band"]:
            # For DOS and band structure calculations, use MPNonSCFSet in modern pymatgen
            vis = MPNonSCFSet(structure, reciprocal_density=reciprocal_density, user_potcar_functional=None)
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
    job_name: Optional[str] = None
) -> str:
    """
    Generate SLURM submission script for VASP calculation.

    Args:
        input_dir: Local input directory containing VASP input files
        partition: Partition (queue) name to use (use list_available_partitions to get options)
        nodes: Number of nodes to request (default 1)
        tasks_per_node: Number of MPI tasks per node (default 32 for typical compute node)
        job_name: Optional job name (defaults to vasp_calculation)

    Returns:
        Path to generated SLURM script
    """
    vasp_module = os.environ.get("VASP_MODULE_NAME", "vasp-6.4.2-intelmpi2017_ioptcell")

    if not job_name:
        job_name = "vasp_calculation"

    # Extract the VASP version directory from module name
    # Module format: vasp-5.4.4-ioptcell_intelmpi2017_hdf5_libxc
    # Full path: /public/home/scniv4a4go/apprepo/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc
    vasp_dir = vasp_module.split(' ', 1)[-1] if ' ' in vasp_module else vasp_module
    # Remove the 'vasp-' prefix if present
    if vasp_dir.startswith('vasp-'):
        vasp_dir = vasp_dir[5:]
    vasp_path = f"/public/home/scniv4a4go/apprepo/vasp/{vasp_dir}"

    slurm_content = f"""#!/bin/bash
#SBATCH -J {job_name}
#SBATCH -p {partition}
#SBATCH -N {nodes}
#SBATCH --ntasks-per-node={tasks_per_node}

module purge
module load {vasp_module}
# Source the environment script to correctly set MKL and compiler libraries (scnet.cn specific)
source {vasp_path}/scripts/env.sh

# MKL optimizations for better performance
export MKL_DEBUG_CPU_TYPE=5
export MKL_CBWR=AVX2
export I_MPI_PIN_DOMAIN=numa

# Increase stack size to avoid segmentation faults
ulimit -s unlimited

WDIR=$(pwd)
echo "Starting VASP calculation on $SLURM_JOB_NODELIST"
echo "Working directory: $WDIR"
echo "Number of nodes: $SLURM_NNODES"
echo "Total tasks: $SLURM_NPROCS"

# Run VASP with MPI (using srun for Slurm)
srun --mpi=pmi2 vasp_std

echo "VASP calculation completed"
"""

    script_path = os.path.join(input_dir, "vasp.slurm")
    with open(script_path, 'w') as f:
        f.write(slurm_content)

    summary = "Successfully generated SLURM script:\n\n"
    summary += "Path: " + script_path + "\n"
    summary += "Job name: " + job_name + "\n"
    summary += "Partition: " + partition + "\n"
    summary += "Nodes: " + str(nodes) + "\n"
    summary += "Total tasks: " + str(nodes * tasks_per_node) + "\n"
    summary += "VASP module: " + vasp_module + "\n"

    return summary


# =============================================================================
# Job Submission and Monitoring
# =============================================================================

@tool("Submit VASP Job")
def submit_vasp_job(local_input_dir: str) -> str:
    """
    Upload all VASP input files to supercomputer and submit the job.
    Creates a new timestamped remote working directory to avoid conflicts between jobs.

    Args:
        local_input_dir: Local directory containing all input files (POSCAR, INCAR, KPOINTS, POTCAR, vasp.slurm)

    Returns:
        Job ID if submission successful
    """
    ssh, sftp = _get_ssh()
    if ssh is None or sftp is None:
        return "Error: SSH/SFTP connection not available"

    # Create a new timestamped remote working directory under ~/vasp_jobs/
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_remote_dir = os.environ.get("VASP_JOBS_REMOTE_DIR", "~/vasp_jobs")
    remote_dir = f"{base_remote_dir.rstrip('/')}/job_{timestamp}"

    try:
        # Create base directory if it doesn't exist
        ssh.exec_command(f"mkdir -p {base_remote_dir}")
        # Create job-specific directory
        ssh.exec_command(f"mkdir -p {remote_dir}")

        # Get absolute path (expands ~ to full path) using realpath
        stdin, stdout, stderr = ssh.exec_command(f"realpath {remote_dir}")
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            error = stderr.read().decode()
            return f"Error: Failed to create remote directory {remote_dir}: {error}"
        # Get absolute path (expands ~ to full path)
        abs_remote_dir = stdout.read().decode().strip()
    except Exception as e:
        return f"Error creating remote directory: {str(e)}"

    uploaded = []
    try:
        for filename in os.listdir(local_input_dir):
            local_path = os.path.join(local_input_dir, filename)
            if os.path.isfile(local_path):
                # Use absolute path for SFTP to avoid ~ issues
                remote_path = f"{abs_remote_dir.rstrip('/')}/{filename}"
                sftp.put(local_path, remote_path)
                uploaded.append(filename)
        remote_dir = abs_remote_dir
    except Exception as e:
        return f"Error uploading files: {str(e)}"

    # Submit job
    cmd = f"cd {remote_dir} && sbatch vasp.slurm"
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode()
        error = stderr.read().decode()

        if exit_code != 0:
            return f"Job submission failed with exit code {exit_code}:\n{error}"

        # Parse job ID from output: "Submitted batch job 123456"
        match = re.search(r'Submitted batch job (\d+)', output)
        if not match:
            return f"Could not parse job ID from output: {output}"

        job_id = match.group(1)
        return f"✅ Job submitted successfully!\n\nJob ID: {job_id}\nUploaded files: {', '.join(uploaded)}\nRemote directory: {remote_dir}"
    except Exception as e:
        return f"Error submitting job: {str(e)}"


@tool("Check Job Status")
def check_job_status(job_id: int) -> str:
    """
    Check the current status of a submitted VASP job.

    Args:
        job_id: Slurm job ID

    Returns:
        Current job status (PENDING, RUNNING, COMPLETED, FAILED)
    """
    ssh, _ = _get_ssh()
    if ssh is None:
        return "Error: SSH connection not available"

    try:
        stdin, stdout, stderr = ssh.exec_command(f"squeue -j {job_id} -h")
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode()

        if exit_code != 0 or not output.strip():
            # No output from squeue means job is no longer in queue
            # Check accounting with sacct for completion status
            stdin2, stdout2, stderr2 = ssh.exec_command(f"sacct -j {job_id} -o State -n -P")
            output2 = stdout2.read().decode()
            if output2.strip():
                state = output2.strip().split('\n')[0]
                return f"Job {job_id} status: {state}"
            else:
                return f"Job {job_id} not found in queue or accounting"

        # Job is still in queue, parse status
        parts = output.strip().split()
        if len(parts) >= 5:
            status_code = parts[4]
            status_map = {
                'PD': 'PENDING (queued)',
                'R': 'RUNNING',
                'CG': 'COMPLETING (finalizing)',
                'CF': 'CONFIGURING',
                'NF': 'NODE_FAIL',
                'RV': 'REVOKED',
                'SE': 'SPECIAL_EXIT',
                'ST': 'STOPPED',
                'S': 'SUSPENDED'
            }
            status = status_map.get(status_code, status_code)
            partition = parts[1]
            name = parts[2]
            return f"Job {job_id} status: {status}\nPartition: {partition}\nName: {name}"
        else:
            return f"Job {job_id} is in queue:\n{output}"
    except Exception as e:
        return f"Error checking job status: {str(e)}"


@tool("Cancel Job")
def cancel_job(job_id: int) -> str:
    """
    Cancel a running or pending VASP job.

    Args:
        job_id: Slurm job ID

    Returns:
        Cancellation confirmation
    """
    ssh, _ = _get_ssh()
    if ssh is None:
        return "Error: SSH connection not available"

    try:
        stdin, stdout, stderr = ssh.exec_command(f"scancel {job_id}")
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode()
        error = stderr.read().decode()

        if exit_code != 0:
            return f"Cancellation failed with exit code {exit_code}:\n{error}"

        return f"✅ Job {job_id} cancelled successfully"
    except Exception as e:
        return f"Error cancelling job: {str(e)}"


# =============================================================================
# Result Download and Parsing
# =============================================================================

@tool("Download VASP Results")
def download_vasp_results(job_id: int, local_job_dir: Optional[str] = None, remote_job_dir: Optional[str] = None) -> str:
    """
    Download all VASP result files from the supercomputer after job completion.

    Args:
        job_id: Slurm job ID
        local_job_dir: Optional local directory to save results (auto-created if not given)
        remote_job_dir: Optional remote job directory (auto-detected from timestamp if not given)

    Returns:
        Summary of downloaded files and local directory
    """
    ssh, sftp = _get_ssh()
    if ssh is None or sftp is None:
        return "Error: SSH/SFTP connection not available"

    if remote_job_dir is None:
        # Fallback to old behavior if remote directory not specified
        remote_dir = os.environ.get("VASP_REMOTE_DIR", "~/apprepo/vasp/6.4.2-intelmpi2017_ioptcell/case")
    else:
        remote_dir = remote_job_dir

    if not local_job_dir:
        local_job_dir = _get_local_job_dir(job_id)
    output_dir = os.path.join(local_job_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # List of common VASP output files to download
    output_files = [
        f"slurm-{job_id}.out",
        "OUTCAR",
        "CONTCAR",
        "OSZICAR",
        "INCAR",
        "KPOINTS",
        "POSCAR",
        "XDATCAR",
        "CHGCAR",
        "WAVECAR",
        "PROCAR"
    ]

    downloaded = []
    failed = []

    for filename in output_files:
        remote_path = f"{remote_dir.rstrip('/')}/{filename}"
        try:
            # Check if file exists
            sftp.stat(remote_path)
            local_path = os.path.join(output_dir, filename)
            sftp.get(remote_path, local_path)
            downloaded.append(filename)
        except IOError:
            failed.append(filename)
        except Exception as e:
            failed.append(f"{filename} ({str(e)})")

    summary = f"✅ Results download complete:\n\n"
    summary += f"Job ID: {job_id}\n"
    summary += f"Local output directory: {output_dir}\n"
    summary += f"\nDownloaded files ({len(downloaded)}):\n"
    for f in downloaded:
        f_path = os.path.join(output_dir, f)
        size = os.path.getsize(f_path)
        size_kb = size / 1024
        summary += f"  - {f} ({size_kb:.1f} KB)\n"

    if failed:
        summary += f"\nFiles not found/failed ({len(failed)}):\n"
        for f in failed:
            summary += f"  - {f}\n"

    return summary


@tool("Parse VASP Output")
def parse_vasp_output(outcar_path: str) -> str:
    """
    Parse VASP OUTCAR file and extract key results.

    Args:
        outcar_path: Path to OUTCAR file

    Returns:
        Extracted properties (energy, band gap, forces, Fermi level, etc.)
    """
    try:
        from pymatgen.io.vasp import Outcar
        import numpy as np
    except ImportError as e:
        return f"Error: Required package not installed. Details: {str(e)}"

    if not os.path.exists(outcar_path):
        return f"Error: OUTCAR file not found: {outcar_path}"

    try:
        outcar = Outcar(outcar_path)

        summary = "VASP OUTCAR Parsing Results:\n\n"

        # Final energy
        if hasattr(outcar, 'final_energy'):
            summary += f"Final energy: {outcar.final_energy:.6f} eV\n"

        # Energy per atom
        if hasattr(outcar, 'final_energy') and hasattr(outcar, 'structure'):
            n_atoms = len(outcar.structure)
            e_per_atom = outcar.final_energy / n_atoms
            summary += f"Final energy per atom: {e_per_atom:.6f} eV/atom\n"

        # Band gap from VASP
        try:
            bg = None
            if hasattr(outcar, 'bandgap'):
                bg = outcar.bandgap
            elif hasattr(outcar, 'bands') and outcar.bands is not None:
                # Modern pymatgen stores band gap in bands object
                bg = outcar.bands.get_gap()
            if bg is not None:
                summary += f"Band gap: {bg:.4f} eV\n"
                if bg > 0:
                    summary += "  → Semiconductor/insulator\n"
                else:
                    summary += "  → Metal\n"
        except Exception:
            # Skip band gap if not available
            pass

        # Fermi level
        if hasattr(outcar, 'efermi'):
            summary += f"Fermi level: {outcar.efermi:.4f} eV\n"

        # Maximum force on atoms
        try:
            forces = None
            if hasattr(outcar, 'forces'):
                forces = outcar.forces
            elif hasattr(outcar, 'ionic_steps') and outcar.ionic_steps:
                # Modern pymatgen stores forces in ionic_steps
                last_step = outcar.ionic_steps[-1]
                forces = last_step.get('forces', None)
            if forces is not None and len(forces) > 0:
                force_norms = np.linalg.norm(forces, axis=1)
                max_force = np.max(force_norms)
                avg_force = np.mean(force_norms)
                summary += f"Maximum force: {max_force:.6f} eV/Å\n"
                summary += f"Average force: {avg_force:.6f} eV/Å\n"
        except Exception:
            # Skip forces if not available
            pass

        # Magnetic moments
        try:
            if hasattr(outcar, 'magnetization'):
                mag = outcar.magnetization
                if mag is not None and len(mag) > 0:
                    total_mag = sum(m[0] for m in mag)
                    summary += f"Total magnetization: {total_mag:.4f} μB\n"
        except Exception:
            pass

        # Number of ionic steps
        try:
            n_steps = None
            if hasattr(outcar, 'nionic_steps'):
                n_steps = outcar.nionic_steps
            elif hasattr(outcar, 'ionic_steps'):
                n_steps = len(outcar.ionic_steps)
            if n_steps is not None:
                summary += f"Number of ionic steps: {n_steps}\n"
        except Exception:
            pass

        return summary
    except Exception as e:
        return f"Error parsing OUTCAR: {str(e)}"


# =============================================================================
# End-to-end Complete Calculation
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
    step1_result = get_structure_from_mp_by_id(material_id)
    if "Error" in step1_result:
        return step1_result

    # Extract structure file path from result
    match = re.search(r'Structure saved to: (.+)$', step1_result, re.MULTILINE)
    if not match:
        return f"Could not find structure file path in result:\n{step1_result}"
    structure_file = match.group(1)
    job_dir = os.path.dirname(structure_file)

    # Step 2: Generate VASP input
    step2_result = generate_vasp_input_from_structure(
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
    step3_result = generate_slurm_script(
        input_dir=input_dir,
        partition=partition,
        nodes=nodes,
        tasks_per_node=tasks_per_node,
        job_name=job_name
    )
    if "Error" in step3_result:
        return step3_result

    # Step 4: Submit job
    step4_result = submit_vasp_job(input_dir)
    if "error" in step4_result.lower():
        return step4_result

    # Extract job ID and remote directory
    match_id = re.search(r'Job ID: (\d+)', step4_result)
    if not match_id:
        return f"Could not find job ID in result:\n{step4_result}"
    job_id = int(match_id.group(1))

    match_dir = re.search(r'Remote directory: (.+)$', step4_result, re.MULTILINE)
    if match_dir:
        remote_job_dir = match_dir.group(1)
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
        status_result = check_job_status(job_id)
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
    step6_result = download_vasp_results(job_id, job_dir, remote_job_dir)
    if "Error" in step6_result:
        return summary + "\n" + step6_result

    # Step 7: Parse results if OUTCAR exists
    output_dir = os.path.join(job_dir, "output")
    outcar_path = os.path.join(output_dir, "OUTCAR")
    parsed_results = ""
    if os.path.exists(outcar_path):
        parsed_results = parse_vasp_output(outcar_path)

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
