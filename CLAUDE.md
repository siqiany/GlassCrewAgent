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
│       ├── vasp_tools.py    # VASP DFT calculations on supercomputing clusters
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

- **Testing**: After modifying tools, always run the corresponding test file: `python -m pytest tests/test_<module_name>.py -v`
