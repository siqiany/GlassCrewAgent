"""
VASP Platform Interaction Module
=================================

This module handles all interactions with the supercomputing platform, including:
- SSH and API connection management
- File upload and download
- Job submission, monitoring, and cancellation
- Queue/partition information retrieval

This is the lowest-level module in the VASP toolchain - it only handles platform
interaction, not VASP input generation or result analysis.
"""

import os
import time
import hmac
import hashlib
import json
import requests
import paramiko
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
    """Get connection mode from environment variable: 'ssh' or 'api'"""
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
    script_content: str,
    queue: str,
    nodes: int,
    ppn: int,
    wall_time: str = "24:00:00",
    job_name: str = "vasp_calculation"
) -> Tuple[Optional[str], str]:
    """
    Submit VASP job via API using cmd mode (GAP_CMD_FILE).

    In cmd mode, the script content is passed directly as a string
    (with \n for newlines) in GAP_CMD_FILE. The platform embeds it
    between # MARK_CMD / # MARK_BASH in its BASE template and executes it.

    Args:
        remote_work_dir: Remote working directory path
        script_content: Pure shell command string (no #!/bin/bash, no #SBATCH)
        queue: SLURM queue/partition name
        nodes: Number of nodes
        ppn: Tasks per node
        wall_time: Wall time limit (HH:MM:SS)
        job_name: Job name

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

    # API job submission parameters (per scnet.cn openapi doc v2.0)
    payload = {
        "strJobManagerID": _api_job_manager_id,
        "mapAppJobInfo": {
            "GAP_SUBMIT_TYPE": "cmd",
            "GAP_CMD_FILE": script_content,
            "GAP_APPNAME": "VASP",
            "GAP_JOB_NAME": job_name,
            "GAP_PPN": str(ppn),
            "GAP_NNODE": str(nodes),
            "GAP_WALL_TIME": wall_time,
            "GAP_WORK_DIR": remote_work_dir,
            "GAP_QUEUE": queue,
            "GAP_STD_OUT_FILE": f"{remote_work_dir}/std.out.%j",
            "GAP_STD_ERR_FILE": f"{remote_work_dir}/std.err.%j",
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


# =============================================================================
# SSH Connection Management
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


# =============================================================================
# Local Directory Management (shared with other modules)
# =============================================================================

def _get_local_job_dir(job_id: Optional[int] = None) -> str:
    """Get or create local directory for VASP calculation"""
    # Always use consistent location: src/data/vasp_calculations
    # This matches the project's data directory organization
    file_abs_path = os.path.abspath(__file__)
    # vasp_platform.py is at src/GlassCrewAgent/tools/ -> go up two levels to src/
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
# Job Management Tools
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

    # Extract the job directory name from local_input_dir
    # Supports both flat (job_timestamp/input) and nested (job_timestamp/relax/input) layouts
    # Flat:    /path/to/job_YYYYMMDD_HHMMSS/input         → job_YYYYMMDD_HHMMSS
    # Nested:  /path/to/job_YYYYMMDD_HHMMSS/relax/input   → job_YYYYMMDD_HHMMSS/relax
    parent_dir = os.path.dirname(local_input_dir)
    job_dir_name = os.path.basename(parent_dir)
    grandparent_dir = os.path.dirname(parent_dir)
    grandparent_name = os.path.basename(grandparent_dir)
    if grandparent_name.startswith('job_'):
        job_dir_name = f"{grandparent_name}/{job_dir_name}"

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

        # Read vasp.slurm content as string for GAP_CMD_FILE (cmd mode)
        # In cmd mode, the platform embeds this between # MARK_CMD / # MARK_BASH
        slurm_local_path = os.path.join(local_input_dir, "vasp.slurm")
        if not os.path.exists(slurm_local_path):
            return f"Error: vasp.slurm not found in {local_input_dir}. Did you generate it with generate_slurm_script?"

        with open(slurm_local_path, 'r') as f:
            script_content = f.read()

        job_name = f"vasp_{job_dir_name}"

        # Submit job via API (pass script as string, not file path)
        job_id, err = _api_submit_job(
            remote_work_dir=remote_dir,
            script_content=script_content,
            queue=partition,
            nodes=nodes,
            ppn=tasks_per_node,
            wall_time="24:00:00",
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
# Result Download Tools
# =============================================================================

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
        'OUTCAR', 'CONTCAR', 'OSZICAR', 'INCAR', 'KPOINTS', 'POSCAR',
        'XDATCAR', 'CHGCAR', 'WAVECAR', 'PROCAR', 'vasprun.xml',
        'EIGENVAL', 'DOSCAR', 'IBZKPT', 'POTCAR', 'REPORT',
        # Slurm output files (multiple naming conventions)
        f'std.out.{job_id}', f'std.err.{job_id}',
        f'slurm-{job_id}.out', f'slurm-{job_id}.err',
        f'job.{job_id}.out', f'job.{job_id}.err',
        f'vasp.{job_id}.out', f'vasp.{job_id}.err'
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
            vasp_prefixes = ['OUTCAR', 'CONTCAR', 'OSZICAR', 'INCAR', 'KPOINTS',
                           'POSCAR', 'XDATCAR', 'CHGCAR', 'WAVECAR', 'PROCAR',
                           'vasprun', 'EIGENVAL', 'DOSCAR', 'IBZKPT', 'POTCAR']
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
            summary += "\n⚠️ WARNING: No files were downloaded!\n"
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
            summary += "\n⚠️ WARNING: No files were downloaded!\n"
            summary += "Please verify:\n"
            summary += "  1. Remote directory path is correct\n"
            summary += "  2. Job has completed and output files exist\n"
            summary += "  3. Files are not stored in a subdirectory\n"

        return summary


# =============================================================================
# Module Exports
# =============================================================================

# List of all tools and functions to export
__all__ = [
    # Core connection functions
    '_get_api_connection_mode',
    '_api_get_token',
    '_get_ssh',
    '_get_local_job_dir',

    # API internal functions (exported for module dependency)
    '_api_create_directory',
    '_api_check_file_exists',
    '_api_upload_file',
    '_api_download_file',
    '_api_list_queues',
    '_api_submit_job',
    '_api_get_job_status',
    '_api_cancel_job',
    '_api_list_directory',

    # Public tools
    'test_connection',
    'test_ssh_connection',
    'list_available_partitions',
    'submit_vasp_job',
    'check_job_status',
    'cancel_job',
    'download_vasp_results',
]
