"""
Test single FDTD simulation agent - only run the fdtd_simulation_agent alone
This tests the fixed workflow order after the bug fix:
initialize_simulation → add_flux_monitor (fixed order)

Test case: Candidate #5 glass tellurite waveguide
Composition: 58TeO2-18Bi2O3-10PbO-8GeO2-4ZnO-2BaO (mol%)
Refractive index: n = 2.385
Wavelength: 589.3 nm (sodium d-line)
Structure: 1 μm thick glass slab (planar waveguide) surrounded by air
"""

import os
import sys
import traceback
from datetime import datetime
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM
from crewai.project import CrewBase, agent, task, crew

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.GlassCrewAgent.tools.meep_tools import (
    create_simulation_cell,
    add_block_geometry,
    add_cylinder_geometry,
    add_sphere_geometry,
    set_dispersive_material_lorentzian,
    set_dispersive_material_from_n,
    add_continuous_wave_source,
    add_gaussian_pulse_source,
    initialize_simulation,
    run_simulation_until_time,
    add_flux_monitor,
    calculate_transmittance_reflectance,
    extract_electric_field_profile,
    find_resonant_frequencies,
    save_simulation_to_hdf5,
    clear_current_simulation,
    get_simulation_output_directory,
)

load_dotenv()

# === LLM Configuration ===
def get_llm():
    """Initialize LLM based on environment configuration."""
    model_name = os.environ.get("MODEL_NAME", "deepseek-chat")
    api_base = os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    
    return LLM(
        model=model_name,
        base_url=api_base,
        api_key=api_key
    )

llm = get_llm()

@CrewBase
class SingleFDTDTestCrew:
    """Single FDTD Simulation Agent test crew"""
    
    agents_config_path = os.path.join(os.path.dirname(__file__), "..", "src", "GlassCrewAgent", "config", "agents.yaml")
    tasks_config_path = os.path.join(os.path.dirname(__file__), "..", "src", "GlassCrewAgent", "config", "tasks.yaml")
    
    def __init__(self):
        pass
    
    @agent
    def fdtd_simulation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['fdtd_simulation_agent'],
            llm=llm,
            tools=[
                create_simulation_cell,
                add_block_geometry,
                add_cylinder_geometry,
                add_sphere_geometry,
                set_dispersive_material_lorentzian,
                set_dispersive_material_from_n,
                add_continuous_wave_source,
                add_gaussian_pulse_source,
                initialize_simulation,
                run_simulation_until_time,
                add_flux_monitor,
                calculate_transmittance_reflectance,
                extract_electric_field_profile,
                find_resonant_frequencies,
                save_simulation_to_hdf5,
                clear_current_simulation,
                get_simulation_output_directory
            ]
        )
    
    @task
    def fdtd_test_task(self) -> Task:
        # Custom task for this specific test
        task_config = {
            "description": """
Simulate a planar waveguide structure using the optical properties of Candidate #5 glass composition:
- Glass composition: 58TeO2-18Bi2O3-10PbO-8GeO2-4ZnO-2BaO (mol%)
- Predicted refractive index: nd ~ 2.36-2.41, use 2.385 as average
- Simulation wavelength: 589.3 nm (sodium d-line)
- Structure: simple planar waveguide - glass slab of thickness 1 μm surrounded by air (n=1)
- Simulation cell: 2D, 10 μm × 6 μm with 1.0 μm PML on all sides
- Resolution: 20 pixels/μm

You need to:
1. Start with clear_current_simulation to get a clean slate
2. Follow the CORRECT simulation workflow step-by-step from your configuration
3. Calculate transmittance at 589.3 nm
4. Get field profiles
5. Verify optical confinement
6. Check if optical performance is consistent with predicted refractive index

⚠️ **CRITICAL**: Follow the workflow order exactly:
   1. clear_current_simulation
   2. create_simulation_cell
   3. add_block_geometry (add the glass slab with ε = n² = 2.385² = 5.688)
   4. add_gaussian_pulse_source (center frequency = 1/0.5893 ≈ 1.697, width 0.5)
   5. initialize_simulation (resolution 20, default ε = 1.0)
   6. **ONLY AFTER INITIALIZATION** add your flux monitors (incident at x=-2.0, transmitted at x=2.0)
   7. run_simulation_until_time (run until ~100)
   8. calculate_transmittance_reflectance and extract results

**REMINDER**: add_flux_monitor must be called AFTER initialize_simulation! This was fixed after a bug.

Provide the final summary with numerical results.
            """,
            "expected_output": """
Complete FDTD simulation results including:
- Simulation parameters summary
- Transmittance at 589.3 nm
- Field profile and confinement analysis
- Conclusion on optical performance consistency with predicted n=2.385
"""
        }
        return Task(
            config=task_config
        )
    
    @crew
    def crew(self) -> Crew:
        """Creates the test crew with only FDTD simulation agent"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )

def main():
    print("=" * 80)
    print("Testing single FDTD Simulation Agent (fixed workflow order)")
    print("Test case: 1μm tellurite glass planar waveguide (n=2.385 @ 589.3nm)")
    print("=" * 80)
    print()
    
    try:
        # Create test crew with single agent
        test_crew = SingleFDTDTestCrew()
        crew = test_crew.crew()
        
        print("Starting single-agent FDTD simulation test...")
        print()
        
        # Run the test
        result = crew.kickoff()
        final_output = result.raw
        
        print()
        print("=" * 80)
        print("TEST COMPLETE")
        print("=" * 80)
        print()
        print("Final Result:")
        print(final_output)
        print()
        
        # Save result to file
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file_path = os.path.join(output_dir, f"fdtd_single_agent_test_{timestamp}.md")
        
        with open(output_file_path, 'w', encoding='utf-8') as f:
            f.write(str(final_output))
            f.write("\n\n---\n")
            f.write(f"Generated on: {datetime.now().isoformat()}\n")
            f.write("Test: single FDTD agent test with fixed workflow order\n")
            f.write("Test case: Candidate #5 tellurite glass 1μm planar waveguide\n")
        
        print(f"\n✅ Test result saved to: {output_file_path}")
        print(f"   Simulation data in: output/meep_simulations/\n")
        
        return {
            "success": True,
            "result": str(final_output),
            "output_file": output_file_path
        }
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"\n❌ Test execution error: {e}")
        print(error_trace)
        
        return {
            "success": False,
            "error": str(e),
            "traceback": error_trace
        }

if __name__ == "__main__":
    main()
