"""
Test VASP job submission with existing input files.
This skips Materials Project download and tests the upload/submission step directly.

Usage:
    python tests/test_vasp_upload_existing.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from src.GlassCrewAgent.tools.vasp_tools import (
    test_ssh_connection,
    list_available_partitions,
    submit_vasp_job,
    check_job_status,
)

def print_section(title):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)

def main():
    print_section("Starting VASP Upload/Submission Test (existing input)")

    # Use the most recent job directory with already generated input
    job_dir = "/home/shiqiany/AIagent/GlassCrewAgent/src/data/vasp_calculations/job_20260416_121349"
    input_dir = os.path.join(job_dir, "input")
    material_id = "mp-149"

    print(f"Using existing input directory: {input_dir}")
    print(f"Files: {os.listdir(input_dir)}")

    # Step 1: Check environment
    print_section("Step 1: Checking SSH connection")
    result = test_ssh_connection.func()
    print(result)

    if "✅" not in result:
        print("❌ SSH connection failed, cannot continue")
        sys.exit(1)
    print("✅ SSH connection successful")

    # Step 2: List partitions
    print_section("Step 2: Listing available partitions")
    partitions_result = list_available_partitions.func()
    print(partitions_result)

    # Step 3: Submit job
    print_section("Step 3: Submitting job to remote cluster")
    submit_result = submit_vasp_job.func(input_dir)
    print(submit_result)

    if "Failed" in submit_result or "Error" in submit_result or "submission failed" in submit_result:
        print("❌ Job submission failed")
        sys.exit(1)

    print("✅ Job submitted successfully")

    # Extract job ID
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
        print(f"Result: {submit_result}")
        sys.exit(1)

    print(f"✅ Extracted job ID: {job_id}")

    # Step 4: Check job status
    print_section(f"Step 4: Checking status for job {job_id}")
    status_result = check_job_status.func(job_id)
    print(status_result)

    # Final summary
    print_section("TEST SUMMARY")
    print(f"""
✅ All steps completed successfully!
  - Input directory: {input_dir}
  - Job ID: {job_id}
  - Status: {status_result}

The job is now queued/running on the supercomputer. When it completes, you can:
  1. Download results: download_vasp_results.func({job_id}, '{material_id}')
  2. Parse output: parse_vasp_output.func('{material_id}')
""")

    return 0

if __name__ == "__main__":
    sys.exit(main())
