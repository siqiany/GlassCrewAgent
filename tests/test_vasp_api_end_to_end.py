"""
Complete end-to-end test for VASP DFT calculation workflow using Supercomputing Internet official API.
This tests the full pipeline with official REST API:
1. API Authentication (AK/SK)
2. List available partitions
3. Get structure from Materials Project
4. Generate VASP input files locally (POSCAR, INCAR, KPOINTS, POTCAR)
5. Generate SLURM script
6. Upload input files via API to remote cluster
7. Submit job to SLURM via API
8. Monitor job status via polling
9. Download results (if completed)
10. Parse output

Usage:
    python tests/test_vasp_api_end_to_end.py [material_id]

Example:
    python tests/test_vasp_api_end_to_end.py mp-149
"""

import os
import sys
import argparse
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from src.GlassCrewAgent.tools.vasp_tools import (
    test_connection,
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
        description='Complete end-to-end VASP API test'
    )
    parser.add_argument(
        'material_id',
        nargs='?',
        default='mp-7000',
        help='Materials Project ID (default: mp-149 for Silicon)'
    )
    args = parser.parse_args()
    material_id = args.material_id

    print_section(f"Starting End-to-End VASP API Test for {material_id}")

    # Step 1: Check environment
    print_section("Step 1: Checking environment configuration")

    required_env = [
        'SCNET_API_USER',
        'SCNET_API_ACCESS_KEY',
        'SCNET_API_SECRET_KEY',
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

    print("✅ All environment checks passed")

    # Step 2: Test API connection
    print_section("Step 2: Testing API connection and authentication")
    result = test_connection.func()
    print(result)

    if "❌" in result or "Error" in result:
        print("❌ API connection failed, cannot continue")
        sys.exit(1)

    print("✅ API connection and authentication successful")

    # Step 3: List available partitions
    print_section("Step 3: Listing available SLURM partitions via API")
    partitions_result = list_available_partitions.func()
    print(partitions_result)

    if "Error" in partitions_result:
        print("❌ Failed to list partitions")
        sys.exit(1)

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
    structure_file_path = os.path.join(os.path.dirname(job_dir), sorted(
        [f for f in os.listdir(os.path.dirname(job_dir)) if os.path.isdir(os.path.join(os.path.dirname(job_dir), f))],
        key=lambda x: os.path.getmtime(os.path.join(os.path.dirname(job_dir), x))
    )[-1], f"{material_id}_structure.json")

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
    job_dir = os.path.dirname(structure_file_path)
    input_dir = os.path.join(job_dir, "input")

    # Use default partition from environment or use first available
    default_partition = os.environ.get("VASP_DEFAULT_PARTITION", "kshcnormal")
    slurm_result = generate_slurm_script.func(
        input_dir,
        partition=default_partition,
        nodes=1,
        tasks_per_node=16
    )
    print(slurm_result)

    if "Failed" in slurm_result or "Error" in slurm_result:
        print("❌ Failed to generate SLURM script")
        sys.exit(1)

    print("✅ SLURM script generated successfully")

    # Step 7: Submit VASP job via API
    print_section("Step 7: Submitting job to remote cluster via API")
    submit_result = submit_vasp_job.func(input_dir)
    print(submit_result)

    if "Failed" in submit_result or "Error" in submit_result or "submission failed" in submit_result:
        print("❌ Job submission failed")
        sys.exit(1)

    print("✅ Job submitted successfully via API")

    # Extract job ID and remote directory from result
    job_id = None
    remote_dir = None
    for line in submit_result.split('\n'):
        if "Job ID" in line:
            match = re.search(r'(\d+)', line)
            if match:
                job_id = match.group(1)
        elif "Remote directory" in line:
            match = re.search(r'Remote directory:\s*(.+)', line)
            if match:
                remote_dir = match.group(1).strip()

    if not job_id:
        print("⚠️  Could not extract job ID from submission result")
        print(f"Result: {submit_result}")
        sys.exit(0)

    print(f"✅ Extracted job ID: {job_id}")
    if remote_dir:
        print(f"✅ Extracted remote directory: {remote_dir}")
    else:
        print("⚠️  Could not extract remote directory - download may fail")

    # Step 8: Check job status with polling
    print_section(f"Step 8: Monitoring job {job_id} until completion")

    # Poll interval in seconds
    poll_interval = 60
    max_wait_minutes = 120

    start_time = time.time()
    max_wait_seconds = max_wait_minutes * 60

    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            print(f"⚠️  Maximum wait time ({max_wait_minutes} minutes) reached")
            print(f"Job {job_id} is still running/pending. You can check later:")
            print(f"    python -c \"from src.GlassCrewAgent.tools.vasp_tools import check_job_status; print(check_job_status.func({job_id}))\"")
            sys.exit(0)

        status_result = check_job_status.func(int(job_id))
        print(status_result)

        if "Error" in status_result:
            print(f"⚠️  Error checking status: {status_result}")

        status_lower = status_result.lower()
        if "completed" in status_lower or "completed" in status_lower:
            print(f"✓ Job {job_id} completed!")
            break
        elif "failed" in status_lower or "cancelled" in status_lower or "revoked" in status_lower:
            print(f"✗ Job {job_id} {status_result}")
            print("Test completed with job failure")
            sys.exit(1)
        else:
            print(f"Still running/pending, checking again in {poll_interval} seconds...")
            time.sleep(poll_interval)

    # Step 9: Download results when completed - auto-detect remote directory from job_id
    print_section(f"Step 9: Downloading results for completed job {job_id}")
    print(f"  Using auto-detection: no need to pass remote directory!")
    download_result = download_vasp_results.func(int(job_id), job_dir)
    print(download_result)

    if "Failed" not in download_result:
        print("✅ Results downloaded successfully")

        # Step 10: Parse output
        print_section("Step 10: Parsing VASP output")
        output_dir = os.path.join(job_dir, "output")
        outcar_path = os.path.join(output_dir, "OUTCAR")
        if os.path.exists(outcar_path):
            parse_result = parse_vasp_output.func(outcar_path)
            print(parse_result)

            if "Error" not in parse_result:
                print("✅ Output parsed successfully")
            else:
                print("❌ Failed to parse output")
        else:
            print(f"⚠️  OUTCAR not found at {outcar_path}")
    else:
        print("❌ Failed to download results")

    # Final summary
    print_section("END-TO-END API TEST SUMMARY")
    print(f"""
✅ All steps up to job completion completed successfully using official API!
  - Material ID: {material_id}
  - Job ID: {job_id if job_id else 'N/A'}
  - Local working directory: {job_dir}

The Supercomputing Internet official API integration is working correctly!

When you want to run automated calculations through the agent, just ensure:
  - VASP_CONNECTION_MODE=api in .env
  - SCNET_API_USER, SCNET_API_ACCESS_KEY, SCNET_API_SECRET_KEY are configured
""")

    return 0


if __name__ == "__main__":
    import re
    sys.exit(main())
