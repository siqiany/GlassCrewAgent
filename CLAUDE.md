# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

GlassCrewAgent is a CrewAI-based multi-agent system for automated glass materials research and design. It uses specialized AI agents to collaborate on tasks including literature search, materials property querying, glass composition generation, FDTD electromagnetic simulation, DFT calculations with VASP, and result validation.

## Project Structure

```
GlassCrewAgent/
├── app.py                    # Flask web UI with SSE real-time updates
├── setup.py                  # Package configuration
├── .env                      # Environment variables (API keys, configuration)
├── templates/
│   └── index.html            # Web UI frontend
├── src/GlassCrewAgent/
│   ├── crew.py              # Main Crew definition and agent setup
│   ├── main.py              # CLI entry point
│   ├── config/
│   │   ├── agents.yaml      # Agent roles, goals, backstories
│   │   └── tasks.yaml       # Task definitions and workflow
│   └── tools/               # Specialized tooling for each capability
│       ├── MPtools.py       # Materials Project API integration
│       ├── VAE_tools.py     # CVAE-based glass composition generation
│       ├── meep_tools.py    # FDTD simulation with Meep
│       ├── vasp_tools.py    # VASP entry point (only exports 6 high-level tools)
│       ├── vasp_platform.py # VASP platform layer (SSH/API, file transfer, jobs)
│       ├── vasp_simulation.py # VASP simulation layer (structure, input generation, workflows)
│       ├── vasp_analysis.py # VASP analysis layer (parsing, plotting, reports)
│       ├── qdrant_search_tool.py  # Semantic search on local paper corpus
│       └── generalCommon.py # arXiv search and PDF reading
├── tests/                    # Test files for each tool module
├── output/                   # Generated reports and simulation outputs
└── data/                     # Data files (VAE model, Qdrant DB)
```

## Agents

1. **searcher** - Searches arXiv papers and local Qdrant vector knowledge base
2. **mp_agent** - Queries material properties from Materials Project API
3. **composition_generator** - Generates glass compositions with target optical properties using a CVAE model
4. **fdtd_simulation_agent** - Runs FDTD electromagnetic simulations with Meep
5. **reviewer** - Validates glass compositions and simulation results
6. **manager** - Coordinates the multi-agent workflow following the manager pattern
7. **vasp_calculation_expert** - Automates VASP DFT calculations on remote supercomputing clusters via SSH

## Commands

### Activate Environment
This project uses a conda virtual environment named `GlassCrewAgent`:
```bash
conda activate GlassCrewAgent
```

**Always use conda run for one-off commands**:
```bash
conda run -n GlassCrewAgent python script.py
```

### Install Dependencies
```bash
pip install -e .
```

### Run Web UI
```bash
python app.py
```
Access at http://localhost:5000

### Run CLI Example
```bash
python src/GlassCrewAgent/main.py
```

### Run Tests
```bash
# Run a specific test file
python -m pytest tests/test_MPtools.py -v
python -m pytest tests/test_meep_tools.py -v
python -m pytest tests/test_VAE_tools.py -v
python tests/test_vasp_end_to_end.py [material_id]     # Full end-to-end VASP workflow
python tests/test_vasp_upload_existing.py            # Test upload/submission only

# Run all tests
python -m pytest tests/ -v
```

## Environment Configuration

Required environment variables (in `.env`):
- `OPENAI_API_BASE`, `OPENAI_API_KEY`, `MODEL_NAME` - LLM configuration (supports DeepSeek, Qwen)
- `MP_KEY` - Materials Project API key
- `EMBEDDING_NAME`, `EMBEDDING_API_BASE`, `EMBEDDING_API_KEY` - Embedding model for Qdrant
- `SUPERCOMPUTING_HOST`, `SUPERCOMPUTING_USERNAME`, `SUPERCOMPUTING_PRIVATE_KEY_PATH` - SSH for VASP
- `VASP_REMOTE_DIR`, `VASP_MODULE_NAME` - VASP remote configuration

## Key Architecture Notes

- Built on **CrewAI** framework with sequential process
- Uses YAML configuration for agent and task definitions
- All tools are custom implementations wrapped as CrewAI tools
- The `GlassCrew` class in `crew.py` uses the CrewBase decorator pattern
- Web UI uses Flask with Server-Sent Events (SSE) for real-time progress streaming
- Uses **CrewAI step_callback** to stream tool-level execution details to the UI
- Results are automatically saved to `output/` directory with timestamps
- The manager agent follows a predefined iterative workflow and must validate results before completion

## Web UI Features

- **Two-tab interface**:
  - *📋 Running Log* - Real-time terminal-style scrolling log showing: which agent is running, which tool was called, tool input/output
  - *📝 Result View* - Full Markdown rendering of the final report with proper styling for headings, code blocks, tables
- Automatic switching to result view when execution completes
- Download button for exporting the final Markdown report
- Dark theme with gradient background matching the project style

## Workflow for Inverse Glass Design

```
Literature Search (searcher) → Material Properties (mp_agent) →
Composition Generation (composition_generator) → FDTD Simulation (fdtd_simulation_agent) →
Validation (reviewer) → [Iterate if needed] → Final Report (manager)
```

## Output

All final reports are saved as Markdown in:
- `output/final_glass_report_{timestamp}.md` - Timestamped version
- `output/final_glass_report.md` - Latest version

Simulation outputs are stored in `output/meep_simulations/`.

## Development Guidelines

- **Tool Pattern**: All custom tools use the CrewAI `@tool("Tool Name")` decorator pattern. When adding new tools:
  - Define in `src/GlassCrewAgent/tools/` module
  - Import all new tools in `src/GlassCrewAgent/crew.py`
  - Add new tools to the `tools` list of the appropriate agent(s)
  - Output files must use absolute paths resolved from project root (not relative paths)

- **Meep FDTD Simulation Notes**:
  - For transmittance calculation: place incident monitor *before* the structure, transmitted monitor *after* the structure
  - For 2D/3D simulations: `plane_size_y` (and `plane_size_z` for 3D) must be explicitly provided and > 0
  - Lorentzian dispersion model requires full complex sigma (do not extract `.real`), preserves loss information
  - Get frequency points from `mp.get_flux_freqs()`, do not manually create with `linspace` when flux data is already available
  - Validate geometry objects are within simulation cell boundaries before adding

- **VASP DFT Calculation Notes (scnet.cn supercomputing)**:
  - **Four-Layer Architecture**: VASP tools have been refactored into 4 modules for better maintainability and clean API:
    - `vasp_platform.py` - Platform layer: SSH/API connectivity, file transfer, job submission/monitoring
    - `vasp_simulation.py` - Simulation layer: Structure retrieval, input file generation, end-to-end workflows
    - `vasp_analysis.py` - Analysis layer: Output parsing, 9+ plot types (DOS, band structure, convergence), HTML reports
    - `vasp_tools.py` - **Entry layer (100 lines)**: Clean facade exposing ONLY 6 high-level tools to agents
  - **Tool Simplification**: VASP agent tools reduced from 18+ granular tools to 6 high-level workflow tools:
    1. `test_ssh_connection` - Pre-check: Test SSH/API connectivity
    2. `list_available_partitions` - Pre-check: List available Slurm partitions
    3. `run_complete_vasp_calculation_from_mp` - One-click: Structure → Submit → Results
    4. `run_band_gap_calculation_from_mp` - One-click: Relaxation → SCF → Band structure
    5. `parse_vasp_output` - Post-process: Parse OUTCAR file
    6. `plot_vasp_summary_plots` - Post-process: Generate all summary plots + HTML report
  - **@tool Call Pattern**: Inside high-level workflow functions, NEVER call `@tool` decorated functions directly, use `.func()`:
    ```python
    # ❌ WRONG: Direct call fails (function is wrapped as Tool object)
    result = get_structure_from_mp_by_id(material_id)
    
    # ✅ CORRECT: Call the underlying function
    result = get_structure_from_mp_by_id.func(material_id)
    
    # ✅ OR: Use helper function (defined in vasp_simulation.py)
    result = _call_tool(get_structure_from_mp_by_id, material_id)
    ```
  - **Accurate Band Gap Calculation**: Use `run_band_gap_calculation_from_mp(material_id)` for proper band gap:
    - Step 1: Structure relaxation (geometry optimization)
    - Step 2: Static SCF calculation (generates CHGCAR charge density)
    - Step 3: Non-SCF band structure calculation on high-symmetry k-path
    - Returns numerical band gap value, VBM/CBM, and material classification
    - ❌ Do NOT use single-step static calculation for band gap - it won't give accurate results!
  - **Structured Output Parsing**: `_parse_vasp_output_structured(outcar_path)` returns dictionary with:
    - `band_gap`, `final_energy`, `fermi_level`, `max_force`, `energy_per_atom`, etc.
    - Use this instead of string parsing when you need numerical values for decision making
  - **Band Structure KPOINTS**: For non-SCF band structure, ALWAYS use `Kpoints.automatic_linemode(divisions=20, ibz=kpath)` not explicit Reciprocal k-points.
    - VASP 5.4 reads k-points with fixed-width `(3F20.16)` — float64 scientific notation (24 chars) exceeds 20-char field, causing "Error reading KPOINTS file"
    - Example: `kpath = HighSymmKpath(structure); band_kpoints = Kpoints.automatic_linemode(divisions=20, ibz=kpath)`
  - **Band Gap Retrieval**: Most reliable source is static SCF `vasprun.xml` via `Vasprun.get_band_structure().get_band_gap()['energy']`
    - Modern pymatgen OUTCAR no longer has `outcar.bandgap` or `outcar.bands` — do NOT rely on these attributes
    - Non-SCF band structure EIGENVAL has smeared Fermi level (ISMEAR=0), making gap detection unreliable
  - **Eigenval Import**: `from pymatgen.io.vasp.outputs import Eigenval` (moved from `pymatgen.io.vasp` in newer versions)
  - **EIGENVAL Array Shape**: eigenvalues are `(nkpts, nbands, 2)` — last dim is [real, imag]; use `[:,:,0]` for real part
  - Two connection modes available: select via `VASP_CONNECTION_MODE` in .env:
    - `ssh`: Direct SSH/SFTP connection (traditional method, keep as fallback)
    - `api`: Supercomputing Internet official REST API (recommended, better integration)
  - API mode requires AK/SK authentication: `SCNET_API_USER`, `SCNET_API_ACCESS_KEY`, `SCNET_API_SECRET_KEY`
  - SFTP cannot resolve `~` home directory - always call `realpath {remote_dir}` to get absolute paths before uploading
  - After loading VASP module, must source `env.sh` script to correctly set Intel MKL libraries (module load alone isn't sufficient)
  - Strip `vasp-` prefix from module name to get correct directory path for `env.sh`
  - Do NOT manually load `intel/2017` module - `env.sh` already handles Intel environment setup
  - `PMG_VASP_PSP_DIR` must point to parent directory containing POTCAR pseudopotentials (not the potpaw subdirectory itself)
  - Modern pymatgen Outcar API changed - use fallbacks when accessing `bandgap`, `forces`, `nionic_steps` attributes
  - scnet.cn user home directory is `/public/home/{username}/` not `/home/{username}/`
  - **Circular Import Note**: `__init__.py` imports can cause circular import errors during refactoring

- **Testing**: After modifying tools, always run the corresponding test file: `python -m pytest tests/test_<module_name>.py -v`
