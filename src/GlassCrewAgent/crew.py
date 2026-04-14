from crewai import Agent, Task, Crew, Process, LLM
from crewai.project import CrewBase, agent, crew, task
from typing import Any, Dict, Optional, List
from dotenv import load_dotenv
import os
import traceback
from datetime import datetime, timezone
from crewai.agents.agent_builder.base_agent import BaseAgent

load_dotenv()

from src.GlassCrewAgent.tools.qdrant_search_tool import search_papers_in_qdrant

from src.GlassCrewAgent.tools.VAE_tools import generate_glass_composition

from src.GlassCrewAgent.tools.MPtools import (
    get_structure_info,
    calculate_density,
    calculate_symmetry,
    get_band_gap_by_formula,
    get_band_gap_by_material_id,
    get_dielectric_by_material_id,
    get_volume_by_formula,
    get_density_by_formula,
    search_materials_containing_elements,
)

from src.GlassCrewAgent.tools.generalCommon import (
    download_papers_from_arxiv_single,
    download_papers_from_arxiv,
    search_arxiv_papers_single,
    search_arxiv_papers,
    list_downloaded_pdfs,
    read_all_downloaded_pdfs,
    read_local_pdf
)

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

# VASP tools removed for temporary branch
# from src.GlassCrewAgent.tools.vasp_tools import (
#     test_ssh_connection,
#     list_available_partitions,
#     get_structure_from_mp_by_id,
#     read_poscar_from_file,
#     generate_vasp_input_from_structure,
#     generate_slurm_script,
#     submit_vasp_job,
#     check_job_status,
#     cancel_job,
#     download_vasp_results,
#     parse_vasp_output,
#     run_complete_vasp_calculation_from_mp,
# )


# === LLM Configuration ===
def get_llm():
    """
    Initialize LLM based on environment configuration.
    Supports DeepSeek and Qwen (Alibaba) models.
    """
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
class GlassCrew:
    """Glass Research Crew for comprehensive glass materials research and design"""

    agents_config_path = os.path.join(os.path.dirname(__file__), "config", "agents.yaml")
    tasks_config_path = os.path.join(os.path.dirname(__file__), "config", "tasks.yaml")
    
    def __init__(self):
        # CrewBase will automatically load the configurations
        pass
    
    @agent
    def searcher(self) -> Agent:
        return Agent(
            config=self.agents_config['searcher'],
            llm=llm,
            tools=[
                list_downloaded_pdfs,
                download_papers_from_arxiv_single,
                download_papers_from_arxiv,
                search_arxiv_papers_single,
                search_arxiv_papers,
                search_papers_in_qdrant,
                read_local_pdf,
                read_all_downloaded_pdfs
            ]
        )
    
    @agent
    def mp_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['mp_agent'],
            llm=llm,
            tools=[
                get_structure_info,
                calculate_density,
                calculate_symmetry,
                get_band_gap_by_formula,
                get_band_gap_by_material_id,
                get_dielectric_by_material_id,
                get_volume_by_formula,
                get_density_by_formula,
                search_materials_containing_elements
            ]
        )
    
    @agent
    def composition_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['composition_generator'],
            llm=llm,
            tools=[generate_glass_composition]
        )
    
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
    
    @agent
    def reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['reviewer'],
            llm=llm,
            tools=[]
        )
    
    @agent
    def manager(self) -> Agent:
        return Agent(
            config=self.agents_config['manager'],
            llm=llm,
            tools=[]
        )
    
    # VASP agent removed for temporary branch
    # @agent
    # def vasp_calculation_expert(self) -> Agent:
    #     return Agent(
    #         config=self.agents_config['vasp_calculation_expert'],
    #         llm=llm,
    #         tools=[
    #             test_ssh_connection,
    #             list_available_partitions,
    #             get_structure_from_mp_by_id,
    #             read_poscar_from_file,
    #             generate_vasp_input_from_structure,
    #             generate_slurm_script,
    #             submit_vasp_job,
    #             check_job_status,
    #             cancel_job,
    #             download_vasp_results,
    #             parse_vasp_output,
    #             run_complete_vasp_calculation_from_mp,
    #         ]
    #     )
    
    @task
    def glass_research_task(self) -> Task:
        task_config = self.tasks_config['glass_research_task']
        output_file = task_config.get('output_file', None)
        
        return Task(
            config=task_config,
            output_file=output_file
        )
    
    @crew
    def crew(self) -> Crew:
        """Creates the Glass research crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )


# === Backward Compatibility Wrappers ===
def handle_user_goal(user_input: str) -> Dict[str, Any]:
    """
    Main handler function to process user research requests.
    (Backward compatibility wrapper)
    
    Args:
        user_input: The user's research question about glass materials.
    
    Returns:
        Dict containing:
            - success: bool indicating if execution succeeded
            - result: final output string
            - trace: list of task execution traces
            - token_usage: token usage statistics
    """
    # Create Crew instance
    glass_crew = GlassCrew()
    crew = glass_crew.crew()
    
    try:
        # Execute crew
        result = crew.kickoff(inputs={'user_input': user_input})
        final = result.raw
        
        # Build trace structure
        trace_struct = []
        for task_output in result.tasks_output:
            trace_struct.append({
                "agent": getattr(task_output.agent, "role", None) if hasattr(task_output, "agent") else None,
                "task": task_output.description if hasattr(task_output, 'description') else "未知任务",
                "input": task_output.description if hasattr(task_output, 'description') else "未知任务",
                "result": task_output.raw if hasattr(task_output, 'raw') else (
                    task_output.result if hasattr(task_output, 'result') else "无输出"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": True,
                "error": None
            })
        
        usage = result.token_usage if hasattr(result, 'token_usage') else None
        
        # 保存最终结果到本地 Markdown 文件
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "output")
        os.makedirs(output_dir, exist_ok=True)
        
        # 使用时间戳生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file_path = os.path.join(output_dir, f"final_glass_report_{timestamp}.md")
        
        # 同时也保存一个固定名称的文件用于最新结果
        fixed_output_path = os.path.join(output_dir, "final_glass_report.md")
        
        try:
            # 写入带时间戳的文件
            with open(output_file_path, 'w', encoding='utf-8') as f:
                f.write(str(final))
                f.write("\n\n---\n")
                f.write(f"Generated on: {datetime.now().isoformat()}\n")
                f.write(f"User Query: {user_input}\n")
            
            # 更新固定名称的最新结果文件
            with open(fixed_output_path, 'w', encoding='utf-8') as f:
                f.write(str(final))
                f.write("\n\n---\n")
                f.write(f"Generated on: {datetime.now().isoformat()}\n")
                f.write(f"User Query: {user_input}\n")
            
            print(f"\n✅ Final report saved to:")
            print(f"   - {output_file_path}")
            print(f"   - {fixed_output_path} (latest version)\n")
        except Exception as e:
            print(f"\n⚠️  Warning: Failed to save final report to file: {e}\n")
        
        return {
            "success": True,
            "result": str(final),
            "output_file": output_file_path,
            "latest_output_file": fixed_output_path,
            "trace": trace_struct,
            "token_usage": usage
        }
    
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Crew execution error: {e}")
        print(error_trace)
        
        return {
            "success": False,
            "result": f"Error occurred during execution: {str(e)}",
            "trace": [{
                "agent": None,
                "task": "glass_research_task",
                "input": user_input,
                "result": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": False,
                "error": str(e)
            }],
            "token_usage": None
        }


def get_crew_instance():
    """
    Get a Crew instance for direct usage (backward compatibility).
    """
    glass_crew = GlassCrew()
    return glass_crew.crew()


def kickoff_with_input(user_input: str) -> Any:
    """
    Convenience method to kickoff crew with user input.
    (Backward compatibility wrapper)
    
    Args:
        user_input: The user's research question about glass materials.
    
    Returns:
        Crew execution result.
    """
    crew_instance = get_crew_instance()
    return crew_instance.kickoff(inputs={'user_input': user_input})