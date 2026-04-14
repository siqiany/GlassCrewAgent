"""
Test file for VASP tools integration with Supercomputing Internet.
Run this to verify the VASP integration is properly configured.

Usage:
    pytest tests/test_vasp_tools.py -v
    or
    python tests/test_vasp_tools.py
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from src.GlassCrewAgent.tools.vasp_tools import (
    test_ssh_connection,
    list_available_partitions,
)


def test_ssh_connection():
    """Test SSH connection to Supercomputing Internet"""
    print("=" * 60)
    print("Testing SSH connection to Supercomputing Internet...")
    print("=" * 60)
    
    username = os.environ.get("SUPERCOMPUTING_USERNAME", "")
    if not username:
        print("⚠️  SUPERCOMPUTING_USERNAME not set in .env")
        print("Please configure your Supercomputing Internet credentials first")
        return False
    
    result = test_ssh_connection()
    print("\nResult:")
    print(result)
    
    if "✅" in result:
        print("\n✅ SSH connection test PASSED")
        return True
    else:
        print("\n❌ SSH connection test FAILED")
        print("Check your SSH key and credentials in .env")
        return False


def test_list_partitions():
    """Test listing available partitions"""
    print("\n" + "=" * 60)
    print("Listing available partitions...")
    print("=" * 60)
    
    result = list_available_partitions()
    print("\nResult:")
    print(result)
    
    if "Error" not in result:
        print("\n✅ Partition listing PASSED")
        return True
    else:
        print("\n❌ Partition listing FAILED")
        return False


def main():
    """Run all tests"""
    print("\nGlassCrewAgent VASP Integration Tests\n")
    
    # First test SSH connection
    ssh_ok = test_ssh_connection()
    
    if ssh_ok:
        # If connection works, list partitions
        partition_ok = test_list_partitions()
    else:
        partition_ok = False
        print("\nSkipping partition test because SSH failed")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"SSH connection: {'✅ PASS' if ssh_ok else '❌ FAIL'}")
    print(f"List partitions: {'✅ PASS' if partition_ok else '❌ FAIL'}")
    print("\n")
    
    if ssh_ok:
        print("✅ VASP integration is properly configured!")
        print("Your CrewAI agent can now submit VASP jobs to Supercomputing Internet")
        return 0
    else:
        print("⚠️  Please configure your Supercomputing Internet credentials in .env:")
        print("  - SUPERCOMPUTING_HOST: login.scnet.cn (default)")
        print("  - SUPERCOMPUTING_USERNAME: your username")
        print("  - SUPERCOMPUTING_PRIVATE_KEY_PATH: path to your SSH private key")
        print("\nAfter configuring, run this test again")
        return 1


if __name__ == "__main__":
    sys.exit(main())