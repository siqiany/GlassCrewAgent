from src.GlassCrewAgent.tools.generalCommon import download_papers_from_arxiv_single, download_papers_from_arxiv, search_arxiv_papers_single, search_arxiv_papers, list_downloaded_pdfs, read_local_pdf, read_all_downloaded_pdfs
from src.GlassCrewAgent.tools.MPtools import (
    get_structure_info,
    calculate_density,
    calculate_symmetry,
    get_band_gap_by_formula,
    get_band_gap_by_material_id,
    get_dielectric_by_material_id,
    get_volume_by_formula,
    get_density_by_formula,
    search_materials_containing_elements
)
from src.GlassCrewAgent.tools.VAE_tools import generate_glass_composition
from src.GlassCrewAgent.tools.qdrant_search_tool import search_papers_in_qdrant
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
    get_simulation_output_directory
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
#     run_complete_vasp_calculation_from_mp
# )

__all__ = [
    "download_papers_from_arxiv_single", 
    "download_papers_from_arxiv",
    "search_arxiv_papers_single",
    "search_arxiv_papers",
    "list_downloaded_pdfs",
    "read_local_pdf",
    "read_all_downloaded_pdfs",
    "get_structure_info",
    "calculate_density",
    "calculate_symmetry",
    "get_band_gap_by_formula",
    "get_band_gap_by_material_id",
    "get_dielectric_by_material_id",
    "get_volume_by_formula",
    "get_density_by_formula",
    "search_materials_containing_elements",
    "generate_glass_composition",
    "search_papers_in_qdrant",
    "create_simulation_cell",
    "add_block_geometry",
    "add_cylinder_geometry",
    "add_sphere_geometry",
    "set_dispersive_material_lorentzian",
    "set_dispersive_material_from_n",
    "add_continuous_wave_source",
    "add_gaussian_pulse_source",
    "initialize_simulation",
    "run_simulation_until_time",
    "add_flux_monitor",
    "calculate_transmittance_reflectance",
    "extract_electric_field_profile",
    "find_resonant_frequencies",
    "save_simulation_to_hdf5",
    "clear_current_simulation",
    "get_simulation_output_directory"
#     VASP exports removed for temporary branch
#     "test_ssh_connection",
#     "list_available_partitions",
#     "get_structure_from_mp_by_id",
#     "read_poscar_from_file",
#     "generate_vasp_input_from_structure",
#     "generate_slurm_script",
#     "submit_vasp_job",
#     "check_job_status",
#     "cancel_job",
#     "download_vasp_results",
#     "parse_vasp_output",
#     "run_complete_vasp_calculation_from_mp"
]

