"""
VASP First-Principles Calculation Tools (Backward Compatibility Entry Point)
=============================================================================

⚠️  NOTE: This module has been refactored into three separate modules for
better maintainability:

   📦 vasp_platform.py     - 超算平台交互 (SSH/API, 文件传输, 任务管理)
   📦 vasp_simulation.py   - VASP模拟设置 (结构获取, 输入文件生成)
   📦 vasp_analysis.py     - 结果分析与绘图 (解析输出, 各种绘图)

This file re-exports all the tools from the three modules to maintain
backward compatibility. Existing code doesn't need to change anything.

Key Features:
- Retrieve crystal structures from Materials Project
- Automatically generate all VASP input files (POSCAR, INCAR, KPOINTS, POTCAR)
- SFTP upload to Supercomputing Internet
- Submit jobs via Slurm sbatch
- Monitor job status with squeue
- Download results upon completion
- Parse output and extract key properties (energy, band gap, forces, etc.)
- 9+ high-quality plots including DOS, band structure, convergence, etc.
- HTML report generation

Required environment variables:
- SUPERCOMPUTING_HOST: SSH host for Supercomputing Internet (default: login.scnet.cn)
- SUPERCOMPUTING_PORT: SSH port (default: 65023 for Supercomputing Internet)
- SUPERCOMPUTING_USERNAME: Your username
- SUPERCOMPUTING_PRIVATE_KEY_PATH: Path to your SSH private key
- PMG_VASP_PSP_DIR: Path to your VASP POTCAR (pseudopotential) directory
- VASP_MODULE_NAME: VASP module name to load (default: vasp-6.4.2-intelmpi2017_ioptcell)
- VASP_JOBS_REMOTE_DIR: Base remote directory for all VASP jobs (default: ~/vasp_jobs)
- SCNET_API_USER, SCNET_API_ACCESS_KEY, SCNET_API_SECRET_KEY: For API mode

Required dependencies:
- paramiko: SSH/SFTP connectivity
- pymatgen: Crystal structure processing and VASP input generation
- matplotlib: For plotting
- mp-api: For Materials Project access
"""

# =============================================================================
# Re-export from all three modules (maintains backward compatibility)
# =============================================================================

# 1. Platform module: only export user-facing high-level tools
from src.GlassCrewAgent.tools.vasp_platform import (
    # Pre-check tools (required before VASP runs)
    test_ssh_connection,
    list_available_partitions,
)

# 2. Simulation module: only export end-to-end workflow tools
from src.GlassCrewAgent.tools.vasp_simulation import (
    # High-level end-to-end workflows
    run_complete_vasp_calculation_from_mp,
    run_band_gap_calculation_from_mp,
)

# 3. Analysis module: only export summary tools
from src.GlassCrewAgent.tools.vasp_analysis import (
    # Output parsing
    parse_vasp_output,
    # One-click comprehensive plotting
    plot_vasp_summary_plots,
)

# =============================================================================
# Export list (for `from vasp_tools import *` and for __all__ checks)
# =============================================================================

__all__ = [
    # ===== 前置检查工具 =====
    'test_ssh_connection',       # 测试SSH连接
    'list_available_partitions', # 查看可用分区/队列

    # ===== 核心高级工作流 =====
    'run_complete_vasp_calculation_from_mp',  # 一键完成完整计算
    'run_band_gap_calculation_from_mp',       # 一键完成带隙计算

    # ===== 结果处理 =====
    'parse_vasp_output',         # 解析VASP输出
    'plot_vasp_summary_plots',   # 一键生成所有汇总图
]

# =============================================================================
# Module information (for introspection)
# =============================================================================

__module_info__ = {
    'refactored': True,
    'refactored_date': '2026-04-23',
    'modules': {
        'vasp_platform': 'Platform interaction (SSH/API, file transfer, jobs)',
        'vasp_simulation': 'Simulation setup (structure, input generation)',
        'vasp_analysis': 'Result analysis and plotting (parsing, visualization)'
    },
    'backward_compatible': True,
}
