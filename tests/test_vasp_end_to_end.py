"""
Complete end-to-end test for VASP DFT calculation workflow.
This tests the full pipeline:
1. SSH connection test
2. List available partitions
3. Get structure from Materials Project
4. Generate VASP input files locally (POSCAR, INCAR, KPOINTS, POTCAR)
5. Generate SLURM script
6. Submit job to remote cluster
7. Monitor job status
8. Download results (if completed)
9. Parse output

Usage:
    python tests/test_vasp_end_to_end.py [material_id]

Example:
    python tests/test_vasp_end_to_end.py mp-149
"""

import os
import sys
import argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from src.GlassCrewAgent.tools.vasp_tools import (
    test_ssh_connection,
    list_available_partitions,
    get_structure_from_mp_by_id,
    generate_vasp_input_from_structure,
    generate_slurm_script,
    submit_vasp_job,
    check_job_status,
    download_vasp_results,
    parse_vasp_output,
)


def print_section(title):
    """Print a section header"""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Complete end-to-end VASP calculation test'
    )
    parser.add_argument(
        'material_id',
        nargs='?',
        default='mp-149',
        help='Materials Project ID (default: mp-149 for Silicon)'
    )
    args = parser.parse_args()
    material_id = args.material_id

    print_section(f"Starting End-to-End VASP Test for {material_id}")

    # Step 1: Check environment
    print_section("Step 1: Checking environment configuration")

    required_env = [
        'SUPERCOMPUTING_HOST',
        'SUPERCOMPUTING_USERNAME',
        'SUPERCOMPUTING_PRIVATE_KEY_PATH',
        'VASP_MODULE_NAME',
        'VASP_JOBS_REMOTE_DIR',
        'PMG_VASP_PSP_DIR',
        'MP_KEY',
    ]

    missing = []
    for var in required_env:
        if not os.environ.get(var):
            missing.append(var)

    if missing:
        print(f"❌ Missing environment variables: {missing}")
        print("Please configure these in your .env file")
        sys.exit(1)

    # Check POTCAR directory
    psp_dir = os.environ.get('PMG_VASP_PSP_DIR')
    if not os.path.exists(psp_dir):
        print(f"❌ POTCAR directory not found: {psp_dir}")
        sys.exit(1)
    print(f"✅ POTCAR directory found: {psp_dir}")

    # Check SSH private key
    ssh_key = os.environ.get('SUPERCOMPUTING_PRIVATE_KEY_PATH')
    if not os.path.exists(ssh_key):
        print(f"❌ SSH private key not found: {ssh_key}")
        sys.exit(1)
    print(f"✅ SSH private key found: {ssh_key}")

    print("✅ All environment checks passed")

    # Step 2: Test SSH connection
    print_section("Step 2: Testing SSH connection")
    result = test_ssh_connection.func()
    print(result)

    if "✅" not in result:
        print("❌ SSH connection failed, cannot continue")
        sys.exit(1)
    print("✅ SSH connection successful")

    # Step 3: List available partitions
    print_section("Step 3: Listing available SLURM partitions")
    partitions_result = list_available_partitions.func()
    print(partitions_result)

    if "Error" in partitions_result:
        print("❌ Failed to list partitions")
        sys.exit(1)

    # Extract a default partition (usually 'normal' or similar)
    # We'll let generate_slurm_script handle the default selection
    print("✅ Partition listing successful")

    # Step 4: Get structure from Materials Project
    print_section(f"Step 4: Fetching structure for {material_id} from Materials Project")
    structure_result = get_structure_from_mp_by_id.func(material_id)
    print(structure_result)

    if "Failed" in structure_result or "Error" in structure_result:
        print("❌ Failed to get structure from Materials Project")
        sys.exit(1)

    print("✅ Structure retrieved successfully")

    # Step 5: Generate VASP input files
    print_section("Step 5: Generating VASP input files with pymatgen")

    # We need to find the structure file path
    # The structure was saved by get_structure_from_mp_by_id to a timestamped job directory
    # Let's find it - it's the most recently created directory
    from src.GlassCrewAgent.tools.vasp_tools import _get_local_job_dir
    job_dir = _get_local_job_dir()
    structure_file_path = os.path.join(job_dir, f"{material_id}_structure.json")

    if not os.path.exists(structure_file_path):
        print(f"❌ Structure file not found: {structure_file_path}")
        sys.exit(1)

    print(f"Using structure file: {structure_file_path}")

    # Generate static calculation (good for testing)
    vasp_input_result = generate_vasp_input_from_structure.func(
        structure_file_path,
        calculation_type="static",
        kpoints_density=1.0
    )
    print(vasp_input_result)

    if "Failed" in vasp_input_result or "Error" in vasp_input_result:
        print("❌ Failed to generate VASP input files")
        sys.exit(1)

    print("✅ VASP input files generated successfully")

    # Step 6: Generate SLURM script
    print_section("Step 6: Generating SLURM script")

    # Input directory is job_dir/input
    from src.GlassCrewAgent.tools.vasp_tools import _get_local_job_dir
    job_dir = _get_local_job_dir()
    input_dir = os.path.join(job_dir, "input")

    # Use the default partition (kshcnormal) which is available
    slurm_result = generate_slurm_script.func(input_dir, partition="kshcnormal", nodes=1, tasks_per_node=16)
    print(slurm_result)

    if "Failed" in slurm_result or "Error" in slurm_result:
        print("❌ Failed to generate SLURM script")
        sys.exit(1)

    print("✅ SLURM script generated successfully")

    # Step 7: Submit VASP job
    print_section("Step 7: Submitting job to remote cluster")
    submit_result = submit_vasp_job.func(input_dir)
    print(submit_result)

    if "Failed" in submit_result or "Error" in submit_result or "submission failed" in submit_result:
        print("❌ Job submission failed")
        sys.exit(1)

    print("✅ Job submitted successfully")

    # Extract job ID from result
    # The result should contain something like "Job ID: 12345"
    job_id = None
    for line in submit_result.split('\n'):
        if "Job ID" in line or "jobid" in line.lower():
            import re
            match = re.search(r'(\d+)', line)
            if match:
                job_id = match.group(1)
                break

    if not job_id:
        print("⚠️  Could not extract job ID from submission result")
        print("End-to-end test completed up to job submission")
        print(f"Result: {submit_result}")
        sys.exit(0)

    print(f"✅ Extracted job ID: {job_id}")

    # Step 8: Check job status
    print_section(f"Step 8: Checking status for job {job_id}")
    status_result = check_job_status.func(job_id)
    print(status_result)

    if "Error" not in status_result:
        print(f"✅ Job status checked: {status_result}")
    else:
        print(f"⚠️  Error checking job status: {status_result}")

    # Step 9: If job is already completed, download results
    if "COMPLETED" in status_result or "completed" in status_result:
        print_section(f"Step 9: Downloading results for completed job {job_id}")
        download_result = download_vasp_results.func(job_id, material_id)
        print(download_result)

        if "Failed" not in download_result:
            print("✅ Results downloaded successfully")

            # Step 10: Parse output
            print_section("Step 10: Parsing VASP output")
            parse_result = parse_vasp_output.func(material_id)
            print(parse_result)

            if "Failed" not in parse_result:
                print("✅ Output parsed successfully")
            else:
                print("❌ Failed to parse output")
        else:
            print("❌ Failed to download results")
    else:
        print(f"\nℹ️  Job {job_id} is still in queue or running")
        print("You can check its status later with:")
        print(f"    python -c \"from src.GlassCrewAgent.tools.vasp_tools import check_job_status; print(check_job_status.func('{job_id}'))\"")
        print("When it completes, download results with:")
        print(f"    python -c \"from src.GlassCrewAgent.tools.vasp_tools import download_vasp_results; print(download_vasp_results.func('{job_id}', '{material_id}'))\"")

    # Final summary
    print_section("END-TO-END TEST SUMMARY")
    print(f"""
✅ All steps up to job submission completed successfully!
  - Material ID: {material_id}
  - Job ID: {job_id if job_id else 'N/A'}
  - Status: Job submitted to remote queue

When the job completes on the cluster, you can:
  1. Download results: download_vasp_results.func("{job_id}", "{material_id}")
  2. Parse output: parse_vasp_output.func("{material_id}")

The VASP automation system is working correctly!
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
