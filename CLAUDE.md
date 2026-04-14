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
- Results are automatically saved to `output/` directory with timestamps
- The manager agent follows a predefined iterative workflow and must validate results before completion

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
