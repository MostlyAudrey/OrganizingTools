#!/usr/bin/env python3
"""Serve the organizer tools site and start one Signal DMER environment per user.

Each name gets its own virtual environment, signal-cli config, and CSV folder so
one person's linked Signal account is not shared with anyone else.

    python tools/serve_organizer_tools.py

Then open http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
APP_ROOT = REPO_ROOT / "tools" / "signal_dmer"
RUNTIME_ROOT = REPO_ROOT / "runtime" / "signal_dmer_users"
REQUIREMENTS = APP_ROOT / "requirements.txt"
UI_SCRIPT = APP_ROOT / "signal_dmer_ui.py"
HOST = "127.0.0.1"
PORT_START = 8600
PORT_END = 8699

ENDED_MESSAGE = (
    "Session ended. The environment, Signal login, and exported files for this name were deleted."
)


class SessionEnded(Exception):
    """The user ended this session while it was starting."""


def _candidates() -> list[Path]:
    found: list[Path] = []
    env = os.environ.get("SIGNAL_DMER_HOME")
    if env:
        found.append(Path(env).expanduser())
    found.append(Path(r"C:\Users\byarm\Desktop\Apps\signal_dmer"))
    found.append(Path("/mnt/c/Users/byarm/Desktop/Apps/signal_dmer"))
    return found


def signal_cli_executable(home: Path) -> Optional[Path]:
    if sys.platform == "win32":
        path = home / "signal-cli-0.14.8" / "bin" / "signal-cli.bat"
    elif sys.platform == "linux":
        native = home / "signal-cli-0.14.8-Linux-native" / "signal-cli"
        shell = home / "signal-cli-0.14.8" / "bin" / "signal-cli"
        if native.is_file():
            return native
        path = shell
    else:
        path = home / "signal-cli-0.14.8" / "bin" / "signal-cli"
    return path if path.is_file() else None


def find_signal_dmer_home() -> Optional[Path]:
    for candidate in _candidates():
        if signal_cli_executable(candidate):
            return candidate.resolve()
    return None


def slugify(name: str) -> str:
    cleaned = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    if not slug or len(slug) > 40:
        raise ValueError("Use a name with letters or numbers, up to 40 characters.")
    return slug


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_pid(pid: int) -> None:
    if pid <= 0 or not pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    try:
        os.killpg(pid, 15)
    except OSError:
        try:
            os.kill(pid, 15)
        except OSError:
            return
    for _ in range(20):
        if not pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, 9)
    except OSError:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def reserve_port(used: set[int]) -> int:
    for port in range(PORT_START, PORT_END + 1):
        if port in used:
            continue
        if port_free(port):
            return port
    raise RuntimeError("No free local port between 8600 and 8699.")


def streamlit_healthy(port: int) -> bool:
    url = f"http://{HOST}:{port}/_stcore/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return

    def onexc(func: Any, failed: str, exc: BaseException) -> None:
        try:
            os.chmod(failed, stat.S_IWRITE)
            func(failed)
        except Exception:
            raise exc

    last: Optional[BaseException] = None
    for _ in range(12):
        try:
            shutil.rmtree(path, onexc=onexc)
            return
        except Exception as exc:
            last = exc
            time.sleep(0.4)
    raise RuntimeError(f"Could not delete session data at {path}: {last}")


def tail_text(path: Path, limit: int = 1800) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


class SessionBook:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._cancel: set[str] = set()
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)

    def public(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": job["id"],
            "name": job["name"],
            "status": job["status"],
            "message": job["message"],
            "url": job.get("url"),
            "detail": job.get("detail") or "",
        }

    def get(self, slug: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(slug)
            if not job:
                return None
            self._refresh_ready(job)
            return self.public(job)

    def open(self, name: str) -> Dict[str, Any]:
        slug = slugify(name)
        with self._lock:
            job = self._jobs.get(slug)
            if job and job["status"] in ("installing", "starting"):
                return self.public(job)
            if job and job["status"] == "ready" and self._refresh_ready(job):
                return self.public(job)
            loaded = self._load_disk(slug, name)
            if loaded and loaded["status"] == "ready":
                self._jobs[slug] = loaded
                return self.public(loaded)
            job = {
                "id": slug,
                "name": name.strip(),
                "status": "installing",
                "message": "Creating a private Python environment for this name.",
                "url": None,
                "detail": "",
                "port": None,
                "pid": None,
                "pids": [],
            }
            self._jobs[slug] = job
            thread = threading.Thread(target=self._launch, args=(slug,), daemon=True)
            job["thread"] = thread
            thread.start()
            return self.public(job)

    def stop(self, slug: str) -> Dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", slug):
            raise ValueError("Unknown session.")
        with self._lock:
            job = self._jobs.get(slug) or self._load_disk(slug, slug)
            user_dir = self._user_dir(slug)
            if job is None and not user_dir.exists():
                raise ValueError("No Signal DMER session for that name.")
            if job is None:
                job = {
                    "id": slug,
                    "name": slug,
                    "status": "ended",
                    "message": "",
                    "pids": [],
                }
                self._jobs[slug] = job
            self._cancel.add(slug)
            pids = [int(pid) for pid in job.get("pids") or []]
            if job.get("pid"):
                pids.append(int(job["pid"]))
            thread = job.get("thread")
            name = job.get("name") or slug
        for pid in pids:
            stop_pid(pid)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=30)
        self._wipe(slug)
        ended = {
            "id": slug,
            "name": name,
            "status": "ended",
            "message": ENDED_MESSAGE,
            "url": None,
            "detail": "",
            "port": None,
            "pid": None,
            "pids": [],
            "thread": None,
        }
        with self._lock:
            self._jobs[slug] = ended
            self._cancel.discard(slug)
        return self.public(ended)

    def _refresh_ready(self, job: Dict[str, Any]) -> bool:
        if job.get("status") != "ready":
            return False
        port = job.get("port")
        pid = int(job.get("pid") or 0)
        if port and pid_alive(pid) and streamlit_healthy(int(port)):
            return True
        job["status"] = "stopped"
        job["message"] = "Signal DMER stopped. Open it again with the same name."
        job["url"] = None
        return False

    def _user_dir(self, slug: str) -> Path:
        return RUNTIME_ROOT / slug

    def _raise_if_cancelled(self, slug: str) -> None:
        if slug in self._cancel:
            raise SessionEnded()

    def _remember_pid(self, slug: str, pid: int) -> None:
        with self._lock:
            job = self._jobs.get(slug)
            if not job:
                return
            pids = job.setdefault("pids", [])
            if pid not in pids:
                pids.append(pid)

    def _wipe(self, slug: str) -> None:
        user_dir = self._user_dir(slug)
        root = RUNTIME_ROOT.resolve()
        resolved = user_dir.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError(f"Refusing to delete {resolved}")
        pids: list[int] = []
        with self._lock:
            job = self._jobs.get(slug) or {}
            pids.extend(int(pid) for pid in job.get("pids") or [])
            if job.get("pid"):
                pids.append(int(job["pid"]))
        session_file = user_dir / "session.json"
        if session_file.is_file():
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                if data.get("pid"):
                    pids.append(int(data["pid"]))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        for pid in pids:
            stop_pid(pid)
        _remove_tree(resolved)

    def _load_disk(self, slug: str, name: str) -> Optional[Dict[str, Any]]:
        path = self._user_dir(slug) / "session.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        pid = int(data.get("pid") or 0)
        port = data.get("port")
        job = {
            "id": slug,
            "name": data.get("name") or name,
            "status": "stopped",
            "message": "Open Signal DMER to start this name's environment.",
            "url": None,
            "detail": "",
            "port": port,
            "pid": pid,
        }
        if port and pid_alive(pid) and streamlit_healthy(int(port)):
            job["status"] = "ready"
            job["url"] = f"http://{HOST}:{port}"
            job["message"] = "This name already has Signal DMER running."
        return job

    def _write_session(self, slug: str, job: Dict[str, Any]) -> None:
        path = self._user_dir(slug) / "session.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": job["name"],
            "pid": job.get("pid"),
            "port": job.get("port"),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _used_ports(self) -> set[int]:
        used: set[int] = set()
        for job in self._jobs.values():
            if job.get("port"):
                used.add(int(job["port"]))
        if RUNTIME_ROOT.is_dir():
            for session_file in RUNTIME_ROOT.glob("*/session.json"):
                try:
                    data = json.loads(session_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                port = data.get("port")
                pid = int(data.get("pid") or 0)
                if port and pid_alive(pid):
                    used.add(int(port))
        return used

    def _launch(self, slug: str) -> None:
        user_dir = self._user_dir(slug)
        data_dir = user_dir / "signal_cli_data"
        config_dir = user_dir / "signal-cli-config"
        venv = user_dir / ".venv"
        install_log = user_dir / "install.log"
        streamlit_log = user_dir / "streamlit.log"
        try:
            self._raise_if_cancelled(slug)
            home = find_signal_dmer_home()
            if home is None:
                raise RuntimeError(
                    "signal-cli was not found. Set SIGNAL_DMER_HOME to the signal_dmer folder "
                    "that contains signal-cli-0.14.8."
                )
            if not UI_SCRIPT.is_file() or not REQUIREMENTS.is_file():
                raise RuntimeError("Signal DMER files are missing from tools/signal_dmer.")
            user_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            config_dir.mkdir(parents=True, exist_ok=True)
            self._set(slug, message="Creating a private Python environment for this name.", detail="")
            python = self._ensure_venv(slug, venv, install_log)
            self._raise_if_cancelled(slug)
            with self._lock:
                self._raise_if_cancelled(slug)
                port = reserve_port(self._used_ports())
                self._jobs[slug]["port"] = port
            self._set(slug, status="starting", message="Starting Signal DMER for this name.")
            pid = self._start_streamlit(
                python=python,
                port=port,
                user_dir=user_dir,
                data_dir=data_dir,
                config_dir=config_dir,
                home=home,
                slug=slug,
                log_path=streamlit_log,
            )
            self._remember_pid(slug, pid)
            with self._lock:
                if slug in self._cancel:
                    raise SessionEnded()
                self._jobs[slug]["pid"] = pid
                self._write_session(slug, self._jobs[slug])
            self._wait_until_ready(slug, port, pid, streamlit_log)
        except SessionEnded:
            return
        except Exception as exc:
            if slug in self._cancel:
                return
            detail = tail_text(install_log) or tail_text(streamlit_log)
            self._set(
                slug,
                status="error",
                message=str(exc),
                url=None,
                detail=detail,
            )

    def _set(self, slug: str, **fields: Any) -> None:
        with self._lock:
            if slug in self._cancel:
                return
            job = self._jobs.get(slug)
            if not job:
                return
            job.update(fields)

    def _run_cancellable(
        self,
        slug: str,
        cmd: list[str],
        log_handle: Any,
        *,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 900,
    ) -> None:
        self._raise_if_cancelled(slug)
        proc = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )
        self._remember_pid(slug, proc.pid)
        deadline = time.time() + timeout
        while proc.poll() is None:
            if slug in self._cancel:
                stop_pid(proc.pid)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
                raise SessionEnded()
            if time.time() > deadline:
                stop_pid(proc.pid)
                raise TimeoutError(f"Command timed out: {cmd[0]}")
            time.sleep(0.25)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)

    def _ensure_venv(self, slug: str, venv: Path, install_log: Path) -> Path:
        python = venv_python(venv)
        stamp = venv / "requirements.sha256"
        wanted = requirements_hash()
        if python.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == wanted:
            return python
        if venv.exists() and not python.is_file():
            shutil.rmtree(venv)
        install_log.parent.mkdir(parents=True, exist_ok=True)
        with install_log.open("a", encoding="utf-8") as log:
            if not python.is_file():
                log.write("Creating virtual environment\n")
                log.flush()
                self._run_cancellable(
                    slug,
                    [sys.executable, "-m", "venv", str(venv)],
                    log,
                    timeout=180,
                )
            self._raise_if_cancelled(slug)
            python = venv_python(venv)
            if not python.is_file():
                raise RuntimeError(f"Virtual environment did not create {python}")
            log.write("Installing Signal DMER packages\n")
            log.flush()
            env = os.environ.copy()
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            cache = REPO_ROOT / "runtime" / "pip-cache"
            cache.mkdir(parents=True, exist_ok=True)
            env["PIP_CACHE_DIR"] = str(cache)
            self._run_cancellable(
                slug,
                [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
                log,
                env=env,
                timeout=900,
            )
        stamp.write_text(wanted, encoding="utf-8")
        return python

    def _start_streamlit(
        self,
        *,
        python: Path,
        port: int,
        user_dir: Path,
        data_dir: Path,
        config_dir: Path,
        home: Path,
        slug: str,
        log_path: Path,
    ) -> int:
        env = os.environ.copy()
        env["SIGNAL_DM_DATA_DIR"] = str(data_dir)
        env["SIGNAL_CLI_CONFIG"] = str(config_dir)
        env["SIGNAL_DM_LOG"] = str(user_dir / "signal_dm.log")
        env["SIGNAL_DMER_HOME"] = str(home)
        env["SIGNAL_CLI_LINK_NAME"] = f"organizer-{slug}"[:40]
        env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [
            str(python),
            "-m",
            "streamlit",
            "run",
            str(UI_SCRIPT),
            "--server.headless",
            "true",
            "--server.address",
            HOST,
            "--server.port",
            str(port),
            "--browser.gatherUsageStats",
            "false",
            "--server.enableCORS",
            "false",
            "--server.enableXsrfProtection",
            "false",
            "--server.fileWatcherType",
            "none",
        ]
        log_handle = log_path.open("a", encoding="utf-8")
        kwargs: Dict[str, Any] = {
            "cwd": str(user_dir),
            "env": env,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(cmd, **kwargs)
        log_handle.close()
        self._remember_pid(slug, process.pid)
        return process.pid

    def _wait_until_ready(self, slug: str, port: int, pid: int, log_path: Path) -> None:
        deadline = time.time() + 90
        while time.time() < deadline:
            self._raise_if_cancelled(slug)
            if not pid_alive(pid):
                raise RuntimeError("Signal DMER exited before it was ready. See the log below.")
            if streamlit_healthy(port):
                url = f"http://{HOST}:{port}"
                with self._lock:
                    if slug in self._cancel:
                        raise SessionEnded()
                    job = self._jobs.get(slug)
                    if not job:
                        raise SessionEnded()
                    job.update(
                        {
                            "status": "ready",
                            "message": "Signal DMER is ready. Link this name's Signal account inside the app.",
                            "url": url,
                            "detail": "",
                        }
                    )
                    self._write_session(slug, job)
                return
            time.sleep(0.5)
        raise RuntimeError("Signal DMER did not become ready in time.")


BOOK = SessionBook()


class Handler(BaseHTTPRequestHandler):
    server_version = "OrganizerTools/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 8000:
            raise ValueError("Request is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Send a JSON body with a name.") from exc
        if not isinstance(data, dict):
            raise ValueError("Send a JSON object.")
        return data

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/signal-dmer/session/"):
            slug = parsed.path.rstrip("/").split("/")[-1]
            if not re.fullmatch(r"[a-z0-9-]{1,40}", slug):
                self._send_json(400, {"status": "error", "message": "Unknown session."})
                return
            job = BOOK.get(slug)
            if not job:
                self._send_json(404, {"status": "error", "message": "No session for that name yet."})
                return
            self._send_json(200, job)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/signal-dmer/session":
                data = self._read_json()
                name = str(data.get("name") or "")
                self._send_json(200, BOOK.open(name))
                return
            match = re.fullmatch(r"/api/signal-dmer/session/([a-z0-9-]{1,40})/stop", parsed.path)
            if match:
                self._send_json(200, BOOK.stop(match.group(1)))
                return
        except ValueError as exc:
            self._send_json(400, {"status": "error", "message": str(exc)})
            return
        except Exception as exc:
            self._send_json(500, {"status": "error", "message": str(exc)})
            return
        self._send_json(404, {"status": "error", "message": "Unknown API path."})

    def _serve_static(self, raw_path: str) -> None:
        rel = unquote(raw_path.split("?", 1)[0])
        if rel in ("", "/"):
            rel = "/index.html"
        rel = rel.lstrip("/")
        target = (DOCS_ROOT / rel).resolve()
        try:
            target.relative_to(DOCS_ROOT.resolve())
        except ValueError:
            self.send_error(403)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve organizer tools, including per-user Signal DMER.")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    home = find_signal_dmer_home()
    if home:
        print(f"Signal DMER binaries: {home}")
    else:
        print("Signal DMER binaries were not found. Set SIGNAL_DMER_HOME before opening that tool.")
    print(f"Organizer tools: http://{HOST}:{args.port}")
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
