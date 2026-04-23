#!/usr/bin/env python
"""
Test script to verify all VASP plotting tools work correctly.
Uses the sample calculation output files provided.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import all plotting tools
from src.GlassCrewAgent.tools.vasp_tools import (
    plot_energy_convergence,
    plot_electronic_convergence,
    plot_force_stress_convergence,
    plot_density_of_states,
    plot_full_dos,
    plot_orbital_pdos,
    plot_band_structure_projected,
    plot_band_dos_combined,
    plot_crystal_structure,
    generate_html_plot_report,
    plot_vasp_summary_plots
)

# Configuration - use your sample calculation
VASP_OUTPUT_DIR = "src/GlassCrewAgent/data/vasp_calculations/job_20260423_103607/output"
JOB_ID = 112140877

def test_function(name, func, *args, **kwargs):
    """Helper to test a single plotting function"""
    print(f"\n{'='*60}")
    print(f"🧪 Testing: {name}")
    print('='*60)
    try:
        result = func.func(*args, **kwargs) if hasattr(func, 'func') else func(*args, **kwargs)
        if "Successfully" in result or "✅" in result:
            print(f"✅ PASSED: {name}")
            print(f"   Result: {result.split(chr(10))[0]}")
            return True
        else:
            print(f"⚠️  PARTIAL: {name}")
            print(f"   Message: {result}")
            return False
    except Exception as e:
        print(f"❌ FAILED: {name}")
        print(f"   Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("🔬 Starting VASP Plotting Tool Tests")
    print(f"📁 Using output directory: {VASP_OUTPUT_DIR}")
    print(f"🆔 Job ID: {JOB_ID}")

    # Check input files exist first
    required_files = ["OSZICAR", "OUTCAR", "vasprun.xml", "CONTCAR", "PROCAR"]
    print("\n📋 Checking required input files:")
    for f in required_files:
        path = os.path.join(VASP_OUTPUT_DIR, f)
        status = "✅" if os.path.exists(path) else "❌"
        print(f"   {status} {f}")

    results = {}

    # 1. Energy convergence
    results["Energy Convergence"] = test_function(
        "Energy Convergence Plot",
        plot_energy_convergence,
        os.path.join(VASP_OUTPUT_DIR, "OSZICAR"),
        os.path.join(VASP_OUTPUT_DIR, "test_energy_convergence.png")
    )

    # 2. Electronic convergence
    results["Electronic Convergence"] = test_function(
        "Electronic Convergence Plot",
        plot_electronic_convergence,
        os.path.join(VASP_OUTPUT_DIR, "OSZICAR"),
        os.path.join(VASP_OUTPUT_DIR, "test_electronic_convergence.png")
    )

    # 3. Force & stress convergence
    results["Force Stress Convergence"] = test_function(
        "Force & Stress Convergence Plot",
        plot_force_stress_convergence,
        os.path.join(VASP_OUTPUT_DIR, "OUTCAR"),
        os.path.join(VASP_OUTPUT_DIR, "test_force_stress.png")
    )

    # 4. Total DOS
    results["Total DOS"] = test_function(
        "Total Density of States Plot",
        plot_density_of_states,
        os.path.join(VASP_OUTPUT_DIR, "vasprun.xml"),
        os.path.join(VASP_OUTPUT_DIR, "test_total_dos.png")
    )

    # 5. Elemental PDOS
    results["Elemental PDOS"] = test_function(
        "Elemental Partial DOS Plot",
        plot_full_dos,
        os.path.join(VASP_OUTPUT_DIR, "vasprun.xml"),
        os.path.join(VASP_OUTPUT_DIR, "test_elemental_pdos.png")
    )

    # 6. Orbital PDOS
    results["Orbital PDOS"] = test_function(
        "Orbital-Resolved PDOS Plot",
        plot_orbital_pdos,
        os.path.join(VASP_OUTPUT_DIR, "vasprun.xml"),
        os.path.join(VASP_OUTPUT_DIR, "test_orbital_pdos.png")
    )

    # 7. Band structure
    results["Band Structure"] = test_function(
        "Band Structure Plot",
        plot_band_structure_projected,
        os.path.join(VASP_OUTPUT_DIR, "vasprun.xml"),
        os.path.join(VASP_OUTPUT_DIR, "test_band_structure.png")
    )

    # 8. Combined Band + DOS (publication quality!)
    results["Band DOS Combined"] = test_function(
        "Combined Band+DOS Plot",
        plot_band_dos_combined,
        os.path.join(VASP_OUTPUT_DIR, "vasprun.xml"),
        os.path.join(VASP_OUTPUT_DIR, "test_band_dos_combined.png")
    )

    # 9. Crystal structure
    results["Crystal Structure"] = test_function(
        "Crystal Structure 3D Plot",
        plot_crystal_structure,
        os.path.join(VASP_OUTPUT_DIR, "CONTCAR"),
        os.path.join(VASP_OUTPUT_DIR, "test_crystal_structure.png")
    )

    # 10. HTML Report
    results["HTML Report"] = test_function(
        "HTML Plot Report",
        generate_html_plot_report,
        VASP_OUTPUT_DIR,
        JOB_ID
    )

    # Final summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    print("\nDetailed results:")
    for name, success in results.items():
        status = "✅" if success else "❌"
        print(f"   {status} {name}")

    print("\n" + "="*60)
    if passed == total:
        print("🎉 ALL TESTS PASSED! Your VASP plotting tools are ready!")
    else:
        print(f"⚠️  Some tests failed. Check the errors above.")
    print("="*60)

    # Now run the FULL summary plot generator (creates everything at once)
    print("\n\n🎨 Running FULL summary plot generator (creates all plots + HTML report):")
    print("-"*60)
    try:
        result = plot_vasp_summary_plots.func(VASP_OUTPUT_DIR, JOB_ID)
        print(result)
        print("\n✅ Full summary completed! Check output/vasp_plots/job_112140877/")
    except Exception as e:
        print(f"❌ Full summary failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
