"""
VASP First-Principles Calculation Tools for CrewAI with Supercomputing Internet Integration

This module provides tools for automated VASP calculations on the Supercomputing Internet platform
(https://www.scnet.cn/), integrated with Materials Project for structure retrieval and pymatgen for
structure processing.

Key Features:
- Retrieve crystal structures from Materials Project
- Automatically generate all VASP input files (POSCAR, INCAR, KPOINTS, POTCAR)
- SFTP upload to Supercomputing Internet
- Submit jobs via Slurm sbatch
- Monitor job status with squeue
- Download results upon completion
- Parse output and extract key properties (energy, band gap, forces, etc.)

Required environment variables:
- SUPERCOMPUTING_HOST: SSH host for Supercomputing Internet (default: login.scnet.cn)
- SUPERCOMPUTING_PORT: SSH port (default: 65023 for Supercomputing Internet)
- SUPERCOMPUTING_USERNAME: Your username
- SUPERCOMPUTING_PRIVATE_KEY_PATH: Path to your SSH private key
- PMG_VASP_PSP_DIR: Path to your VASP POTCAR (pseudopotential) directory (required by pymatgen)
- VASP_MODULE_NAME: VASP module name to load (default: vasp-6.4.2-intelmpi2017_ioptcell)
- VASP_JOBS_REMOTE_DIR: Base remote directory for all VASP jobs (default: ~/vasp_jobs) - each job gets its own timestamped subdirectory

Required dependencies:
- paramiko: SSH/SFTP connectivity
- pymatgen: Crystal structure processing and VASP input generation
"""

import os
import time
import hmac
import hashlib
import json
import requests
import paramiko
import re
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from crewai.tools import tool

# Global SSH client singleton
_ssh_client = None
_sftp_client = None

# =============================================================================
# Supercomputing Internet Official API Implementation (AK/SK Authentication)
# =============================================================================
# Global API token cache
_api_token: Optional[str] = None
_api_token_expire_time: Optional[int] = None
_api_hpc_urls: Optional[str] = None
_api_efile_urls: Optional[str] = None
_api_cluster_id: Optional[str] = None
_api_job_manager_id: Optional[str] = None


def _get_api_connection_mode() -> str:
    """Get connection mode from environment: 'ssh' or 'api'"""
    return os.environ.get("VASP_CONNECTION_MODE", "ssh")


def _api_calculate_signature(params: Dict[str, Any], secret_key: str) -> str:
    """
    Calculate HMAC-SHA256 signature for AK/SK authentication per scnet.cn spec.
    Steps:
    1. Sort keys lexicographically
    2. Create JSON string with sorted keys
    3. Calculate HMAC-SHA256 with SK as key, result to lowercase hex
    """
    # Sort keys lexicographically
    sorted_keys = sorted(params.keys())
    sorted_params = {k: params[k] for k in sorted_keys}
    # Create JSON string (no extra spaces)
    message = json.dumps(sorted_params, separators=(',', ':'))
    # Calculate HMAC-SHA256
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def _api_get_token() -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """
    Get or renew access token via AK/SK authentication.
    Returns:
        (token, hpc_urls, efile_urls, error_message)
    """
    global _api_token, _api_token_expire_time, _api_hpc_urls, _api_efile_urls, _api_cluster_id, _api_job_manager_id

    # Check if cached token is still valid (renew if less than 5 minutes left)
    if _api_token is not None and _api_token_expire_time is not None and _api_job_manager_id:
        current_time = int(time.time())
        if _api_token_expire_time - current_time > 300:  # 5 minutes
            return _api_token, _api_hpc_urls, _api_efile_urls, ""

    # Get AK/SK from environment
    user = os.environ.get("SCNET_API_USER", "")
    access_key = os.environ.get("SCNET_API_ACCESS_KEY", "")
    secret_key = os.environ.get("SCNET_API_SECRET_KEY", "")
    orgid = os.environ.get("SCNET_API_ORGID", "")

    if not user or not access_key or not secret_key:
        return None, None, None, "Error: SCNET_API_USER, SCNET_API_ACCESS_KEY, SCNET_API_SECRET_KEY not set in .env"

    # API endpoint
    url = "https://api.scnet.cn/api/user/v3/tokens"

    # Get current timestamp (seconds)
    timestamp = str(int(time.time()))

    # Parameters for signature
    params = {
        "user": user,
        "accessKey": access_key,
        "timestamp": timestamp
    }

    # Add orgid if provided
    if orgid:
        params["orgid"] = orgid

    # Calculate signature
    signature = _api_calculate_signature(params, secret_key)

    # Request headers
    headers = {
        "user": user,
        "accessKey": access_key,
        "signature": signature,
        "timestamp": timestamp
    }

    # Add orgid to headers if provided
    if orgid:
        headers["orgid"] = orgid

    try:
        response = requests.post(url, headers=headers, json={}, timeout=30)
        if response.status_code != 200:
            return None, None, None, f"Authentication failed: status {response.status_code}, response: {response.text[:200]}"
        data = response.json()

        if data.get("code") != "0" and data.get("code") != 0:
            msg = data.get("msg", "Unknown error")
            return None, None, None, f"Authentication failed: {msg} (full response: {str(data)[:200]})"

        # Get first cluster from response
        clusters = data.get("data", [])
        if not clusters:
            return None, None, None, "No clusters found in authentication response"

        # Use the first available cluster
        cluster = clusters[0]
        token = cluster.get("token", "")
        cluster_id = cluster.get("clusterId", "")

        if not token:
            return None, None, None, "No token found in authentication response"

        # Decode token to get expiration time (JWT)
        try:
            # JWT format: header.payload.signature
            payload_b64 = token.split('.')[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding
            import base64
            payload = json.loads(base64.b64decode(payload_b64))
            expire_time = payload.get("expireTime", "")
            if expire_time:
                _api_token_expire_time = int(expire_time)
        except Exception:
            # If we can't parse, assume 24 hours
            _api_token_expire_time = int(time.time()) + 86400

        # Now get cluster info (hpcUrls and efileUrls)
        center_url = "https://www.scnet.cn/ac/openapi/v2/center"
        headers_center = {
            "token": token,
            "Content-Type": "application/json"
        }
        response_center = requests.get(center_url, headers=headers_center, timeout=30)
        if response_center.status_code != 200:
            return None, None, None, f"Get cluster info failed: status {response_center.status_code}, response: {response_center.text[:200]}"
        data_center = response_center.json()

        if data_center.get("code") != "0" and data_center.get("code") != 0:
            msg = data_center.get("msg", "Unknown error")
            return None, None, None, f"Get cluster info failed: {msg}"

        data_info = data_center.get("data", {})
        ingress_urls = data_info.get("ingressUrls", [])
        efile_urls_list = data_info.get("efileUrls", [])
        hpc_urls_list = data_info.get("hpcUrls", [])

        # Get the first enabled URL
        hpc_url = None
        for item in hpc_urls_list:
            if item.get("enable") == "true" or item.get("enable") is True:
                hpc_url = item.get("url", "")
                break

        efile_url = None
        for item in efile_urls_list:
            if item.get("enable") == "true" or item.get("enable") is True:
                efile_url = item.get("url", "")
                break

        if not hpc_url or not efile_url:
            return None, None, None, "No enabled HPC or eFile URLs found"

        # Cache globally
        _api_token = token
        _api_hpc_urls = hpc_url.rstrip('/')
        _api_efile_urls = efile_url.rstrip('/')
        _api_cluster_id = cluster_id

        # Get job manager ID (needed for job submission)
        cluster_url = f"{_api_hpc_urls}/hpc/openapi/v2/cluster"
        headers_cluster = {"token": token}
        response_cluster = requests.get(cluster_url, headers=headers_cluster, timeout=30)
        response_cluster.raise_for_status()
        data_cluster = response_cluster.json()

        if data_cluster.get("code") == "0" or data_cluster.get("code") == 0:
            clusters_data = data_cluster.get("data", [])
            if clusters_data:
                # Take first SLURM cluster
                for cm in clusters_data:
                    if cm.get("JobManagerType") == "SLURM":
                        _api_job_manager_id = str(cm.get("id", ""))
                        break
                if not _api_job_manager_id and clusters_data:
                    _api_job_manager_id = str(clusters_data[0].get("id", ""))

        return _api_token, _api_hpc_urls, _api_efile_urls, ""

    except Exception as e:
        return None, None, None, f"API request error: {str(e)}"


def _api_create_directory(remote_path: str, create_parents: bool = True) -> Tuple[bool, str]:
    """Create remote directory via API"""
    token, _, efile_urls, err = _api_get_token()
    if err:
        return False, err

    url = f"{efile_urls}/openapi/v2/file/mkdir"
    headers = {"token": token}
    params = {
        "path": remote_path,
        "createParents": create_parents
    }

    try:
        response = requests.post(url, headers=headers, params=params, json={}, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == "0" or data.get("code") == 0:
            return True, ""
        else:
            msg = data.get("msg", "Unknown error")
            return False, f"Create directory failed: {msg}"
    except Exception as e:
        return False, f"API error: {str(e)}"


def _api_check_file_exists(remote_path: str) -> Tuple[bool, str]:
    """Check if remote file/directory exists"""
    token, _, efile_urls, err = _api_get_token()
    if err:
        return False, err

    url = f"{efile_urls}/openapi/v2/file/exist"
    headers = {"token": token}
    params = {"path": remote_path}

    try:
        response = requests.post(url, headers=headers, params=params, json={}, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == "0" or data.get("code") == 0:
            exist = data.get("data", {}).get("exist", False)
            return exist, ""
        else:
            msg = data.get("msg", "Unknown error")
            return False, f"Check exist failed: {msg}"
    except Exception as e:
        return False, f"API error: {str(e)}"


def _api_upload_file(local_path: str, remote_path: str, cover: str = "cover") -> Tuple[bool, str]:
    """Upload single file via API (multipart/form-data)"""
    token, _, efile_urls, err = _api_get_token()
    if err:
        return False, err

    url = f"{efile_urls}/openapi/v2/file/upload"

    if not os.path.exists(local_path):
        return False, f"Local file not found: {local_path}"

    try:
        with open(local_path, 'rb') as f:
            files = {'file': (os.path.basename(local_path), f)}
            data = {
                'path': os.path.dirname(remote_path),
                'cover': cover
            }
            headers = {"token": token}
            response = requests.post(url, headers=headers, data=data, files=files, timeout=300)
            response.raise_for_status()
            result = response.json()
            if result.get("code") == "0" or result.get("code") == 0:
                return True, ""
            else:
                msg = result.get("msg", "Unknown error")
                return False, f"Upload failed: {msg}"
    except Exception as e:
        return False, f"Upload error: {str(e)}"


def _api_download_file(remote_path: str, local_path: str) -> Tuple[bool, str]:
    """Download file via API"""
    token, _, efile_urls, err = _api_get_token()
    if err:
        return False, err

    url = f"{efile_urls}/openapi/v2/file/download"
    params = {"path": remote_path}
    headers = {"token": token}

    try:
        response = requests.get(url, headers=headers, params=params, stream=True, timeout=300)
        response.raise_for_status()

        # Create directory if needed
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return True, ""
    except Exception as e:
        return False, f"Download error: {str(e)}"


def _api_list_queues(username: str) -> Tuple[Optional[List[Dict]], str]:
    """List available queues for user"""
    token, hpc_urls, _, err = _api_get_token()
    if err:
        return None, err

    if not _api_job_manager_id:
        return None, "Job manager ID not available"

    url = f"{hpc_urls}/hpc/openapi/v2/queuenames/users/{username}"
    headers = {"token": token}
    params = {"strJobManagerID": _api_job_manager_id}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == "0" or data.get("code") == 0:
            queues = data.get("data", [])
            if not queues:
                return None, "No queues returned from API"
            return queues, ""
        else:
            msg = data.get("msg", "Unknown error")
            full_response = str(data)[:200]
            return None, f"List queues failed: {msg} ({full_response})"
    except Exception as e:
        return None, f"API error: {str(e)}"


def _api_submit_job(
    remote_work_dir: str,
    slurm_path: str,
    queue: str,
    nodes: int,
    ppn: int,
    wall_time: str = "72:00:00",
    job_name: str = "vasp_calculation"
) -> Tuple[Optional[str], str]:
    """
    Submit VASP job via API.
    Returns: (job_id, error_message)
    """
    token, hpc_urls, _, err = _api_get_token()
    if err:
        return None, err

    if not _api_job_manager_id:
        return None, "Job manager ID not available"

    url = f"{hpc_urls}/hpc/openapi/v2/apptemplates/BASIC/BASE/job"
    headers = {
        "token": token,
        "Content-Type": "application/json"
    }

    # API job submission parameters
    payload = {
        "strJobManagerID": _api_job_manager_id,
        "mapAppJobInfo": {
            "GAP_SUBMIT_TYPE": "sched",
            "GAP_APPNAME": "VASP",
            "GAP_JOB_NAME": job_name,
            "GAP_PPN": str(ppn),
            "GAP_NNODE": str(nodes),
            "GAP_WALL_TIME": wall_time,
            "GAP_WORK_DIR": remote_work_dir,
            "GAP_SCHED_FILE": slurm_path,
            "GAP_STD_OUT_FILE": f"{remote_work_dir}/std.out.%j",
            "GAP_STD_ERR_FILE": f"{remote_work_dir}/std.err.%j",
            "GAP_QUEUE": queue,
            "GAP_CLUSTER_ID": _api_cluster_id,
            "advance": False
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            return None, f"Job submission failed: status {response.status_code}, response: {response.text[:300]}"
        data = response.json()
        if data.get("code") == "0" or data.get("code") == 0:
            data_obj = data.get("data", {})
            if isinstance(data_obj, dict):
                job_id = str(data_obj.get("jobid", data_obj.get("jobId", "")))
            else:
                job_id = str(data_obj)
            return job_id, ""
        else:
            msg = data.get("msg", "Unknown error")
            full_data = str(data)[:300]
            return None, f"Job submission failed: {msg} ({full_data})"
    except Exception as e:
        return None, f"API error: {str(e)}"


def _api_get_job_status(job_id: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Get job status via API.
    Returns: (status, job_name, error_message)
    """
    token, hpc_urls, _, err = _api_get_token()
    if err:
        return None, None, err

    url = f"{hpc_urls}/hpc/openapi/v2/jobs/{job_id}"
    headers = {"token": token}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == "0" or data.get("code") == 0:
            job_data = data.get("data", {})
            status = job_data.get("jobStatus", "UNKNOWN")
            job_name = job_data.get("jobName", "")
            # Map API status codes to readable names
            status_map = {
                "statR": "RUNNING",
                "statP": "PENDING",
                "statC": "COMPLETED",
                "statF": "FAILED",
                "statS": "SUSPENDED",
                "statCA": "CANCELLED",
                "statCG": "COMPLETING",
            }
            readable_status = status_map.get(status, status)
            return readable_status, job_name, ""
        else:
            msg = data.get("msg", "Unknown error")
            return None, None, f"Get status failed: {msg}"
    except Exception as e:
        return None, None, f"API error: {str(e)}"


def _api_cancel_job(job_id: str) -> Tuple[bool, str]:
    """Cancel job via API"""
    token, hpc_urls, _, err = _api_get_token()
    if err:
        return False, err

    if not _api_job_manager_id:
        return False, "Job manager ID not available"

    username = os.environ.get("SCNET_API_USER", "") or os.environ.get("SUPERCOMPUTING_USERNAME", "")
    url = f"{hpc_urls}/hpc/openapi/v2/jobs"
    headers = {"token": token}
    params = {
        "jobMethod": "5",  # 5 means delete
        "strJobInfoMap": f"{_api_job_manager_id},{username}:{job_id}:"
    }

    try:
        response = requests.delete(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == "0" or data.get("code") == 0:
            return True, ""
        else:
            msg = data.get("msg", "Unknown error")
            return False, f"Cancel failed: {msg}"
    except Exception as e:
        return False, f"API error: {str(e)}"

# =============================================================================
# End of API Implementation
# =============================================================================


def _get_ssh() -> Tuple[Optional[paramiko.SSHClient], Optional[paramiko.SFTPClient]]:
    """Get or create SSH/SFTP connection using environment configuration"""
    global _ssh_client, _sftp_client

    if _ssh_client is not None:
        try:
            _ssh_client.exec_command("echo 1", timeout=5)
            return _ssh_client, _sftp_client
        except Exception:
            try:
                _sftp_client.close()
                _ssh_client.close()
            except:
                pass
            _ssh_client = None
            _sftp_client = None

    host = os.environ.get("SUPERCOMPUTING_HOST", "login.scnet.cn")
    username = os.environ.get("SUPERCOMPUTING_USERNAME", "")
    port = int(os.environ.get("SUPERCOMPUTING_PORT", "65023"))
    key_path = os.environ.get("SUPERCOMPUTING_PRIVATE_KEY_PATH", os.path.expanduser("~/.ssh/id_rsa"))

    if not username:
        return None, None

    key_path = os.path.expanduser(key_path)
    if not os.path.exists(key_path):
        print(f"Error: SSH private key not found at {key_path}")
        return None, None

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=host,
            username=username,
            key_filename=key_path,
            port=port,
            timeout=30
        )
        sftp = ssh.open_sftp()
        _ssh_client = ssh
        _sftp_client = sftp
        return ssh, sftp
    except Exception as e:
        print(f"SSH connection error: {str(e)}")
        return None, None


def _get_local_job_dir(job_id: Optional[int] = None) -> str:
    """Get or create local directory for VASP calculation"""
    # Always use consistent location: src/data/vasp_calculations
    # This matches the project's data directory organization
    file_abs_path = os.path.abspath(__file__)
    # vasp_tools.py is at src/GlassCrewAgent/tools/ -> go up two levels to src/
    src_dir = os.path.dirname(os.path.dirname(file_abs_path))
    base_dir = os.path.join(src_dir, "data", "vasp_calculations")
    os.makedirs(base_dir, exist_ok=True)

    if job_id:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_dir = os.path.join(base_dir, f"job_{job_id}_{timestamp}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_dir = os.path.join(base_dir, f"job_{timestamp}")

    os.makedirs(job_dir, exist_ok=True)
    os.makedirs(os.path.join(job_dir, "input"), exist_ok=True)
    os.makedirs(os.path.join(job_dir, "output"), exist_ok=True)

    return job_dir


# =============================================================================
# Connection and Information Tools (supports both SSH and API modes)
# =============================================================================

@tool("Test Connection")
def test_connection() -> str:
    """
    Test connection to Supercomputing Internet. Works with both SSH/SFTP mode and official API mode.
    Connection mode is selected by VASP_CONNECTION_MODE environment variable.

    Returns:
        Connection status and basic information
    """
    mode = _get_api_connection_mode()

    if mode == "api":
        # Test API authentication
        token, hpc_urls, efile_urls, err = _api_get_token()
        if err:
            return f"❌ API connection failed: {err}"

        queues, err = _api_list_queues(os.environ.get("SCNET_API_USER", ""))
        if err:
            return f"✅ API authentication successful, but failed to list queues: {err}"

        summary = f"✅ API connection and authentication successful!\n\n"
        summary += f"HPC URL: {hpc_urls}\n"
        summary += f"File URL: {efile_urls}\n"
        summary += f"Cluster ID: {_api_cluster_id}\n"
        summary += f"Job Manager ID: {_api_job_manager_id}\n\n"
        summary += f"Available queues ({len(queues)}):\n"
        for q in queues[:10]:  # Show first 10
            summary += f"  - {q.get('queueName', 'unknown')}: max nodes={q.get('queMaxNodect', '?')}, max cores={q.get('queMaxNcpus', '?')}\n"
        if len(queues) > 10:
            summary += f"  ... and {len(queues) - 10} more\n"
        return summary

    else:  # ssh mode
        ssh, sftp = _get_ssh()
        if ssh is None:
            return "Error: Could not establish SSH connection. Check your environment configuration (SUPERCOMPUTING_HOST, SUPERCOMPUTING_USERNAME, SUPERCOMPUTING_PRIVATE_KEY_PATH)."

        try:
            stdin, stdout, stderr = ssh.exec_command("hostname && whoami && sinfo -s")
            exit_code = stdout.channel.recv_exit_status()
            result = stdout.read().decode()
            error = stderr.read().decode()

            if exit_code != 0:
                return f"Connected but command failed:\nExit code: {exit_code}\nError: {error}"

            return f"✅ SSH connection successful!\n\nOutput:\n{result}"
        except Exception as e:
            return f"Error testing connection: {str(e)}"


# Keep the original name for backward compatibility
@tool("Test SSH Connection")
def test_ssh_connection() -> str:
    """
    Test connection to Supercomputing Internet (backward compatibility alias).
    """
    # Access the underlying function via .func attribute (CrewAI Tool convention)
    # This avoids "Tool object is not callable" error when one tool calls another
    if hasattr(test_connection, 'func'):
        return test_connection.func()
    # Fallback for different versions of CrewAI
    try:
        return test_connection()
    except TypeError:
        # If direct call fails, use the internal function
        mode = _get_api_connection_mode()
        if mode == "api":
            token, hpc_urls, efile_urls, err = _api_get_token()
            if err:
                return f"❌ API connection failed: {err}"
            queues, err = _api_list_queues(os.environ.get("SCNET_API_USER", ""))
            if err:
                return f"✅ API authentication successful, but failed to list queues: {err}"
            summary = f"✅ API connection and authentication successful!\n\n"
            summary += f"HPC URL: {hpc_urls}\n"
            summary += f"File URL: {efile_urls}\n"
            summary += f"Cluster ID: {_api_cluster_id}\n"
            summary += f"Job Manager ID: {_api_job_manager_id}\n\n"
            summary += f"Available queues ({len(queues)}):\n"
            for q in queues[:10]:
                summary += f"  - {q.get('queueName', 'unknown')}: max nodes={q.get('queMaxNodect', '?')}, max cores={q.get('queMaxNcpus', '?')}\n"
            if len(queues) > 10:
                summary += f"  ... and {len(queues) - 10} more\n"
            return summary
        else:
            ssh, sftp = _get_ssh()
            if ssh is None:
                return "Error: Could not establish SSH connection. Check your environment configuration."
            try:
                stdin, stdout, stderr = ssh.exec_command("hostname && whoami && sinfo -s")
                exit_code = stdout.channel.recv_exit_status()
                result = stdout.read().decode()
                if exit_code != 0:
                    return f"Connected but command failed:\nExit code: {exit_code}\nError: {stderr.read().decode()}"
                return f"✅ SSH connection successful!\n\nOutput:\n{result}"
            except Exception as e:
                return f"Error testing connection: {str(e)}"


@tool("List Available Partitions")
def list_available_partitions() -> str:
    """
    List all available partitions (queues) on the supercomputing cluster that can be used for VASP jobs.
    Works with both SSH/SFTP mode and official API mode.

    Returns:
        Formatted list of available partitions with their specifications
    """
    mode = _get_api_connection_mode()

    if mode == "api":
        username = os.environ.get("SCNET_API_USER", "") or os.environ.get("SUPERCOMPUTING_USERNAME", "")
        queues, err = _api_list_queues(username)
        if err:
            return f"Error: {err}"

        if not queues:
            return "No queues found"

        summary = "Available partitions (queues):\n\n"
        summary += f"{'Name':<15} {'MaxNodes':<10} {'MaxCores':<10} {'MaxGPUs':<8}\n"
        summary += "-" * 50 + "\n"
        for q in queues:
            name = q.get('queueName', 'unknown')
            max_nodes = q.get('queMaxNodect', '?')
            max_cores = q.get('queMaxNcpus', '?')
            max_gpus = q.get('queMaxNgpus', '0')
            summary += f"{name:<15} {max_nodes:<10} {max_cores:<10} {max_gpus:<8}\n"
        return summary

    else:  # ssh mode
        ssh, _ = _get_ssh()
        if ssh is None:
            return "Error: SSH connection not available."

        try:
            stdin, stdout, stderr = ssh.exec_command("sinfo -s")
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()

            if exit_code != 0:
                return f"Error listing partitions: {error}"

            return f"Available partitions (queues):\n\n{output}"
        except Exception as e:
            return f"Error: {str(e)}"


# =============================================================================
# Structure Handling (Materials Project Integration)
# =============================================================================

@tool("Get Structure from Materials Project")
def get_structure_from_mp_by_id(material_id: str) -> str:
    """
    Retrieve crystal structure from Materials Project by material ID.

    Args:
        material_id: Materials Project material ID (e.g., 'mp-149' for Si)

    Returns:
        Structure information and saves to local for VASP input generation
    """
    try:
        from mp_api.client import MPRester
        from pymatgen.core.structure import Structure
    except ImportError:
        return "Error: Required packages not installed: mp-api and pymatgen"

    api_key = os.environ.get("MP_KEY", "")
    if not api_key:
        return "Error: MP_KEY not set in environment"

    try:
        with MPRester(api_key) as mpr:
            structure = mpr.get_structure_by_material_id(material_id)

            lattice = structure.lattice
            info = "Successfully retrieved structure for " + material_id + ":\n\n"
            info += "Formula: " + structure.composition.reduced_formula + "\n"
            info += "Number of sites: " + str(len(structure)) + "\n"
            info += "Lattice parameters:\n"
            info += "  a = " + f"{lattice.a:.4f}" + " Å\n"
            info += "  b = " + f"{lattice.b:.4f}" + " Å\n"
            info += "  c = " + f"{lattice.c:.4f}" + " Å\n"
            info += "  alpha = " + f"{lattice.alpha:.2f}" + "°\n"
            info += "  beta = " + f"{lattice.beta:.2f}" + "°\n"
            info += "  gamma = " + f"{lattice.gamma:.2f}" + "°\n"
            info += "Volume: " + f"{structure.volume:.4f}" + " Å³\n"
            info += "Density: " + f"{structure.density:.4f}" + " g/cm³\n"

            job_dir = _get_local_job_dir()
            structure_file = os.path.join(job_dir, material_id + "_structure.json")
            structure.to_file(structure_file, fmt="json")

            info += "\nStructure saved to: " + structure_file

            return info
    except Exception as e:
        return "Error retrieving structure from Materials Project: " + str(e)


@tool("Read POSCAR from Local File")
def read_poscar_from_file(file_path: str) -> str:
    """
    Read a POSCAR file from local disk and parse it using pymatgen.

    Args:
        file_path: Full path to the POSCAR file

    Returns:
        Structure information parsed from POSCAR
    """
    try:
        from pymatgen.io.vasp import Poscar
        from pymatgen.core.structure import Structure
    except ImportError:
        return "Error: pymatgen not installed"

    if not os.path.exists(file_path):
        return "Error: File not found: " + file_path

    try:
        poscar = Poscar.from_file(file_path)
        structure = poscar.structure

        lattice = structure.lattice
        info = "Successfully read POSCAR:\n\n"
        info += "Formula: " + structure.composition.reduced_formula + "\n"
        info += "Number of sites: " + str(len(structure)) + "\n"
        info += "Lattice parameters:\n"
        info += "  a = " + f"{lattice.a:.4f}" + " Å\n"
        info += "  b = " + f"{lattice.b:.4f}" + " Å\n"
        info += "  c = " + f"{lattice.c:.4f}" + " Å\n"
        info += "Volume: " + f"{structure.volume:.4f}" + " Å³\n"

        return info
    except Exception as e:
        return "Error reading POSCAR: " + str(e)


# =============================================================================
# VASP Input File Generation
# =============================================================================

@tool("Generate VASP Input from Structure")
def generate_vasp_input_from_structure(
    structure_file_path: str,
    calculation_type: str = "structure_relaxation",
    kpoints_density: float = 0.5
) -> str:
    """
    Generate complete set of VASP input files (POSCAR, INCAR, KPOINTS, POTCAR) from a pymatgen structure file.

    Args:
        structure_file_path: Path to the structure file (JSON format from get_structure_from_mp_by_id)
        calculation_type: Type of calculation - available options:
            - "structure_relaxation": Full atomic and cell relaxation (ISIF=3)
            - "static": Static self-consistent calculation (for DOS/band properties)
            - "band": Band structure calculation
            - "dos": Density of states calculation
        kpoints_density: k-point density in 1/Å (default 0.5, lower for larger cells)

    Returns:
        Summary of generated input files
    """
    try:
        from pymatgen.core.structure import Structure
        from pymatgen.io.vasp.sets import MPRelaxSet, MPStaticSet, MPNonSCFSet
    except ImportError as e:
        return f"Error: pymatgen not installed. Details: {str(e)}"

    # Check if POTCAR directory is configured
    psp_dir = os.environ.get("PMG_VASP_PSP_DIR")
    if not psp_dir:
        return "Error: PMG_VASP_PSP_DIR environment variable not set. Please set it to your POTCAR (VASP pseudopotential) directory."

    if not os.path.exists(psp_dir):
        return f"Error: POTCAR directory not found at {psp_dir}. Please check your PMG_VASP_PSP_DIR configuration."

    if not os.path.exists(structure_file_path):
        return "Error: Structure file not found: " + structure_file_path

    job_dir = os.path.dirname(structure_file_path)
    input_dir = os.path.join(job_dir, "input")
    os.makedirs(input_dir, exist_ok=True)

    try:
        structure = Structure.from_file(structure_file_path)

        # Create kpoints object manually for maximum pymatgen compatibility
        # This avoids issues with different parameter names across pymatgen versions
        from pymatgen.io.vasp import Kpoints
        kpoints = Kpoints.automatic_density(structure, kpoints_density)

        # Our POTCAR directory has elements directly in the root (no extra POT_GGA_PAW_PBE layer)
        # user_potcar_functional=None disables the extra directory layer
        # Use user_kpoints_settings (correct parameter name in modern pymatgen)
        if calculation_type == "structure_relaxation":
            vis = MPRelaxSet(structure, user_kpoints_settings=kpoints, user_potcar_functional=None)
        elif calculation_type == "static":
            vis = MPStaticSet(structure, user_kpoints_settings=kpoints, user_potcar_functional=None)
        elif calculation_type in ["dos", "band"]:
            vis = MPNonSCFSet(structure, user_kpoints_settings=kpoints, user_potcar_functional=None)
        else:
            return "Error: Unknown calculation type: " + calculation_type + ". Available: structure_relaxation, static, dos, band"

        vis.write_input(input_dir)

        files = os.listdir(input_dir)
        summary = "Successfully generated VASP input files for " + calculation_type + ":\n\n"
        summary += "System: " + structure.composition.reduced_formula + "\n"
        summary += "Number of atoms: " + str(len(structure)) + "\n"
        summary += "k-point density: " + str(kpoints_density) + " 1/Å\n"
        summary += "\nGenerated files:\n"
        for f in files:
            f_path = os.path.join(input_dir, f)
            size = os.path.getsize(f_path)
            summary += "  - " + f + " (" + str(size) + " bytes)\n"
        summary += "\nDirectory: " + input_dir + "\n"

        return summary
    except Exception as e:
        return "Error generating VASP input: " + str(e)


@tool("Generate SLURM Script")
def generate_slurm_script(
    input_dir: str,
    partition: str,
    nodes: int = 1,
    tasks_per_node: int = 32,
    job_name: Optional[str] = None
) -> str:
    """
    Generate SLURM submission script for VASP calculation.

    Args:
        input_dir: Local input directory containing VASP input files
        partition: Partition (queue) name to use (use list_available_partitions to get options)
        nodes: Number of nodes to request (default 1)
        tasks_per_node: Number of MPI tasks per node (default 32 for typical compute node)
        job_name: Optional job name (defaults to vasp_calculation)

    Returns:
        Path to generated SLURM script
    """
    vasp_module = os.environ.get("VASP_MODULE_NAME", "vasp-6.4.2-intelmpi2017_ioptcell")

    if not job_name:
        job_name = "vasp_calculation"

    # Extract the VASP version directory from module name
    # Module format: vasp-5.4.4-ioptcell_intelmpi2017_hdf5_libxc
    # Full path: /public/home/scniv4a4go/apprepo/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc
    vasp_dir = vasp_module.split(' ', 1)[-1] if ' ' in vasp_module else vasp_module
    # Remove the 'vasp-' prefix if present
    if vasp_dir.startswith('vasp-'):
        vasp_dir = vasp_dir[5:]
    vasp_path = f"/public/home/scniv4a4go/apprepo/vasp/{vasp_dir}"

    slurm_content = f"""#!/bin/bash
#SBATCH -J {job_name}
#SBATCH -p {partition}
#SBATCH -N {nodes}
#SBATCH --ntasks-per-node={tasks_per_node}

module purge
module load {vasp_module}
# Source the environment script to correctly set MKL and compiler libraries (scnet.cn specific)
source {vasp_path}/scripts/env.sh

# MKL optimizations for better performance
export MKL_DEBUG_CPU_TYPE=5
export MKL_CBWR=AVX2
export I_MPI_PIN_DOMAIN=numa

# Increase memory lock limit for MPI (fixes: DAPL startup: RLIMIT_MEMLOCK too small)
ulimit -l unlimited
# Increase stack size to avoid segmentation faults
ulimit -s unlimited

WDIR=$(pwd)
echo "Starting VASP calculation on $SLURM_JOB_NODELIST"
echo "Working directory: $WDIR"
echo "Number of nodes: $SLURM_NNODES"
echo "Total tasks: $SLURM_NPROCS"

# Run VASP with MPI (using srun for Slurm)
srun --mpi=pmi2 vasp_std

echo "VASP calculation completed"
"""

    script_path = os.path.join(input_dir, "vasp.slurm")
    with open(script_path, 'w') as f:
        f.write(slurm_content)

    summary = "Successfully generated SLURM script:\n\n"
    summary += "Path: " + script_path + "\n"
    summary += "Job name: " + job_name + "\n"
    summary += "Partition: " + partition + "\n"
    summary += "Nodes: " + str(nodes) + "\n"
    summary += "Total tasks: " + str(nodes * tasks_per_node) + "\n"
    summary += "VASP module: " + vasp_module + "\n"

    return summary


# =============================================================================
# Job Submission and Monitoring
# =============================================================================

@tool("Submit VASP Job")
def submit_vasp_job(local_input_dir: str) -> str:
    """
    Upload all VASP input files to supercomputer and submit the job.
    Creates a new timestamped remote working directory to avoid conflicts between jobs.
    Works with both SSH/SFTP mode and official API mode.

    Args:
        local_input_dir: Local directory containing all input files (POSCAR, INCAR, KPOINTS, POTCAR, vasp.slurm)

    Returns:
        Job ID if submission successful
    """
    mode = _get_api_connection_mode()

    # Extract the job directory name from local_input_dir (e.g., job_20260422_135818)
    # This ensures local and remote directories have the EXACT SAME NAME!
    # local_input_dir format: /path/to/job_YYYYMMDD_HHMMSS/input
    parent_dir = os.path.dirname(local_input_dir)  # Get the job_* directory
    job_dir_name = os.path.basename(parent_dir)    # Extract job_YYYYMMDD_HHMMSS

    base_remote_dir = os.environ.get("VASP_JOBS_REMOTE_DIR", "~/vasp_jobs")

    # Expand ~ to user home directory (required for API which doesn't expand tilde)
    # scnet.cn uses /public/home/ not /home/ for user directories
    if base_remote_dir.startswith("~/"):
        # On supercomputing cluster, the username is SUPERCOMPUTING_USERNAME, not SCNET_API_USER
        username = os.environ.get("SUPERCOMPUTING_USERNAME", "") or os.environ.get("SCNET_API_USER", "")
        if username:
            base_remote_dir = f"/public/home/{username}/{base_remote_dir[2:]}"

    # Use the SAME directory name as local - no more timestamp mismatch!
    remote_dir = f"{base_remote_dir.rstrip('/')}/{job_dir_name}"

    if mode == "api":
        # Get current user
        username = os.environ.get("SCNET_API_USER", "") or os.environ.get("SUPERCOMPUTING_USERNAME", "")

        # Get partition from environment or use default
        partition = os.environ.get("VASP_DEFAULT_PARTITION", "kshcnormal")

        # Parse nodes and tasks from environment or use defaults
        nodes = int(os.environ.get("VASP_DEFAULT_NODES", "1"))
        tasks_per_node = int(os.environ.get("VASP_DEFAULT_TASKS_PER_NODE", "16"))

        # Create directory via API
        success, err = _api_create_directory(remote_dir, create_parents=True)
        if not success:
            return f"Error creating remote directory via API: {err}"

        uploaded = []
        failed = []
        # Upload all files
        for filename in os.listdir(local_input_dir):
            local_path = os.path.join(local_input_dir, filename)
            if os.path.isfile(local_path):
                remote_path = f"{remote_dir.rstrip('/')}/{filename}"
                success, err = _api_upload_file(local_path, remote_path)
                if success:
                    uploaded.append(filename)
                else:
                    failed.append(f"{filename}: {err}")

        if failed:
            return f"Some files failed to upload:\n" + "\n".join(failed) + f"\n\nUploaded: {uploaded}"

        # Find vasp.slurm path
        if "vasp.slurm" not in uploaded:
            return f"Error: vasp.slurm not found in {local_input_dir}. Did you generate it with generate_slurm_script?"

        remote_slurm_path = f"{remote_dir.rstrip('/')}/vasp.slurm"
        job_name = f"vasp_{job_dir_name}"

        # Submit job via API
        job_id, err = _api_submit_job(
            remote_work_dir=remote_dir,
            slurm_path=remote_slurm_path,
            queue=partition,
            nodes=nodes,
            ppn=tasks_per_node,
            wall_time="72:00:00",
            job_name=job_name
        )

        if err:
            return f"Job submission failed via API: {err}"

        return f"✅ Job submitted successfully via API!\n\nJob ID: {job_id}\nUploaded files: {', '.join(uploaded)}\nRemote directory: {remote_dir}\nPartition: {partition}\nNodes: {nodes}, Tasks per node: {tasks_per_node}"

    else:  # ssh mode
        ssh, sftp = _get_ssh()
        if ssh is None or sftp is None:
            return "Error: SSH/SFTP connection not available"

        try:
            # Create base directory if it doesn't exist
            ssh.exec_command(f"mkdir -p {base_remote_dir}")
            # Create job-specific directory
            ssh.exec_command(f"mkdir -p {remote_dir}")

            # Get absolute path (expands ~ to full path) using realpath
            stdin, stdout, stderr = ssh.exec_command(f"realpath {remote_dir}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                error = stderr.read().decode()
                return f"Error: Failed to create remote directory {remote_dir}: {error}"
            # Get absolute path (expands ~ to full path)
            abs_remote_dir = stdout.read().decode().strip()
        except Exception as e:
            return f"Error creating remote directory: {str(e)}"

        uploaded = []
        try:
            for filename in os.listdir(local_input_dir):
                local_path = os.path.join(local_input_dir, filename)
                if os.path.isfile(local_path):
                    # Use absolute path for SFTP to avoid ~ issues
                    remote_path = f"{abs_remote_dir.rstrip('/')}/{filename}"
                    sftp.put(local_path, remote_path)
                    uploaded.append(filename)
            remote_dir = abs_remote_dir
        except Exception as e:
            return f"Error uploading files: {str(e)}"

        # Submit job
        cmd = f"cd {remote_dir} && sbatch vasp.slurm"
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()

            if exit_code != 0:
                return f"Job submission failed with exit code {exit_code}:\n{error}"

            # Parse job ID from output: "Submitted batch job 123456"
            match = re.search(r'Submitted batch job (\d+)', output)
            if not match:
                return f"Could not parse job ID from output: {output}"

            job_id = match.group(1)
            return f"✅ Job submitted successfully!\n\nJob ID: {job_id}\nUploaded files: {', '.join(uploaded)}\nRemote directory: {remote_dir}"
        except Exception as e:
            return f"Error submitting job: {str(e)}"


@tool("Check Job Status")
def check_job_status(job_id: int) -> str:
    """
    Check the current status of a submitted VASP job.
    Works with both SSH/SFTP mode and official API mode.

    Args:
        job_id: Slurm job ID (or API job ID)

    Returns:
        Current job status (PENDING, RUNNING, COMPLETED, FAILED)
    """
    mode = _get_api_connection_mode()

    if mode == "api":
        status, job_name, err = _api_get_job_status(str(job_id))
        if err:
            return f"Error checking job status via API: {err}"
        return f"Job {job_id} status: {status}\nName: {job_name if job_name else 'N/A'}"

    else:  # ssh mode
        ssh, _ = _get_ssh()
        if ssh is None:
            return "Error: SSH connection not available"

        try:
            stdin, stdout, stderr = ssh.exec_command(f"squeue -j {job_id} -h")
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode()

            if exit_code != 0 or not output.strip():
                # No output from squeue means job is no longer in queue
                # Check accounting with sacct for completion status
                stdin2, stdout2, stderr2 = ssh.exec_command(f"sacct -j {job_id} -o State -n -P")
                output2 = stdout2.read().decode()
                if output2.strip():
                    state = output2.strip().split('\n')[0]
                    return f"Job {job_id} status: {state}"
                else:
                    return f"Job {job_id} not found in queue or accounting"

            # Job is still in queue, parse status
            parts = output.strip().split()
            if len(parts) >= 5:
                status_code = parts[4]
                status_map = {
                    'PD': 'PENDING (queued)',
                    'R': 'RUNNING',
                    'CG': 'COMPLETING (finalizing)',
                    'CF': 'CONFIGURING',
                    'NF': 'NODE_FAIL',
                    'RV': 'REVOKED',
                    'SE': 'SPECIAL_EXIT',
                    'ST': 'STOPPED',
                    'S': 'SUSPENDED'
                }
                status = status_map.get(status_code, status_code)
                partition = parts[1]
                name = parts[2]
                return f"Job {job_id} status: {status}\nPartition: {partition}\nName: {name}"
            else:
                return f"Job {job_id} is in queue:\n{output}"
        except Exception as e:
            return f"Error checking job status: {str(e)}"


@tool("Cancel Job")
def cancel_job(job_id: int) -> str:
    """
    Cancel a running or pending VASP job.
    Works with both SSH/SFTP mode and official API mode.

    Args:
        job_id: Slurm job ID (or API job ID)

    Returns:
        Cancellation confirmation
    """
    mode = _get_api_connection_mode()

    if mode == "api":
        success, err = _api_cancel_job(str(job_id))
        if success:
            return f"✅ Job {job_id} cancelled successfully via API"
        else:
            return f"Cancellation failed via API: {err}"

    else:  # ssh mode
        ssh, _ = _get_ssh()
        if ssh is None:
            return "Error: SSH connection not available"

        try:
            stdin, stdout, stderr = ssh.exec_command(f"scancel {job_id}")
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()

            if exit_code != 0:
                return f"Cancellation failed with exit code {exit_code}:\n{error}"

            return f"✅ Job {job_id} cancelled successfully"
        except Exception as e:
            return f"Error cancelling job: {str(e)}"


# =============================================================================
# Result Download and Parsing
# =============================================================================

def _api_list_directory(remote_path: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """
    List files in remote directory via API.
    Returns: (list of file info dicts, error message)
    Each dict has: name (str), type ('file' or 'dir'), size (int)
    """
    token, _, efile_urls, err = _api_get_token()
    if err:
        return None, err

    url = f"{efile_urls}/openapi/v2/file/list"
    headers = {"token": token}
    params = {"path": remote_path}

    try:
        response = requests.post(url, headers=headers, params=params, json={}, timeout=30)
        if response.status_code != 200:
            return None, f"List directory failed: status {response.status_code}"
        data = response.json()
        if data.get("code") != "0" and data.get("code") != 0:
            msg = data.get("msg", "Unknown error")
            return None, f"List directory failed: {msg}"

        files_data = data.get("data", [])
        result = []
        for f in files_data:
            # Different API versions may use different key names
            file_name = f.get("name", f.get("fileName", ""))
            file_type = f.get("type", f.get("fileType", "file"))
            file_size = f.get("size", f.get("fileSize", 0))
            result.append({"name": file_name, "type": file_type, "size": file_size})
        return result, ""
    except Exception as e:
        return None, f"API error: {str(e)}"


@tool("Download VASP Results")
def download_vasp_results(job_id: int, local_job_dir: Optional[str] = None, remote_job_dir: Optional[str] = None) -> str:
    """
    Download all VASP result files from the supercomputer after job completion.
    Works with both SSH/SFTP mode and official API mode.

    Args:
        job_id: Slurm job ID (or API job ID)
        local_job_dir: Optional local directory to save results (auto-created if not given)
        remote_job_dir: Optional remote job directory (auto-detected from timestamp if not given)

    Returns:
        Summary of downloaded files and local directory
    """
    mode = _get_api_connection_mode()

    if not local_job_dir:
        local_job_dir = _get_local_job_dir(job_id)
    output_dir = os.path.join(local_job_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # If remote_job_dir is not provided, construct it directly from local_job_dir
    # Local and remote directories have the EXACT SAME NAME (fixed in submit_vasp_job)
    if remote_job_dir is None:
        # Construct the base remote directory (same logic as submit_vasp_job)
        base_remote_dir = os.environ.get("VASP_JOBS_REMOTE_DIR", "~/vasp_jobs")
        if base_remote_dir.startswith("~/"):
            username = os.environ.get("SUPERCOMPUTING_USERNAME", "") or os.environ.get("SCNET_API_USER", "")
            if username:
                base_remote_dir = f"/public/home/{username}/{base_remote_dir[2:]}"

        # Extract job directory name from local_job_dir - use the SAME name for remote!
        job_dir_name = os.path.basename(local_job_dir)
        remote_dir = f"{base_remote_dir.rstrip('/')}/{job_dir_name}"
        print(f"[DEBUG] Constructed remote directory: {remote_dir}")
    else:
        # Use the provided remote_job_dir directly
        remote_dir = remote_job_dir

    # List of common VASP output files to download (with multiple naming patterns)
    vasp_output_patterns = [
        # Standard VASP output files
        "OUTCAR", "CONTCAR", "OSZICAR", "INCAR", "KPOINTS", "POSCAR",
        "XDATCAR", "CHGCAR", "WAVECAR", "PROCAR", "vasprun.xml",
        "EIGENVAL", "DOSCAR", "IBZKPT", "POTCAR", "REPORT",
        # Slurm output files (multiple naming conventions)
        f"std.out.{job_id}", f"std.err.{job_id}",
        f"slurm-{job_id}.out", f"slurm-{job_id}.err",
        f"job.{job_id}.out", f"job.{job_id}.err",
        f"vasp.{job_id}.out", f"vasp.{job_id}.err"
    ]

    if mode == "api":
        downloaded = []
        failed = []
        debug_info = []

        debug_info.append(f"Remote directory: {remote_dir}")

        # List remote directory to see what files actually exist
        files_list, err = _api_list_directory(remote_dir)
        if err:
            # Directory not accessible - try to list parent directory to help debug
            debug_info.append(f"⚠️ Cannot access directory: {err}")
            parent_dir = os.path.dirname(remote_dir)
            debug_info.append(f"\n💡 Checking parent directory for help: {parent_dir}")
            parent_files, parent_err = _api_list_directory(parent_dir)
            if not parent_err and parent_files:
                debug_info.append(f"   Found these items in parent directory:")
                for f in parent_files[:20]:
                    debug_info.append(f"     - {f['name']}{'/' if f['type'] == 'dir' else ''}")
                if len(parent_files) > 20:
                    debug_info.append(f"     ... and {len(parent_files) - 20} more")
            else:
                debug_info.append(f"   Parent directory also not accessible")
        else:
            remote_files = [f["name"] for f in files_list if f["type"] == "file"]
            debug_info.append(f"Files found in remote directory ({len(remote_files)}):")
            for f in sorted(remote_files):
                debug_info.append(f"  - {f}")

        # Step 1: List remote directory to see what files actually exist
        files_list, err = _api_list_directory(remote_dir)
        if err:
            debug_info.append(f"Warning: Could not list remote directory: {err}")
            debug_info.append("Falling back to direct file check...")
            # Fallback: try direct file check
            for filename in vasp_output_patterns:
                remote_path = f"{remote_dir.rstrip('/')}/{filename}"
                exist, err = _api_check_file_exists(remote_path)
                if exist:
                    local_path = os.path.join(output_dir, filename)
                    success, dl_err = _api_download_file(remote_path, local_path)
                    if success:
                        downloaded.append(filename)
                    else:
                        failed.append(f"{filename} (download: {dl_err})")
                else:
                    failed.append(f"{filename} (not found)")
        else:
            # Success: we have the actual file list!
            remote_files = [f["name"] for f in files_list if f["type"] == "file"]
            debug_info.append(f"Files found in remote directory ({len(remote_files)}):")
            for f in sorted(remote_files):
                debug_info.append(f"  - {f}")

            # Download all files that match VASP output patterns
            # Also download ALL VASP-related files (case-insensitive match)
            files_to_download = set()

            # Pattern 1: exact match
            for pattern in vasp_output_patterns:
                if pattern in remote_files:
                    files_to_download.add(pattern)

            # Pattern 2: case-insensitive match for common VASP files
            vasp_prefixes = ["OUTCAR", "CONTCAR", "OSZICAR", "INCAR", "KPOINTS",
                           "POSCAR", "XDATCAR", "CHGCAR", "WAVECAR", "PROCAR",
                           "vasprun", "EIGENVAL", "DOSCAR", "IBZKPT", "POTCAR"]
            for rf in remote_files:
                rf_upper = rf.upper()
                for prefix in vasp_prefixes:
                    if rf_upper.startswith(prefix) or prefix in rf_upper:
                        files_to_download.add(rf)
                        break
                # Also download any .out or .err files
                if rf.endswith(".out") or rf.endswith(".err") or rf.endswith(".log"):
                    files_to_download.add(rf)

            debug_info.append(f"\nFiles to download ({len(files_to_download)}):")
            for f in sorted(files_to_download):
                debug_info.append(f"  - {f}")

            # Download each file
            for filename in sorted(files_to_download):
                remote_path = f"{remote_dir.rstrip('/')}/{filename}"
                local_path = os.path.join(output_dir, filename)
                success, err = _api_download_file(remote_path, local_path)
                if success:
                    downloaded.append(filename)
                else:
                    failed.append(f"{filename}: {err}")

            # Report any files that were not found but we expected
            expected_not_found = []
            for pattern in vasp_output_patterns:
                if pattern not in files_to_download:
                    expected_not_found.append(pattern)

        # Build summary output
        summary = f"✅ Results download complete via API:\n\n"
        summary += f"Job ID: {job_id}\n"
        summary += f"Remote directory: {remote_dir}\n"
        summary += f"Local output directory: {output_dir}\n"

        if debug_info:
            summary += "\n--- Debug Info ---\n"
            for line in debug_info:
                summary += line + "\n"

        summary += f"\nDownloaded files ({len(downloaded)}):\n"
        for f in sorted(downloaded):
            f_path = os.path.join(output_dir, f)
            if os.path.exists(f_path):
                size = os.path.getsize(f_path)
                size_kb = size / 1024
                summary += f"  - {f} ({size_kb:.1f} KB)\n"
            else:
                summary += f"  - {f}\n"

        if failed:
            summary += f"\nFiles not found/failed ({len(failed)}):\n"
            for f in sorted(failed)[:20]:
                summary += f"  - {f}\n"
            if len(failed) > 20:
                summary += f"  ... and {len(failed) - 20} more\n"

        if len(downloaded) == 0:
            summary += "\n⚠️  WARNING: No files were downloaded!\n"
            summary += "Please verify:\n"
            summary += "  1. Remote directory path is correct\n"
            summary += "  2. Job has completed and output files exist\n"
            summary += "  3. Files are not stored in a subdirectory\n"

        return summary

    else:  # ssh mode
        ssh, sftp = _get_ssh()
        if ssh is None or sftp is None:
            return "Error: SSH/SFTP connection not available"

        downloaded = []
        failed = []
        debug_info = []

        try:
            # First list remote directory to see what's available
            stdin, stdout, stderr = ssh.exec_command(f"ls -la {remote_dir}")
            exit_code = stdout.channel.recv_exit_status()
            ls_output = stdout.read().decode()
            ls_error = stderr.read().decode()

            if exit_code == 0:
                debug_info.append(f"Files in remote directory:\n{ls_output}")
                # Parse filenames from ls output
                remote_files = []
                for line in ls_output.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 9 and not line.startswith('total'):
                        remote_files.append(parts[-1])
                debug_info.append(f"Found {len(remote_files)} files")
            else:
                debug_info.append(f"Warning: ls command failed: {ls_error}")
                remote_files = None

            # Download all matching files
            if remote_files:
                files_to_download = set()
                # Match VASP output patterns
                for rf in remote_files:
                    rf_upper = rf.upper()
                    for pattern in vasp_output_patterns:
                        if rf == pattern or pattern in rf_upper:
                            files_to_download.add(rf)
                            break
                    # Also download any output/error/log files
                    if rf.endswith(".out") or rf.endswith(".err") or rf.endswith(".log"):
                        files_to_download.add(rf)

                for filename in sorted(files_to_download):
                    remote_path = f"{remote_dir.rstrip('/')}/{filename}"
                    try:
                        local_path = os.path.join(output_dir, filename)
                        sftp.get(remote_path, local_path)
                        downloaded.append(filename)
                    except Exception as e:
                        failed.append(f"{filename}: {str(e)}")
            else:
                # Fallback: try fixed file list
                for filename in vasp_output_patterns:
                    remote_path = f"{remote_dir.rstrip('/')}/{filename}"
                    try:
                        sftp.stat(remote_path)
                        local_path = os.path.join(output_dir, filename)
                        sftp.get(remote_path, local_path)
                        downloaded.append(filename)
                    except IOError:
                        failed.append(filename)
                    except Exception as e:
                        failed.append(f"{filename}: {str(e)}")

        except Exception as e:
            debug_info.append(f"Error during file listing: {str(e)}")

        # Build summary
        summary = f"✅ Results download complete:\n\n"
        summary += f"Job ID: {job_id}\n"
        summary += f"Remote directory: {remote_dir}\n"
        summary += f"Local output directory: {output_dir}\n"

        if debug_info:
            summary += "\n--- Debug Info ---\n"
            for line in debug_info[:50]:  # Limit debug output
                summary += line + "\n"

        summary += f"\nDownloaded files ({len(downloaded)}):\n"
        for f in sorted(downloaded):
            f_path = os.path.join(output_dir, f)
            size = os.path.getsize(f_path)
            size_kb = size / 1024
            summary += f"  - {f} ({size_kb:.1f} KB)\n"

        if failed:
            summary += f"\nFiles not found/failed ({len(failed)}):\n"
            for f in sorted(failed)[:20]:
                summary += f"  - {f}\n"
            if len(failed) > 20:
                summary += f"  ... and {len(failed) - 20} more\n"

        if len(downloaded) == 0:
            summary += "\n⚠️  WARNING: No files were downloaded!\n"
            summary += "Please verify:\n"
            summary += "  1. Remote directory path is correct\n"
            summary += "  2. Job has completed and output files exist\n"
            summary += "  3. Files are not stored in a subdirectory\n"

        return summary


@tool("Parse VASP Output")
def parse_vasp_output(outcar_path: str) -> str:
    """
    Parse VASP OUTCAR file and extract key results.

    Args:
        outcar_path: Path to OUTCAR file

    Returns:
        Extracted properties (energy, band gap, forces, Fermi level, etc.)
    """
    try:
        from pymatgen.io.vasp import Outcar
        import numpy as np
    except ImportError as e:
        return f"Error: Required package not installed. Details: {str(e)}"

    if not os.path.exists(outcar_path):
        return f"Error: OUTCAR file not found: {outcar_path}"

    try:
        outcar = Outcar(outcar_path)

        summary = "VASP OUTCAR Parsing Results:\n\n"

        # Final energy
        if hasattr(outcar, 'final_energy'):
            summary += f"Final energy: {outcar.final_energy:.6f} eV\n"

        # Energy per atom
        if hasattr(outcar, 'final_energy') and hasattr(outcar, 'structure'):
            n_atoms = len(outcar.structure)
            e_per_atom = outcar.final_energy / n_atoms
            summary += f"Final energy per atom: {e_per_atom:.6f} eV/atom\n"

        # Band gap from VASP
        try:
            bg = None
            if hasattr(outcar, 'bandgap'):
                bg = outcar.bandgap
            elif hasattr(outcar, 'bands') and outcar.bands is not None:
                # Modern pymatgen stores band gap in bands object
                bg = outcar.bands.get_gap()
            if bg is not None:
                summary += f"Band gap: {bg:.4f} eV\n"
                if bg > 0:
                    summary += "  → Semiconductor/insulator\n"
                else:
                    summary += "  → Metal\n"
        except Exception:
            # Skip band gap if not available
            pass

        # Fermi level
        if hasattr(outcar, 'efermi'):
            summary += f"Fermi level: {outcar.efermi:.4f} eV\n"

        # Maximum force on atoms
        try:
            forces = None
            if hasattr(outcar, 'forces'):
                forces = outcar.forces
            elif hasattr(outcar, 'ionic_steps') and outcar.ionic_steps:
                # Modern pymatgen stores forces in ionic_steps
                last_step = outcar.ionic_steps[-1]
                forces = last_step.get('forces', None)
            if forces is not None and len(forces) > 0:
                force_norms = np.linalg.norm(forces, axis=1)
                max_force = np.max(force_norms)
                avg_force = np.mean(force_norms)
                summary += f"Maximum force: {max_force:.6f} eV/Å\n"
                summary += f"Average force: {avg_force:.6f} eV/Å\n"
        except Exception:
            # Skip forces if not available
            pass

        # Magnetic moments
        try:
            if hasattr(outcar, 'magnetization'):
                mag = outcar.magnetization
                if mag is not None and len(mag) > 0:
                    total_mag = sum(m[0] for m in mag)
                    summary += f"Total magnetization: {total_mag:.4f} μB\n"
        except Exception:
            pass

        # Number of ionic steps
        try:
            n_steps = None
            if hasattr(outcar, 'nionic_steps'):
                n_steps = outcar.nionic_steps
            elif hasattr(outcar, 'ionic_steps'):
                n_steps = len(outcar.ionic_steps)
            if n_steps is not None:
                summary += f"Number of ionic steps: {n_steps}\n"
        except Exception:
            pass

        return summary
    except Exception as e:
        return f"Error parsing OUTCAR: {str(e)}"


# =============================================================================
# End-to-end Complete Calculation
# =============================================================================

@tool("Complete VASP Calculation from MP ID")
def run_complete_vasp_calculation_from_mp(
    material_id: str,
    partition: str,
    calculation_type: str = "structure_relaxation",
    kpoints_density: float = 0.5,
    nodes: int = 1,
    tasks_per_node: int = 32,
    poll_interval: int = 60
) -> str:
    """
    End-to-end complete VASP calculation starting from Materials Project ID.
    This automates the entire workflow: get structure → generate input → submit → wait → download → parse.

    Args:
        material_id: Materials Project ID (e.g., 'mp-149')
        partition: Partition (queue) name to use
        calculation_type: Type of calculation (structure_relaxation, static, dos, band)
        kpoints_density: k-point density in 1/Å
        nodes: Number of nodes
        tasks_per_node: Tasks per node
        poll_interval: Seconds between status checks (default 60)

    Returns:
        Complete calculation summary with parsed results
    """
    start_time = datetime.now()

    # Helper to call underlying function of a CrewAI tool
    def _call_tool(tool_func, *args, **kwargs):
        if hasattr(tool_func, 'func'):
            return tool_func.func(*args, **kwargs)
        try:
            return tool_func(*args, **kwargs)
        except TypeError:
            # Fallback: try different access patterns for CrewAI
            for attr in ['__wrapped__', '_func', 'original_func']:
                if hasattr(tool_func, attr):
                    return getattr(tool_func, attr)(*args, **kwargs)
            raise

    # Step 1: Get structure from MP
    step1_result = _call_tool(get_structure_from_mp_by_id, material_id)
    if "Error" in step1_result:
        return step1_result

    # Extract structure file path from result
    match = re.search(r'Structure saved to: (.+)$', step1_result, re.MULTILINE)
    if not match:
        return f"Could not find structure file path in result:\n{step1_result}"
    structure_file = match.group(1)
    job_dir = os.path.dirname(structure_file)

    # Step 2: Generate VASP input
    step2_result = _call_tool(
        generate_vasp_input_from_structure,
        structure_file_path=structure_file,
        calculation_type=calculation_type,
        kpoints_density=kpoints_density
    )
    if "Error" in step2_result:
        return step2_result

    # Extract input directory
    match = re.search(r'Directory: (.+)$', step2_result, re.MULTILINE)
    if not match:
        return f"Could not find input directory in result:\n{step2_result}"
    input_dir = match.group(1)

    # Step 3: Generate SLURM script
    job_name = f"vasp_{material_id}"
    step3_result = _call_tool(
        generate_slurm_script,
        input_dir=input_dir,
        partition=partition,
        nodes=nodes,
        tasks_per_node=tasks_per_node,
        job_name=job_name
    )
    if "Error" in step3_result:
        return step3_result

    # Step 4: Submit job
    step4_result = _call_tool(submit_vasp_job, input_dir)
    if "error" in step4_result.lower():
        return step4_result

    # Extract job ID and remote directory using robust patterns
    match_id = re.search(r'Job ID: (\d+)', step4_result)
    if not match_id:
        return f"Could not find job ID in result:\n{step4_result}"
    job_id = int(match_id.group(1))

    # Use a more robust regex that handles different line endings
    match_dir = re.search(r'Remote directory:\s*(.+?)(?:\n|$)', step4_result)
    if match_dir:
        remote_job_dir = match_dir.group(1).strip()
    else:
        # Fallback to default if not found
        remote_job_dir = os.environ.get("VASP_REMOTE_DIR", "~/apprepo/vasp/6.4.2-intelmpi2017_ioptcell/case")

    # Step 5: Wait for completion
    summary = f"===== VASP Calculation Started =====\n\n"
    summary += f"Material ID: {material_id}\n"
    summary += f"Job ID: {job_id}\n"
    summary += f"Calculation type: {calculation_type}\n"
    summary += f"Partition: {partition}\n"
    summary += f"Nodes: {nodes}, Total tasks: {nodes * tasks_per_node}\n"
    summary += f"Remote directory: {remote_job_dir}\n"
    summary += f"\nWaiting for job completion...\n"

    # Polling loop
    while True:
        status_result = _call_tool(check_job_status, job_id)
        if "Error" in status_result:
            summary += f"\n{status_result}\n"
            break

        if "COMPLETED" in status_result:
            summary += f"✓ Job completed\n"
            break
        elif "FAILED" in status_result or "CANCELLED" in status_result:
            summary += f"✗ Job {status_result}\n"
            return summary + "\nJob did not complete successfully."
        else:
            # Still running/pending
            status_line = status_result.split('\n')[0]
            summary += f"  {status_line} - checking again in {poll_interval}s...\n"
            time.sleep(poll_interval)

    # Step 6: Download results
    step6_result = _call_tool(download_vasp_results, job_id, job_dir, remote_job_dir)
    if "Error" in step6_result:
        return summary + "\n" + step6_result

    # Step 7: Parse results if OUTCAR exists
    output_dir = os.path.join(job_dir, "output")
    outcar_path = os.path.join(output_dir, "OUTCAR")
    parsed_results = ""
    if os.path.exists(outcar_path):
        parsed_results = _call_tool(parse_vasp_output, outcar_path)

    # Complete summary
    end_time = datetime.now()
    duration = end_time - start_time
    duration_min = duration.total_seconds() / 60

    final_summary = f"===== VASP Calculation Complete =====\n\n"
    final_summary += f"Material ID: {material_id}\n"
    final_summary += f"Job ID: {job_id}\n"
    final_summary += f"Calculation type: {calculation_type}\n"
    final_summary += f"Total duration: {duration_min:.1f} minutes\n"
    final_summary += f"Local working directory: {job_dir}\n"
    final_summary += f"\n--- Intermediate Steps ---\n"
    final_summary += step1_result + "\n"
    final_summary += step2_result + "\n"
    final_summary += step3_result + "\n"
    final_summary += step4_result + "\n"
    final_summary += step6_result + "\n"

    if parsed_results:
        final_summary += "\n--- Parsed Results ---\n"
        final_summary += parsed_results

    return final_summary


# =============================================================================
# VASP Output Plotting (using pymatgen and matplotlib)
# =============================================================================

def _get_matplotlib():
    """Import matplotlib lazily to avoid issues when it's not installed."""
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend for saving to file
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        raise ImportError(
            "matplotlib is not installed. Please install it using:\n"
            "pip install matplotlib\n"
            "For more details, see https://matplotlib.org/stable/installation/"
        )


@tool("Plot Energy Convergence from OSZICAR")
def plot_energy_convergence(
    oszicar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot electronic step energy convergence from VASP OSZICAR file.
    Creates a PNG image showing energy versus electronic step iteration.

    Args:
        oszicar_path: Path to the OSZICAR file from VASP output
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(oszicar_path):
        return f"Error: OSZICAR file not found at {oszicar_path}"

    try:
        from pymatgen.io.vasp import Oszicar
    except ImportError:
        return "Error: pymatgen not installed"

    try:
        oszicar = Oszicar(oszicar_path)

        # Extract energy data from each ionic step
        energies = []
        for step in oszicar.ionic_steps:
            # pymatgen stores the final energy in 'E0' key
            energies.append(step["E0"])

        iterations = list(range(1, len(energies) + 1))

        # Determine output path
        if not output_png_path:
            base, _ = os.path.splitext(oszicar_path)
            output_png_path = f"{base}_energy_convergence.png"

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Create the plot
        fig, ax = plt.subplots(figsize=(10, 6))

        ax.plot(iterations, energies, 'b-o', linewidth=2, markersize=6)
        ax.set_xlabel('Ionic Step')
        ax.set_ylabel('Total Energy (eV)')
        ax.set_title('VASP Energy Convergence')
        ax.grid(True, alpha=0.3)

        # Set x-ticks to integer steps
        ax.set_xticks(iterations)

        # Add final energy annotation
        if len(energies) > 0:
            final_e = energies[-1]
            ax.text(0.02, 0.98, f'Final Energy: {final_e:.6f} eV',
                    transform=ax.transAxes, va='top',
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created energy convergence plot:\n- Input: {oszicar_path}\n- Output PNG: {output_png_path}\n- Ionic steps: {len(energies)}"

    except Exception as e:
        return f"Error creating energy convergence plot: {str(e)}"


@tool("Plot Band Structure from VASP Output")
def plot_band_structure(
    outcar_path: str,
    procar_path: str,
    kpoints_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot electronic band structure from VASP output files (OUTCAR, PROCAR, KPOINTS).
    Creates a publication-quality PNG image of the band structure.

    Args:
        outcar_path: Path to OUTCAR file
        procar_path: Path to PROCAR file
        kpoints_path: Path to KPOINTS file (with high-symmetry path)
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    for path, name in [(outcar_path, "OUTCAR"), (procar_path, "PROCAR"), (kpoints_path, "KPOINTS")]:
        if not os.path.exists(path):
            return f"Error: {name} file not found at {path}"

    try:
        from pymatgen.io.vasp import Outcar, Procar, Kpoints
        from pymatgen.electronic_structure.plotter import BSPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly (missing electronic structure module)"

    try:
        outcar = Outcar(outcar_path)
        procar = Procar(procar_path)
        kpoints = Kpoints.from_file(kpoints_path)

        # Get band structure from pymatgen
        bands = procar.get_band_structure(kpoints, outcar.efermi)

        # Determine output path
        if not output_png_path:
            base_dir = os.path.dirname(outcar_path)
            output_png_path = os.path.join(base_dir, "band_structure.png")

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Create plot using pymatgen's BSPlotter
        plotter = BSPlotter(bands)
        plot = plotter.get_plot(ylim=(-5, 5))  # Default energy range around Fermi level

        # Save figure
        plot.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(plot.gcf())

        # Get band gap info for summary
        if bands.get_gap() > 0:
            gap_info = f"Band Gap: {bands.get_gap():.4f} eV (Semiconductor)"
        else:
            gap_info = "Band Gap: {bands.get_gap():.4f} eV (Metal)"

        return f"Successfully created band structure plot:\n- Output PNG: {output_png_path}\n- Fermi energy: {outcar.efermi:.4f} eV\n- {gap_info}"

    except Exception as e:
        return f"Error creating band structure plot: {str(e)}"


@tool("Plot Density of States from VASP Output")
def plot_density_of_states(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot total density of states (DOS) from VASP vasprun.xml file.
    Creates a publication-quality PNG image of the DOS.

    Args:
        vasprun_path: Path to vasprun.xml file from VASP output
        output_png_path: Optional output PNG path (defaults to same directory with .png extension)

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import DosPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly (missing electronic structure module)"

    try:
        vasprun = Vasprun(vasprun_path)
        complete_dos = vasprun.complete_dos

        # Determine output path
        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "density_of_states.png")

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Create plot - FIXED: use simpler API compatible with all pymatgen versions
        plotter = DosPlotter(sigma=0.1)
        plotter.add_dos("Total DOS", complete_dos)
        ax = plotter.get_plot(xlim=(-5, 5))  # Default energy range around Fermi

        # Save figure
        fig = ax.figure
        fig.set_size_inches(10, 6)
        fig.tight_layout()
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created density of states plot:\n- Output PNG: {output_png_path}\n- Fermi energy: {complete_dos.efermi:.4f} eV"

    except Exception as e:
        return f"Error creating density of states plot: {str(e)}"


@tool("Plot Total and Partial Density of States")
def plot_full_dos(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot total density of states AND elemental partial density of states from VASP.
    This is much more informative than just total DOS - shows element contributions.

    Args:
        vasprun_path: Path to vasprun.xml file from VASP output
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import DosPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
        complete_dos = vasprun.complete_dos

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "full_dos_with_elements.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        plotter = DosPlotter(sigma=0.1)
        plotter.add_dos("Total DOS", complete_dos)

        # Add partial DOS by element
        pdos = complete_dos.get_element_dos()
        for element, dos in pdos.items():
            plotter.add_dos(str(element), dos)

        ax = plotter.get_plot(xlim=(-8, 4))
        ax.legend(fontsize=10, loc='upper right')

        fig = ax.figure
        fig.set_size_inches(12, 7)
        fig.tight_layout()
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        elements = [str(e) for e in pdos.keys()]
        return f"Successfully created full PDOS plot:\n- Output PNG: {output_png_path}\n- Elements plotted: {', '.join(elements)}\n- Fermi level: {complete_dos.efermi:.4f} eV"

    except Exception as e:
        return f"Error creating full PDOS plot: {str(e)}"


@tool("Plot Band Structure with Projections")
def plot_band_structure_projected(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot electronic band structure from VASP vasprun.xml file.
    Uses manual plotting approach to avoid pymatgen version compatibility issues.

    Args:
        vasprun_path: Path to vasprun.xml file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        # Read vasprun.xml
        vasprun = Vasprun(vasprun_path)
        efermi = vasprun.efermi

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "band_structure.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Get eigen values - handle both spin-polarized and non-spin-polarized cases
        eigenvalues = vasprun.eigenvalues
        kpoints = vasprun.actual_kpoints

        # Calculate distances between consecutive k-points for the x-axis
        if len(kpoints) < 2:
            return "Error: Not enough k-points for band structure plot"

        lattice = vasprun.final_structure.lattice
        reciprocal_lattice = lattice.reciprocal_lattice

        x = [0]
        for i in range(1, len(kpoints)):
            dk = np.array(kpoints[i]) - np.array(kpoints[i-1])
            dk_cart = reciprocal_lattice.get_cartesian_coords(dk)
            dist = np.linalg.norm(dk_cart)
            x.append(x[-1] + dist)

        # Create plot
        fig, ax = plt.subplots(figsize=(12, 8))

        # Plot bands - handle both spin cases
        if isinstance(eigenvalues, dict):
            # Spin-polarized calculation
            for spin, eig_data in eigenvalues.items():
                if isinstance(eig_data, np.ndarray) and eig_data.ndim == 2:
                    nbands = eig_data.shape[1]
                    for band in range(nbands):
                        energies = eig_data[:, band] - efermi
                        label = f'{spin.name}' if band == 0 else ""
                        ax.plot(x, energies, color='blue' if spin.name == 'Up' else 'red',
                               linewidth=1.2, alpha=0.8, label=label)
        else:
            # Non-spin-polarized
            if isinstance(eigenvalues, np.ndarray) and eigenvalues.ndim == 2:
                nbands = eigenvalues.shape[1]
                for band in range(nbands):
                    energies = eigenvalues[:, band] - efermi
                    ax.plot(x, energies, color='darkblue', linewidth=1.2, alpha=0.8)

        # Add Fermi level line
        ax.axhline(y=0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='Fermi level')

        # Add vertical lines at high symmetry points
        # Find positions where k-point path changes direction (simple heuristic)
        if len(x) > 5:
            dists = np.diff(x)
            jumps = np.where(dists > np.mean(dists) * 1.5)[0]
            for jump in jumps:
                ax.axvline(x=x[jump+1], color='gray', linestyle=':', alpha=0.5)

        ax.set_xlabel('k-point path')
        ax.set_ylabel('Energy (E - E$_F$) [eV]')
        ax.set_title('Electronic Band Structure')
        ax.set_ylim(-8, 4)
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Hide x-tick labels since they don't have physical meaning without labels
        ax.set_xticks([])

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created band structure plot:\n- Output PNG: {output_png_path}\n- Fermi level: {efermi:.4f} eV\n- Number of bands: {nbands if 'nbands' in dir() else 'N/A'}\n- Number of k-points: {len(kpoints)}"

    except Exception as e:
        return f"Error creating band structure plot: {str(e)}"


@tool("Plot Orbital-resolved Partial DOS")
def plot_orbital_pdos(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot orbital-resolved density of states (s, p, d orbitals separated).
    Shows detailed contributions from different atomic orbitals.

    Args:
        vasprun_path: Path to vasprun.xml file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import DosPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
        complete_dos = vasprun.complete_dos

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "orbital_pdos.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        plotter = DosPlotter(sigma=0.05)
        plotter.add_dos("Total DOS", complete_dos)

        # Add orbital-resolved DOS (s, p, d orbitals)
        # FIXED: get_spd_dos() doesn't take site argument in newer pymatgen
        # Instead, we just plot the overall spd DOS
        spd_dos = complete_dos.get_spd_dos()
        for orbital, dos in spd_dos.items():
            plotter.add_dos(orbital.name, dos)

        ax = plotter.get_plot(xlim=(-8, 4))
        ax.legend(fontsize=9, loc='upper right', ncol=2)

        fig = ax.figure
        fig.set_size_inches(14, 8)
        fig.tight_layout()
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created orbital-resolved PDOS plot:\n- Output PNG: {output_png_path}\n- Fermi level: {complete_dos.efermi:.4f} eV"

    except Exception as e:
        return f"Error creating orbital PDOS plot: {str(e)}"


@tool("Plot Electronic Steps Convergence")
def plot_electronic_convergence(
    oszicar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot detailed electronic SCF step convergence for EACH ionic step.
    Shows how the energy converges during each self-consistent field cycle.
    Much more detailed than just final energy per ionic step.

    Args:
        oszicar_path: Path to OSZICAR file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(oszicar_path):
        return f"Error: OSZICAR file not found at {oszicar_path}"

    try:
        from pymatgen.io.vasp import Oszicar
    except ImportError:
        return "Error: pymatgen not installed"

    try:
        oszicar = Oszicar(oszicar_path)

        if not output_png_path:
            base, _ = os.path.splitext(oszicar_path)
            output_png_path = f"{base}_electronic_convergence.png"
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Collect all electronic step energies
        all_energies = []
        step_markers = [0]  # Mark where ionic steps change
        current_pos = 0

        for ionic_step in oszicar.ionic_steps:
            if 'electronic_steps' in ionic_step and ionic_step['electronic_steps']:
                for e_step in ionic_step['electronic_steps']:
                    all_energies.append(e_step['E'])
                    current_pos += 1
                step_markers.append(current_pos)

        if len(all_energies) == 0:
            return "No electronic step data found in OSZICAR"

        # Create plot
        fig, ax = plt.subplots(figsize=(14, 7))
        ax.plot(range(len(all_energies)), all_energies, 'b-', linewidth=1.5, alpha=0.8)

        # Mark ionic step boundaries
        for marker in step_markers[1:-1]:
            ax.axvline(x=marker, color='r', linestyle='--', alpha=0.3)

        ax.set_xlabel('Electronic SCF Step (all ionic steps combined)')
        ax.set_ylabel('Energy (eV)')
        ax.set_title('Full Electronic SCF Convergence - All Ionic Steps')
        ax.grid(True, alpha=0.3)

        # Add ionic step markers
        ax.axvline(x=0, color='r', linestyle='--', alpha=0.3, label='Ionic step boundary')
        ax.legend()

        # Add energy change info
        delta_e = abs(all_energies[-1] - all_energies[0])
        ax.text(0.02, 0.98, f'Total energy change: {delta_e:.4f} eV\nFinal energy: {all_energies[-1]:.6f} eV\nIonic steps: {len(step_markers)-1}',
                transform=ax.transAxes, va='top', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created electronic convergence plot:\n- Output PNG: {output_png_path}\n- Total electronic steps: {len(all_energies)}\n- Ionic steps: {len(step_markers)-1}"

    except Exception as e:
        return f"Error creating electronic convergence plot: {str(e)}"


@tool("Plot Force and Stress Convergence")
def plot_force_stress_convergence(
    outcar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot maximum force and stress convergence during ionic relaxation.
    Shows how forces decrease as the structure relaxes to equilibrium.

    Args:
        outcar_path: Path to OUTCAR file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(outcar_path):
        return f"Error: OUTCAR file not found at {outcar_path}"

    try:
        from pymatgen.io.vasp import Outcar
    except ImportError:
        return "Error: pymatgen not installed"

    try:
        outcar = Outcar(outcar_path)

        if not output_png_path:
            base_dir = os.path.dirname(outcar_path)
            output_png_path = os.path.join(base_dir, "force_stress_convergence.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Extract forces from each ionic step
        max_forces = []
        avg_forces = []
        energies = []

        # FIXED: Different pymatgen versions store ionic_steps differently
        if hasattr(outcar, 'ionic_steps'):
            ionic_steps = outcar.ionic_steps
        else:
            # Fallback: read forces from OUTCAR directly if attribute not available
            # Try to get from steps attribute or parse manually
            try:
                ionic_steps = outcar.steps
            except:
                # Last resort: use oszicar to get energy data
                from pymatgen.io.vasp import Oszicar
                try:
                    oszicar = Oszicar(outcar_path.replace('OUTCAR', 'OSZICAR'))
                    for step in oszicar.ionic_steps:
                        if 'E0' in step:
                            energies.append(step['E0'])
                    # If we got energy data from OSZICAR, just plot energy
                    if energies:
                        iterations = list(range(1, len(energies) + 1))
                        fig, ax = plt.subplots(figsize=(12, 7))
                        ax.plot(iterations, energies, 'g-o', linewidth=2, markersize=6)
                        ax.set_xlabel('Ionic Step')
                        ax.set_ylabel('Total Energy (eV)')
                        ax.set_title('Energy Convergence During Relaxation')
                        ax.grid(True, alpha=0.3)
                        fig.tight_layout()
                        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
                        plt.close(fig)
                        return f"Successfully created energy convergence plot (force data not available):\n- Output PNG: {output_png_path}\n- Ionic steps: {len(energies)}"
                except:
                    pass
                return "Error: Could not find ionic step data in OUTCAR. The calculation may be static (not a relaxation)."

        for step in ionic_steps:
            if isinstance(step, dict) and 'forces' in step and step['forces'] is not None:
                forces_np = np.array(step['forces'])
                force_norms = np.linalg.norm(forces_np, axis=1)
                max_forces.append(np.max(force_norms))
                avg_forces.append(np.mean(force_norms))
            if isinstance(step, dict) and 'E0' in step:
                energies.append(step['E0'])

        if not max_forces:
            return "No force data found in OUTCAR"

        iterations = list(range(1, len(max_forces) + 1))

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

        # Forces plot
        ax1.plot(iterations, max_forces, 'r-o', linewidth=2, markersize=6, label='Max force')
        ax1.plot(iterations, avg_forces, 'b-s', linewidth=2, markersize=6, label='Avg force')
        ax1.axhline(y=0.01, color='g', linestyle='--', alpha=0.5, label='Typical convergence (0.01 eV/Å)')
        ax1.set_xlabel('Ionic Step')
        ax1.set_ylabel('Force (eV/Å)')
        ax1.set_title('Force Convergence During Relaxation')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.set_yscale('log')

        # Energy plot
        energies = [step['E0'] for step in outcar.ionic_steps if 'E0' in step]
        if len(energies) == len(iterations):
            ax2.plot(iterations, energies, 'g-o', linewidth=2, markersize=6)
            ax2.set_xlabel('Ionic Step')
            ax2.set_ylabel('Total Energy (eV)')
            ax2.set_title('Energy Convergence')
            ax2.grid(True, alpha=0.3)

        fig.tight_layout()
        plt.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created force/stress convergence plot:\n- Output PNG: {output_png_path}\n- Ionic steps: {len(max_forces)}\n- Final max force: {max_forces[-1]:.6f} eV/Å"

    except Exception as e:
        return f"Error creating force convergence plot: {str(e)}"


@tool("Plot Band Structure + DOS Combined")
def plot_band_dos_combined(
    vasprun_path: str,
    output_png_path: str = ""
) -> str:
    """
    Create a combined plot showing band structure (left) and density of states (right)
    on the same figure with aligned energy axes. This is the standard publication-style
    electronic structure plot.

    Args:
        vasprun_path: Path to vasprun.xml file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(vasprun_path):
        return f"Error: vasprun.xml file not found at {vasprun_path}"

    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.plotter import BSDOSPlotter
    except ImportError:
        return "Error: pymatgen not installed correctly (BSDOSPlotter not available)"

    try:
        vasprun = Vasprun(vasprun_path, parse_projected_eigen=True)
        bs = vasprun.get_band_structure(kpoints_filename=None, line_mode=True)
        dos = vasprun.complete_dos

        if not output_png_path:
            base_dir = os.path.dirname(vasprun_path)
            output_png_path = os.path.join(base_dir, "band_dos_combined.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # FIXED: parameter name is fig_size (with underscore), not figsize
        plotter = BSDOSPlotter(bs_projection=None, dos_projection=None, vb_energy_range=5, cb_energy_range=5, fig_size=(14, 10))
        fig = plotter.get_plot(bs, dos)
        fig.savefig(output_png_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return f"Successfully created combined band structure + DOS plot:\n- Output PNG: {output_png_path}\n- This is publication-quality figure for papers!"

    except Exception as e:
        return f"Error creating band+DOS combined plot: {str(e)}"


@tool("Plot Crystal Structure")
def plot_crystal_structure(
    poscar_path: str,
    output_png_path: str = ""
) -> str:
    """
    Plot 3D crystal structure visualization from POSCAR or CONTCAR file.
    Uses pymatgen's powerful structure plotting capabilities to generate
    publication-quality crystal structure images with bonds and labels.

    Args:
        poscar_path: Path to POSCAR or CONTCAR file
        output_png_path: Optional output PNG path

    Returns:
        Path to the saved PNG image file
    """
    plt = _get_matplotlib()

    if not os.path.exists(poscar_path):
        return f"Error: Structure file not found at {poscar_path}"

    try:
        from pymatgen.io.vasp import Poscar
        from pymatgen.analysis.structure_analyzer import VoronoiConnectivity
    except ImportError:
        return "Error: pymatgen not installed correctly"

    try:
        poscar = Poscar.from_file(poscar_path)
        structure = poscar.structure

        if not output_png_path:
            base_dir = os.path.dirname(poscar_path)
            output_png_path = os.path.join(base_dir, "crystal_structure.png")
        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        # Use pymatgen's StructurePlotter if available, fallback to custom plot
        try:
            from pymatgen.analysis.structure_matcher import StructureMatcher
            from mpl_toolkits.mplot3d import Axes3D

            fig = plt.figure(figsize=(12, 10))
            ax = fig.add_subplot(111, projection='3d')

            # Define colors for common elements
            element_colors = {
                'Si': '#d9d9d9', 'C': '#333333', 'O': '#ff0000', 'N': '#3050f8',
                'H': '#ffffff', 'Li': '#cc80ff', 'Na': '#ab5cf2', 'K': '#8f40d4',
                'Ge': '#666666', 'Ga': '#c28f8f', 'As': '#bd80e3', 'P': '#ffa100',
                'Al': '#bfa6a6', 'Mg': '#8aff00', 'Ca': '#3dff00', 'Sr': '#00ff00',
                'Ti': '#bf8f8f', 'Zr': '#e6e6e6', 'Hf': '#4dc2ff', 'V': '#a6a6ab',
                'Nb': '#73c2c9', 'Ta': '#4da6d9', 'Cr': '#8a99c7', 'Mo': '#54b5b5',
                'W': '#4da6a6', 'Mn': '#9c7ac7', 'Fe': '#e06633', 'Co': '#f090a0',
                'Ni': '#50d050', 'Cu': '#c88033', 'Zn': '#7d80b0', 'Ag': '#c0c0c0',
                'Au': '#ffd123', 'Cd': '#ffd98f', 'Hg': '#b8b8d0', 'In': '#a67573',
                'Tl': '#a6544d', 'Sn': '#668080', 'Pb': '#575961', 'Bi': '#9e4fb5',
                'S': '#ffff30', 'Se': '#ffa100', 'Te': '#d47a00', 'F': '#90e050',
                'Cl': '#1ff01f', 'Br': '#a62929', 'I': '#940094'
            }

            # Plot atoms
            coords = structure.cart_coords
            species = [str(s.specie) for s in structure.sites]

            for i, (x, y, z) in enumerate(coords):
                elem = species[i]
                color = element_colors.get(elem, '#808080')
                size = 150 + (structure.sites[i].specie.number * 2)
                ax.scatter(x, y, z, c=color, s=size, alpha=0.8, edgecolors='black', linewidths=1.5)
                ax.text(x, y, z + 0.3, elem, fontsize=10, ha='center', va='bottom')

            # Draw unit cell box
            lattice = structure.lattice
            vertices = [
                [0, 0, 0], [lattice.a, 0, 0], [lattice.a, lattice.b, 0], [0, lattice.b, 0],
                [0, 0, lattice.c], [lattice.a, 0, lattice.c], [lattice.a, lattice.b, lattice.c], [0, lattice.b, lattice.c]
            ]
            vertices = np.dot(vertices, lattice.matrix)

            # Draw edges
            edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4),
                     (0,4), (1,5), (2,6), (3,7)]
            for i, j in edges:
                ax.plot([vertices[i][0], vertices[j][0]],
                       [vertices[i][1], vertices[j][1]],
                       [vertices[i][2], vertices[j][2]],
                       'k-', alpha=0.5, linewidth=2)

            ax.set_xlabel('X (Å)')
            ax.set_ylabel('Y (Å)')
            ax.set_zlabel('Z (Å)')
            ax.set_title(f'Crystal Structure: {structure.composition.reduced_formula}\n{len(structure)} atoms')

            # Add info text
            info_text = f"Formula: {structure.composition.reduced_formula}\n"
            info_text += f"Space group: {structure.get_space_group_info()[0]}\n"
            info_text += f"Volume: {structure.volume:.2f} Å³\n"
            info_text += f"a = {lattice.a:.3f} Å, b = {lattice.b:.3f} Å, c = {lattice.c:.3f} Å"
            ax.text2D(0.02, 0.02, info_text, transform=ax.transAxes,
                     bbox=dict(boxstyle='round', facecolor='white', alpha=0.9), fontsize=10)

            ax.grid(True, alpha=0.2)
            ax.view_init(elev=20, azim=45)

            fig.tight_layout()
            plt.savefig(output_png_path, dpi=150, bbox_inches='tight', transparent=False)
            plt.close(fig)

        except Exception as e:
            return f"Error in 3D plotting: {str(e)}"

        return f"Successfully created crystal structure plot:\n- Output PNG: {output_png_path}\n- Formula: {structure.composition.reduced_formula}\n- {len(structure)} atoms\n- Space group: {structure.get_space_group_info()[0]}"

    except Exception as e:
        return f"Error creating crystal structure plot: {str(e)}"


@tool("Generate HTML Report with All Plots")
def generate_html_plot_report(
    vasp_output_dir: str,
    job_id: int
) -> str:
    """
    Generate a beautiful HTML report page displaying all the generated VASP plots.
    Creates an interactive gallery of all plots with descriptions and metadata.

    Args:
        vasp_output_dir: Local directory containing VASP output files
        job_id: Job ID

    Returns:
        Path to the generated HTML report file
    """
    current_file = os.path.abspath(__file__)
    tools_dir = os.path.dirname(current_file)
    glass_agent_dir = os.path.dirname(tools_dir)
    src_dir = os.path.dirname(glass_agent_dir)
    project_root = os.path.dirname(src_dir)
    plots_dir = os.path.join(project_root, "output", "vasp_plots", f"job_{job_id}")

    if not os.path.exists(plots_dir):
        return f"Error: Plots directory not found: {plots_dir}"

    # Find all PNG files
    png_files = sorted([f for f in os.listdir(plots_dir) if f.endswith('.png')])

    if not png_files:
        return "Error: No PNG plot files found in the directory"

    # Parse OUTCAR for metadata
    outcar_path = os.path.join(vasp_output_dir, "OUTCAR")
    formula = "Unknown"
    final_energy = "N/A"
    band_gap = "N/A"

    if os.path.exists(outcar_path):
        try:
            from pymatgen.io.vasp import Outcar
            outcar = Outcar(outcar_path)
            if hasattr(outcar, 'structure') and outcar.structure:
                formula = outcar.structure.composition.reduced_formula
            if hasattr(outcar, 'final_energy'):
                final_energy = f"{outcar.final_energy:.4f} eV"
        except:
            pass

    # Create HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VASP Calculation Report - Job {job_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        .header h1 {{
            color: #333;
            font-size: 28px;
            margin-bottom: 20px;
        }}
        .metadata {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .meta-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }}
        .meta-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .meta-value {{
            font-size: 18px;
            font-weight: 600;
            color: #333;
            margin-top: 5px;
        }}
        .gallery {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 25px;
        }}
        .plot-card {{
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        .plot-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.25);
        }}
        .plot-card h3 {{
            color: #333;
            font-size: 18px;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }}
        .plot-card img {{
            width: 100%;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.3s ease;
        }}
        .plot-card img:hover {{
            transform: scale(1.02);
        }}
        .plot-desc {{
            margin-top: 12px;
            color: #666;
            font-size: 13px;
            line-height: 1.5;
        }}
        #lightbox {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }}
        #lightbox img {{
            max-width: 90%;
            max-height: 90%;
            border-radius: 10px;
        }}
        #lightbox.active {{ display: flex; }}
        #lightbox-close {{
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 40px;
            cursor: pointer;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔬 VASP Calculation Report - Job {job_id}</h1>
            <div class="metadata">
                <div class="meta-item">
                    <div class="meta-label">Material</div>
                    <div class="meta-value">{formula}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Job ID</div>
                    <div class="meta-value">{job_id}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Final Energy</div>
                    <div class="meta-value">{final_energy}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Total Plots</div>
                    <div class="meta-value">{len(png_files)} plots</div>
                </div>
            </div>
        </div>

        <div class="gallery">
"""

    # Plot descriptions
    plot_descriptions = {
        '01_energy_convergence': 'Energy convergence during ionic relaxation. Shows how the total energy decreases and stabilizes.',
        '02_electronic_convergence_detailed': 'Detailed electronic SCF convergence. Shows every self-consistent field step.',
        '03_force_stress_convergence': 'Maximum force on atoms during relaxation. Shows convergence to equilibrium geometry.',
        '04_total_dos': 'Total electronic density of states. Shows the distribution of electron energy levels in the material.',
        '05_elemental_pdos': 'Elemental partial density of states. Shows which elements contribute most to each energy level.',
        '06_orbital_pdos': 'Orbital-resolved partial density of states. Shows s, p, d orbital contributions.',
        '07_band_structure': 'Electronic band structure. Shows energy bands along high-symmetry k-point paths.',
        '08_band_dos_combined': '✭ Publication-quality combined band structure + DOS plot. Standard for scientific papers.',
        'crystal_structure': '3D visualization of the crystal structure showing atom positions and unit cell.',
    }

    for png_file in png_files:
        plot_name = png_file.replace('.png', '')
        title = plot_name.replace('_', ' ').title()
        description = ''
        for key, desc in plot_descriptions.items():
            if key in png_file:
                description = desc
                break

        html_content += f"""
            <div class="plot-card">
                <h3>{title}</h3>
                <img src="{png_file}" onclick="openLightbox('{png_file}')">
                <p class="plot-desc">{description}</p>
            </div>
"""

    html_content += """
        </div>
    </div>

    <div id="lightbox" onclick="closeLightbox()">
        <span id="lightbox-close">&times;</span>
        <img id="lightbox-img" src="" alt="">
    </div>

    <script>
        function openLightbox(src) {
            document.getElementById('lightbox-img').src = src;
            document.getElementById('lightbox').classList.add('active');
        }
        function closeLightbox() {
            document.getElementById('lightbox').classList.remove('active');
        }
    </script>
</body>
</html>
"""

    # Save HTML file
    html_path = os.path.join(plots_dir, "vasp_report.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return f"""✅ Beautiful HTML report generated!

📁 Report location: {html_path}
🖼️ Plots included: {len(png_files)}

You can now open the HTML file in your browser to see all plots in a beautiful interactive gallery!"""


@tool("Generate All VASP Summary Plots")
def plot_vasp_summary_plots(
    vasp_output_dir: str,
    job_id: int
) -> str:
    """
    Generate ALL available summary plots from a completed VASP calculation.
    Creates organized output directory under output/vasp_plots/job_{job_id}/
    and generates ALL plots for which the required input files exist.

    Available plots:
    - Energy convergence (ionic steps)
    - Full electronic SCF convergence (detailed)
    - Force and stress convergence
    - Total density of states
    - Full elemental partial density of states
    - Orbital-resolved PDOS (s, p, d orbitals)
    - Band structure
    - Combined band structure + DOS (publication quality)

    Args:
        vasp_output_dir: Local directory containing VASP output files (OUTCAR, OSZICAR, etc.)
        job_id: Job ID (used for organizing output directory)

    Returns:
        Summary of all plots generated
    """
    # Create output directory
    current_file = os.path.abspath(__file__)
    tools_dir = os.path.dirname(current_file)
    glass_agent_dir = os.path.dirname(tools_dir)
    src_dir = os.path.dirname(glass_agent_dir)
    project_root = os.path.dirname(src_dir)
    output_dir = os.path.join(project_root, "output", "vasp_plots", f"job_{job_id}")
    os.makedirs(output_dir, exist_ok=True)

    summary = f"===== Generating ALL VASP Summary Plots for job {job_id} =====\n"
    summary += f"Output directory: {output_dir}\n\n"

    generated = []
    failed = []

    # 1. Energy convergence from OSZICAR
    oszicar_path = os.path.join(vasp_output_dir, "OSZICAR")
    if os.path.exists(oszicar_path):
        result = plot_energy_convergence.func(oszicar_path, os.path.join(output_dir, "01_energy_convergence.png"))
        if "Successfully" in result:
            generated.append("Energy convergence")
        else:
            failed.append(f"Energy convergence: {result}")
    else:
        failed.append("Energy convergence: OSZICAR not found")

    # 2. Detailed electronic SCF convergence
    if os.path.exists(oszicar_path):
        result = plot_electronic_convergence.func(oszicar_path, os.path.join(output_dir, "02_electronic_convergence_detailed.png"))
        if "Successfully" in result:
            generated.append("Detailed electronic SCF convergence")
        else:
            failed.append(f"Electronic convergence: {result}")

    # 3. Force and stress convergence
    outcar_path = os.path.join(vasp_output_dir, "OUTCAR")
    if os.path.exists(outcar_path):
        result = plot_force_stress_convergence.func(outcar_path, os.path.join(output_dir, "03_force_stress_convergence.png"))
        if "Successfully" in result:
            generated.append("Force & stress convergence")
        else:
            failed.append(f"Force convergence: {result}")

    # 3b. Crystal structure from CONTCAR or POSCAR
    contcar_path = os.path.join(vasp_output_dir, "CONTCAR")
    poscar_path = os.path.join(vasp_output_dir, "POSCAR")
    structure_path = contcar_path if os.path.exists(contcar_path) else poscar_path
    if os.path.exists(structure_path):
        result = plot_crystal_structure.func(structure_path, os.path.join(output_dir, "00_crystal_structure.png"))
        if "Successfully" in result:
            generated.append("Crystal structure (3D visualization)")
        else:
            failed.append(f"Crystal structure: {result}")

    # 4. Check vasprun.xml for electronic structure plots
    vasprun_path = os.path.join(vasp_output_dir, "vasprun.xml")
    if os.path.exists(vasprun_path):
        # 4a. Total DOS
        result = plot_density_of_states.func(vasprun_path, os.path.join(output_dir, "04_total_dos.png"))
        if "Successfully" in result:
            generated.append("Total density of states")
        else:
            failed.append(f"Total DOS: {result}")

        # 4b. Full elemental PDOS
        result = plot_full_dos.func(vasprun_path, os.path.join(output_dir, "05_elemental_pdos.png"))
        if "Successfully" in result:
            generated.append("Elemental partial DOS")
        else:
            failed.append(f"Elemental PDOS: {result}")

        # 4c. Orbital PDOS
        result = plot_orbital_pdos.func(vasprun_path, os.path.join(output_dir, "06_orbital_pdos.png"))
        if "Successfully" in result:
            generated.append("Orbital-resolved PDOS")
        else:
            failed.append(f"Orbital PDOS: {result}")

        # 4d. Band structure
        result = plot_band_structure_projected.func(vasprun_path, os.path.join(output_dir, "07_band_structure.png"))
        if "Successfully" in result:
            generated.append("Band structure")
        else:
            failed.append(f"Band structure: {result}")

        # 4e. Combined band + DOS (publication quality!)
        result = plot_band_dos_combined.func(vasprun_path, os.path.join(output_dir, "08_band_dos_combined.png"))
        if "Successfully" in result:
            generated.append("✭ Band + DOS combined (publication-quality!)")
        else:
            failed.append(f"Combined band+DOS: {result}")
    else:
        failed.append("Electronic structure plots: vasprun.xml not found")

    # Final summary
    summary += f"✅ SUCCESSFULLY GENERATED ({len(generated)} plots):\n"
    for i, plot in enumerate(generated, 1):
        summary += f"  {i}. {plot}\n"

    if failed:
        summary += f"\n⚠️ Not generated/missing ({len(failed)}):\n"
        for msg in failed:
            summary += f"  - {msg}\n"

    # Generate HTML report
    html_result = generate_html_plot_report.func(vasp_output_dir, job_id)
    summary += f"\n================================================================\n"
    summary += f"📁 All high-quality plots saved to: {output_dir}/\n"
    summary += f"🎨 Total plots generated: {len(generated)}\n\n"
    summary += html_result
    return summary
