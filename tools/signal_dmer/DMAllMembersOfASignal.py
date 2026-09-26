#!/usr/bin/env python3
"""
Signal Group DM Script
======================
This script allows you to:
1. Get all members of a Signal group
2. Send a direct message to each member

Requirements:
- signal-cli (bundled layout per OS; see README / QUICKSTART)
- Windows: JDK 25+ for ``signal-cli.bat`` (bundled ``jdk-25`` folder optional)
- Linux: prefer ``signal-cli-0.14.8-Linux-native/signal-cli`` when it runs (no JDK); else ``signal-cli-0.14.8/bin/signal-cli`` (JDK 25+). The ``-Linux-client`` binary is not used (JSON-RPC daemon client only).
- You must be registered with Signal and have access to the group

Usage:
    python DMAllMembersOfASignal.py
"""

import subprocess
import json
import sys
import time
import logging
import stat
import shutil
from typing import List, Dict, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from __main__ import SignalCLI
import os
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import random
import csv
from datetime import datetime
import re


def _project_root() -> Path:
    """Folder that contains signal-cli. Honors SIGNAL_DMER_HOME when the UI is launched per user."""
    env = os.environ.get("SIGNAL_DMER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent


def _linux_signal_cli_binary_runs(exe: Path) -> bool:
    """True if ``exe`` runs (e.g. Graal ``Linux-native`` build); false on GLIBC mismatch, etc."""
    if not exe.is_file():
        return False
    try:
        r = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_signal_cli_linux_native_executable(executable: Path) -> bool:
    """Graal native ``signal-cli`` (no JVM); lives under a ``*-Linux-native`` directory."""
    if sys.platform == "win32":
        return False
    return executable.name == "signal-cli" and "linux-native" in executable.parent.name.lower()


def default_signal_cli_path() -> Path:
    """
    Pick the signal-cli executable shipped with this project.

    - Windows: ``signal-cli-0.14.8/bin/signal-cli.bat`` (uses JAVA_HOME or PATH java).
    - Linux: ``signal-cli-0.14.8-Linux-native/signal-cli`` when present and runnable (no JDK);
      else ``signal-cli-0.14.8/bin/signal-cli`` (JVM). We do not use ``signal-cli-client``
      (JSON-RPC to ``signal-cli daemon`` only).
    - macOS: ``signal-cli-0.14.8/bin/signal-cli`` (unpack a macOS build if needed).
    """
    root = _project_root()
    if sys.platform == "win32":
        return root / "signal-cli-0.14.8" / "bin" / "signal-cli.bat"
    if sys.platform == "linux":
        native = root / "signal-cli-0.14.8-Linux-native" / "signal-cli"
        shell = root / "signal-cli-0.14.8" / "bin" / "signal-cli"
        client = root / "signal-cli-0.14.8-Linux-client" / "signal-cli-client"

        if native.is_file() and _linux_signal_cli_binary_runs(native):
            return native
        if shell.is_file():
            if native.is_file():
                logging.getLogger(__name__).info(
                    "Using ``signal-cli-0.14.8/bin/signal-cli``: Linux-native binary did not run on this OS "
                    "(often GLIBC); JVM build + JDK 25 is required."
                )
            return shell
        if native.is_file():
            logging.getLogger(__name__).error(
                "``signal-cli-0.14.8-Linux-native/signal-cli`` is present but does not run here "
                "(GLIBC mismatch is common on older distros / WSL).\n"
                "Install the full ``signal-cli-*-Linux.tar.gz`` as ``signal-cli-0.14.8/`` with ``bin/signal-cli`` "
                "and JDK 25 on PATH, or use a newer Linux environment for the native build."
            )
            raise SystemExit(1)
        if client.is_file():
            logging.getLogger(__name__).error(
                "Found ``signal-cli-client`` but not ``signal-cli-0.14.8/bin/signal-cli``.\n"
                "The ``*-Linux-client.tar.gz`` build is only a JSON-RPC client (talks to "
                "``signal-cli daemon`` over a Unix socket). This script needs the full "
                "``signal-cli-*-Linux.tar.gz`` archive: extract it as ``signal-cli-0.14.8/`` "
                "next to this script so ``bin/signal-cli`` exists, with JDK 25 on PATH."
            )
            raise SystemExit(1)
        return shell
    return root / "signal-cli-0.14.8" / "bin" / "signal-cli"


def use_shell_for_signal_cli(executable: Union[str, Path]) -> bool:
    """Windows ``.bat`` launchers must run with ``shell=True`` for ``subprocess``."""
    return sys.platform == "win32" and str(executable).lower().endswith(".bat")


def _pip_install_qrcode_instructions() -> str:
    """Human-readable install hint for ``qrcode`` / ``Pillow`` (varies by OS)."""
    if sys.platform == "win32":
        return (
            "  Windows (PowerShell or Command Prompt):\n"
            '    python -m pip install "qrcode[pil]" pillow\n'
            "  If ``python`` is not found, try:\n"
            '    py -m pip install "qrcode[pil]" pillow'
        )
    return (
        "  Debian / Ubuntu (PEP 668 — ``externally-managed-environment``): use a venv in this folder:\n"
        "    sudo apt install python3-venv python3-tk\n"
        "    python3 -m venv .venv && . .venv/bin/activate\n"
        "    pip install 'qrcode[pil]' pillow\n"
        "    python3 DMAllMembersOfASignal.py   # or: .venv/bin/python3 DMAllMembersOfASignal.py\n"
        "  Or install only from apt (no pip; QR popup needs Tk):\n"
        "    sudo apt install python3-qrcode python3-pil python3-tk\n"
        "  Other Linux / macOS (if ``pip install`` is allowed):\n"
        "    python3 -m pip install 'qrcode[pil]' pillow\n"
        "  Fedora (RPM):\n"
        "    sudo dnf install python3-pip python3-qrcode python3-pillow python3-tkinter"
    )


def _print_manual_linking_qr_help(url: str) -> None:
    """When the in-app QR window cannot run, tell the user how to link using a browser-based QR."""
    print("\n" + "=" * 60)
    print("MANUAL QR (browser)")
    print("=" * 60)
    print("\n1. Copy the link at the bottom (your Signal link-device URI).")
    print(
        "\n2. In a browser, open https://goqr.me/ — use plain text / data mode, paste the full link "
        "(including ``sgnl://``), generate a QR, then scan it with Signal on your phone:"
    )
    print("\n3. Phone: Signal → Settings → Linked devices → Link new device → scan that QR.")
    print("\n4. Leave this terminal alone until the phone finishes linking — do not close it yet.")
    print("\nYour link (copy all of it):")
    print(f"   {url}")


def _prompt_qr_linking_fallback(url: str) -> str:
    """
    After the QR popup fails, ask whether to continue with a manual QR or stop to install deps.

    Returns:
        ``manual`` — user completes linking in the browser; keep ``signal-cli link`` running until they press Enter.
        ``retry_later`` — user installs packages and restarts; caller should stop the link process.
    """
    print("\n" + "-" * 60)
    while True:
        choice = input(
            "\nHow do you want to continue?\n"
            "  1 = Manual linking — I will create a QR in my browser, scan with Signal, then come back here\n"
            "  2 = Stop for now — I will install missing Python/Tk packages and run this script again to link\n"
            "Enter 1 or 2: "
        ).strip()
        if choice == "1":
            _print_manual_linking_qr_help(url)
            input(
                "\nWhen your phone shows the linked device (or if linking failed), press Enter here "
                "so the script can continue. The ``signal-cli link`` process must stay running until then."
            )
            return "manual"
        if choice == "2":
            print(
                "\nStopping the link session. Install the suggested packages (e.g. ``python3-tkinter``, "
                "``qrcode``, ``Pillow``), then run this script again and choose link again."
            )
            return "retry_later"
        print("Please type 1 or 2.")


# signal-cli 0.14.x is built for Java 25 (class file version 69).
SIGNAL_CLI_MIN_JAVA_MAJOR = 25


def _signal_cli_list_groups_timeout_seconds() -> int:
    """
    ``listGroups -d`` can exceed 30s with many groups, or on slow paths (e.g. WSL ``/mnt/c/...``).

    Override with env ``SIGNAL_DM_LIST_GROUPS_TIMEOUT`` (seconds, 60–3600).
    """
    raw = os.environ.get("SIGNAL_DM_LIST_GROUPS_TIMEOUT", "300")
    try:
        v = int(raw)
        return max(60, min(v, 3600))
    except ValueError:
        return 300


def _parse_openjdk_version_output(text: str) -> Optional[int]:
    """Parse major Java language version from ``java -version`` combined stdout/stderr."""
    if not text:
        return None
    m = re.search(r'version "1\.(\d+)\.', text)
    if m:
        return int(m.group(1))
    m = re.search(r'version "(\d+)', text)
    if m:
        return int(m.group(1))
    return None


def _java_major_version_for_command(java_cmd: List[str]) -> Optional[int]:
    """Run ``java_cmd`` plus ``-version`` and return the parsed major version."""
    try:
        r = subprocess.run(
            [*java_cmd, "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return _parse_openjdk_version_output((r.stderr or "") + (r.stdout or ""))


def configure_windows_java_env(log: logging.Logger) -> None:
    """
    If JAVA_HOME is not set, point it at a JDK directory next to this project.

    The bundled ``signal-cli.bat`` respects JAVA_HOME. Install the Windows JDK
    installer, or extract a portable JDK into e.g. ``signal_dmer/jdk-25``.
    """
    if sys.platform != "win32":
        return
    if os.environ.get("JAVA_HOME"):
        return
    root = _project_root()
    candidates: List[Path] = []
    for p in sorted(root.glob("jdk*"), key=lambda x: str(x).lower()):
        if p.is_dir():
            candidates.append(p)
    for name in ("jdk-25", "jdk"):
        p = root / name
        if p.is_dir() and p not in candidates:
            candidates.append(p)
    for jdk in candidates:
        java_exe = jdk / "bin" / "java.exe"
        if not java_exe.is_file():
            continue
        major = _java_major_version_for_command([str(java_exe)])
        if major is not None and major >= SIGNAL_CLI_MIN_JAVA_MAJOR:
            os.environ["JAVA_HOME"] = str(jdk.resolve())
            log.info("JAVA_HOME set to bundled/portable JDK: %s", os.environ["JAVA_HOME"])
            return


def ensure_posix_java_if_needed(signal_cli_executable: Path, log: logging.Logger) -> None:
    """Linux/macOS: JVM ``bin/signal-cli`` needs Java 25+ on PATH; Linux-native binary does not."""
    if sys.platform == "win32":
        return
    if signal_cli_executable.name.lower() == "signal-cli-client":
        return
    if _is_signal_cli_linux_native_executable(signal_cli_executable):
        return
    if not shutil.which("java"):
        log.error(
            "Java (JDK) is required for ``bin/signal-cli`` but ``java`` was not found on PATH.\n"
            "signal-cli 0.14.x needs Java %s or newer.\n"
            "  Install Temurin %s from https://adoptium.net/ (Linux x64 tarball is fine), "
            "or use your distro package when it offers openjdk-%s-jdk.",
            SIGNAL_CLI_MIN_JAVA_MAJOR,
            SIGNAL_CLI_MIN_JAVA_MAJOR,
            SIGNAL_CLI_MIN_JAVA_MAJOR,
        )
        raise SystemExit(1)
    major = _java_major_version_for_command(["java"])
    if major is None:
        log.error("Could not parse Java version from ``java -version`` output.")
        raise SystemExit(1)
    if major < SIGNAL_CLI_MIN_JAVA_MAJOR:
        log.error(
            "Java %s is on PATH, but signal-cli 0.14.x requires Java %s or newer "
            "(class file version 69; JDK 21 reports major 21 and is too old).\n"
            "Install JDK %s, e.g. Temurin from https://adoptium.net/ or ``sudo apt install openjdk-%s-jdk`` "
            "when your Ubuntu/Debian release provides it.",
            major,
            SIGNAL_CLI_MIN_JAVA_MAJOR,
            SIGNAL_CLI_MIN_JAVA_MAJOR,
            SIGNAL_CLI_MIN_JAVA_MAJOR,
        )
        raise SystemExit(1)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.environ.get("SIGNAL_DM_LOG", "signal_dm.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
configure_windows_java_env(logger)

signal_cli_path = default_signal_cli_path()

# Data directory for CSV files and messages. Per-user launches set SIGNAL_DM_DATA_DIR.
_data_env = os.environ.get("SIGNAL_DM_DATA_DIR")
DATA_DIR = (
    Path(_data_env).expanduser().resolve()
    if _data_env
    else Path(__file__).resolve().parent / "signal_cli_data"
)
DATA_DIR.mkdir(parents=True, exist_ok=True)

class SignalCLI:
    """Wrapper for signal-cli (Windows ``.bat``, Linux native, or POSIX JVM ``bin/signal-cli``)."""

    def __init__(
        self,
        signal_cli_path: Union[str, Path, None] = None,
        account: str | None = None,
        *,
        auto_setup_account: bool = True,
    ):
        """
        Initialize SignalCLI wrapper

        Args:
            signal_cli_path: Path to signal-cli executable (default: OS-specific layout)
            account: Your Signal phone number (e.g., +1234567890)
            auto_setup_account: If True (default) and account is not provided, prompt/link/register
                interactively as needed. Set False for non-interactive UIs that will handle linking.
        """
        if signal_cli_path is None:
            signal_cli_path = default_signal_cli_path()
        self.signal_cli_path = str(Path(signal_cli_path).resolve())
        self._shell = use_shell_for_signal_cli(self.signal_cli_path)
        self.account = account
        self._lock = threading.Lock()  # For thread-safe operations

        exe_path = Path(self.signal_cli_path)
        if not exe_path.is_file():
            raise FileNotFoundError(f"signal-cli not found at {self.signal_cli_path}")

        if exe_path.name.lower() == "signal-cli-client":
            logger.error(
                "``signal-cli-client`` is not supported here: it is a JSON-RPC client for "
                "``signal-cli daemon`` only (socket errors like ENOENT otherwise). "
                "Use ``signal-cli-0.14.8/bin/signal-cli`` from the full ``signal-cli-*-Linux.tar.gz`` archive."
            )
            raise SystemExit(1)

        if sys.platform != "win32" and exe_path.is_file():
            try:
                mode = exe_path.stat().st_mode
                if not (mode & stat.S_IXUSR):
                    exe_path.chmod(mode | stat.S_IRWXU)
                    logger.info("Set execute permission on %s", self.signal_cli_path)
            except OSError as e:
                logger.warning("Could not chmod +x %s: %s", self.signal_cli_path, e)

        ensure_posix_java_if_needed(exe_path, logger)

        logger.info("Using signal-cli at: %s (%s)", self.signal_cli_path, sys.platform)
        
        # Get account if not provided (interactive by default)
        if self.account is None and auto_setup_account:
            self.account = self._get_registered_account()

    def detect_registered_account(self) -> Optional[str]:
        """Return the first registered account (if any) without prompting."""
        try:
            result = self._run_command(["listAccounts"])
            accounts = [a.strip() for a in result.strip().split("\n") if a.strip()]
            if not accounts:
                return None
            account_line = accounts[0]
            if "Number:" in account_line:
                return account_line.split("Number:")[-1].strip()
            return account_line.strip()
        except Exception:
            return None

    def set_account(self, account: str) -> None:
        """Set the active account number for subsequent commands."""
        self.account = account

    def _cli_argv(self, *args: str) -> List[str]:
        """signal-cli invocation, including this user's config directory when set."""
        cmd = [self.signal_cli_path]
        config = os.environ.get("SIGNAL_CLI_CONFIG")
        if config:
            cmd.extend(["-c", config])
        cmd.extend(args)
        return cmd
    
    def _get_registered_account(self) -> str:
        """Get the registered Signal account"""
        try:
            result = self._run_command(["listAccounts"])
            accounts = result.strip().split('\n')
            if accounts and accounts[0]:
                account_line = accounts[0].strip()
                # Handle different output formats: "Number: +1234567890" or just "+1234567890"
                if "Number:" in account_line:
                    account = account_line.split("Number:")[-1].strip()
                else:
                    account = account_line.strip()
                logger.info(f"Using account: {account}")
                return account
            else:
                # No account found - guide user through setup
                return self._setup_account()
        except Exception as e:
            logger.error(f"Error getting account: {e}")
            # Try setup as fallback
            return self._setup_account()
    
    def _setup_account(self) -> str:
        """Guide user through Signal account setup"""
        print("\n" + "="*60)
        print("SIGNAL ACCOUNT SETUP")
        print("="*60)
        print("\nNo Signal account found. Let's set one up!")
        print("\nYou have two options:")
        print("1. Link to an existing Signal account (recommended)")
        print("2. Register a new phone number")
        
        while True:
            choice = input("\nChoose option (1 or 2): ").strip()
            if choice in ['1', '2']:
                break
            print("Please enter 1 or 2")
        
        if choice == '1':
            return self._link_device()
        else:
            return self._register_new_account()
    
    def _link_device(self) -> str:
        """Link signal-cli to an existing Signal account"""
        print("\n" + "-"*60)
        print("LINK TO EXISTING SIGNAL ACCOUNT")
        print("-"*60)
        print("\nThis will link signal-cli to your existing Signal mobile app.")
        print("You'll need your phone nearby to scan a QR code.")
        
        # Generate linking URI
        print("\nGenerating linking code...\n")
        
        # Use threading to read output while process runs
        link_url = None
        process = None
        
        def read_output():
            """Background thread to read signal-cli output"""
            nonlocal link_url
            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    print(line, end='')  # Print in real-time
                    
                    # Look for URL patterns
                    if not link_url:
                        for pattern in [r'sgnl://linkdevice\?[^\s]+', r'tsdevice:/\?[^\s]+']:
                            match = re.search(pattern, line)
                            if match:
                                link_url = match.group(0)
                                break
            except:
                pass
        
        try:
            link_name = os.environ.get("SIGNAL_CLI_LINK_NAME", "signal-cli-on-desktop")
            cmd = self._cli_argv("link", "-n", link_name)
            
            # Start the process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=self._shell,
                encoding='utf-8',
                text=True,
                bufsize=1,
            )
            
            # Start reading output in background thread
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()
            
            # Wait for URL to be extracted (max 10 seconds)
            for _ in range(100):
                if link_url:
                    break
                time.sleep(0.1)
            
            if link_url:
                print("\n" + "=" * 60)
                print("LINK DEVICE URI (QR popup if available)")
                print("=" * 60)
                print(f"\n{link_url}\n")
                link_mode = self._display_qr_code_blocking(link_url, process)
                if link_mode == "retry_later":
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except Exception:
                            process.kill()
                    print("\n(Link session ended. Run the script again when you are ready to link.)")
                    raise SystemExit(0)
            else:
                print("\n⚠️  Could not extract linking URL from output.")
                input("\nPress Enter once linking is complete...")
            
            # ``signal-cli link`` may still be running until the phone completes pairing; only
            # stop it after the popup closed (manual path already waited for Enter).
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
            
            # Verify linking worked
            result = self._run_command(["listAccounts"])
            accounts = result.strip().split('\n')
            if accounts and accounts[0]:
                account_line = accounts[0].strip()
                if "Number:" in account_line:
                    account = account_line.split("Number:")[-1].strip()
                else:
                    account = account_line.strip()
                print(f"\n✓ Successfully linked! Using account: {account}")
                return account
            else:
                raise ValueError("Linking may have failed. No account found.")
            
        except Exception as e:
            print(f"\n✗ Error during linking: {e}")
            print("\nPlease try again or register a new number instead.")
            # Make sure to clean up the process
            try:
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2)
            except:
                pass
            raise
    
    def _display_qr_code_blocking(self, url: str, process) -> str:
        """Display QR code in a popup window (blocking, runs on main thread).

        Returns:
            ``popup`` if the Tk window was used, ``manual`` or ``retry_later`` from the text fallback prompt.
        """
        try:
            import qrcode
            from PIL import Image, ImageTk
            import tkinter as tk
            from tkinter import ttk
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)
            
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Create popup window
            root = tk.Tk()
            root.title("Signal Device Linking - Scan QR Code")
            root.geometry("500x650")
            root.resizable(False, False)
            
            # Make window stay on top
            root.attributes('-topmost', True)
            
            # Create frame
            frame = ttk.Frame(root, padding="20")
            frame.pack(fill=tk.BOTH, expand=True)
            
            # Title
            title = ttk.Label(frame, text="Scan this QR code with Signal", font=('Arial', 14, 'bold'))
            title.pack(pady=(0, 10))
            
            # Instructions
            instructions = ttk.Label(
                frame, 
                text="1. Open Signal on your phone\n2. Go to Settings > Linked Devices\n3. Tap 'Link New Device'\n4. Scan this QR code",
                justify=tk.CENTER,
                font=('Arial', 10)
            )
            instructions.pack(pady=(0, 10))
            
            # Display QR code
            photo = ImageTk.PhotoImage(qr_img)
            label = ttk.Label(frame, image=photo)
            label.image = photo  # Keep a reference
            label.pack(pady=10)
            
            # Status label
            status_label = ttk.Label(frame, text="Waiting for you to scan...", font=('Arial', 9), foreground='gray')
            status_label.pack(pady=5)
            
            # Close button
            def on_close():
                root.quit()
                root.destroy()
            
            close_btn = ttk.Button(
                frame, 
                text="Done - I've scanned the code",
                command=on_close
            )
            close_btn.pack(pady=10)
            
            # Check process status periodically
            def check_process():
                if process.poll() is not None:
                    # Process finished
                    status_label.config(text="✓ Linking complete!", foreground='green')
                    close_btn.config(text="Close Window")
                else:
                    # Schedule next check
                    root.after(1000, check_process)
            
            # Start checking after 2 seconds
            root.after(2000, check_process)
            
            # Auto-close after 5 minutes (in case user forgets)
            root.after(300000, on_close)
            
            # Run the GUI (blocking call on main thread)
            root.mainloop()
            return "popup"

        except ImportError as e:
            logger.warning(f"Could not display QR code window: {e}")
            err = str(e).lower()
            if "imagetk" in err or "tkinter" in err:
                print(
                    "\n⚠️  The QR popup needs Tkinter (``ImageTk``). On many Linux installs it is a separate package."
                )
                print("  Fedora:     sudo dnf install python3-tkinter")
                print("  Debian/Ubuntu: sudo apt install python3-tk")
            else:
                print("\n⚠️  Optional — install Python packages if you want the in-app QR popup later:")
                print(_pip_install_qrcode_instructions())
            return _prompt_qr_linking_fallback(url)
        except Exception as e:
            logger.warning(f"Error displaying QR code: {e}")
            print(f"\n⚠️  Could not open the QR popup: {e}")
            return _prompt_qr_linking_fallback(url)
    
    def _register_new_account(self) -> str:
        """Register a new phone number with Signal"""
        print("\n" + "-"*60)
        print("REGISTER NEW PHONE NUMBER")
        print("-"*60)
        print("\nNote: This requires a phone number that can receive SMS.")
        print("If you already have Signal on your phone, use linking instead!")
        
        phone = input("\nEnter your phone number (with country code, e.g., +1234567890): ").strip()
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        print(f"\nRegistering {phone}...")
        
        try:
            # Send verification code
            cmd = self._cli_argv("-a", phone, "register")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=self._shell,
                encoding='utf-8'
            )
            
            print(result.stdout)
            print(result.stderr)
            
            # Get verification code from user
            verification_code = input("\nEnter the verification code you received: ").strip()
            
            # Verify the code
            cmd = self._cli_argv("-a", phone, "verify", verification_code)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=self._shell,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                print(f"\n✓ Successfully registered {phone}!")
                return phone
            else:
                raise ValueError(f"Verification failed: {result.stderr}")
                
        except Exception as e:
            print(f"\n✗ Error during registration: {e}")
            raise
    
    def _run_command(self, args: List[str], timeout: int = 30) -> str:
        """
        Run a signal-cli command with enhanced error handling
        
        Args:
            args: Command arguments
            timeout: Command timeout in seconds
            
        Returns:
            Command output as string
        """
        prefix: List[str] = []
        if self.account:
            prefix.extend(["-a", self.account])
        cmd = self._cli_argv(*prefix, *args)
        
        logger.debug(f"Running command: {' '.join(['***' if i > 0 and cmd[i-1] == '-m' else arg for i, arg in enumerate(cmd)])}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=self._shell,
                encoding='utf-8',
                errors='replace'  # Handle encoding issues gracefully
            )
            
            if result.returncode != 0:
                logger.error(f"Command failed with code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
            
            return result.stdout
        
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(f"Error running command: {e}")
            raise
    
    def list_groups(self) -> List[Dict]:
        """
        List all Signal groups
        
        Returns:
            List of group dictionaries (excluding groups with null names)
        """
        try:
            lg_timeout = _signal_cli_list_groups_timeout_seconds()
            logger.info("Fetching group list (timeout %s s)...", lg_timeout)
            output = self._run_command(["listGroups", "-d"], timeout=lg_timeout)
            
            groups = []
            for line in output.strip().split('\n'):
                if line.strip():
                    try:
                        # Parse group info (format may vary)
                        if 'Id:' in line and 'Name:' in line:
                            logger.debug(f"Processing group line: {line[:100]}...")
                            parts = line.split()
                            group_id = None
                            group_name = None
                            
                            # Extract ID and name from the line
                            id_idx = line.find('Id:')
                            name_idx = line.find('Name:')
                            
                            if id_idx != -1:
                                after_id = line[id_idx + 3:].strip()
                                logger.debug(f"After 'Id:': '{after_id[:50]}...'")
                                if after_id:  # Make sure there's content after "Id: "
                                    parts = after_id.split()
                                    if parts:  # Make sure split() returned something
                                        group_id = parts[0]
                                        logger.debug(f"Extracted group_id: {group_id}")
                            
                            if name_idx != -1:
                                # Extract name more carefully - everything after "Name:" until "Description:" or end
                                name_start = name_idx + 5
                                desc_idx = line.find('Description:', name_start)
                                if desc_idx != -1:
                                    name_part = line[name_start:desc_idx].strip()
                                else:
                                    name_part = line[name_start:].strip()
                                group_name = name_part
                                logger.debug(f"Extracted group_name: '{group_name}'")
                            
                            # Only add groups that have a valid name (not null/empty)
                            if group_id and group_name and group_name.lower() not in ['null', '']:
                                groups.append({
                                    'id': group_id,
                                    'name': group_name
                                })
                                logger.debug(f"Added group: {group_name}")
                    except Exception as e:
                        logger.error(f"Error parsing group line: {line[:50]}... - {e}")
                        import traceback
                        logger.error(traceback.format_exc())
            
            logger.info(f"Found {len(groups)} groups (filtered out null names)")
            return groups
        
        except Exception as e:
            logger.error(f"Error listing groups: {e}")
            raise
    
    def _get_contacts_info(self) -> Dict:
        """
        Get recipient information from Signal (contacts plus other known recipients).

        Uses ``listContacts -a`` so lookups include everyone signal-cli knows about
        (e.g. group members), not only address-book contacts. ``sendSyncRequest`` only
        syncs contacts from the phone; it does not fetch missing profile names for
        strangers in a group.

        Returns:
            Dictionary mapping UUIDs/numbers to contact info
        """
        try:
            output = self._run_command(["-o", "json", "listContacts", "-a"], timeout=120)
            contacts_data = json.loads(output)
            
            # Create lookup dictionaries by number and UUID
            contacts_by_number = {}
            contacts_by_uuid = {}
            
            for contact in contacts_data:
                number = contact.get('number')
                uuid = contact.get('uuid')
                
                # Determine best display name
                display_name = self._get_display_name(contact)
                
                contact_info = {
                    'display_name': display_name,
                    'number': number,
                    'uuid': uuid,
                    'raw_contact': contact
                }
                
                if number:
                    contacts_by_number[number] = contact_info
                if uuid:
                    contacts_by_uuid[uuid] = contact_info
            
            return {'by_number': contacts_by_number, 'by_uuid': contacts_by_uuid}
        
        except Exception as e:
            logger.warning(f"Could not load contacts info: {e}")
            return {'by_number': {}, 'by_uuid': {}}
    
    def _get_display_name(self, contact: Dict) -> str:
        """
        Get the best display name for a contact
        
        Args:
            contact: Contact data from listContacts
            
        Returns:
            Best available display name
        """
        # Priority order: contact name -> profile name -> given name -> number -> UUID
        
        # Try contact name (user-set name)
        name = contact.get('name') or ''
        if name and name.strip():
            return name.strip()
            
        # Try profile names (from Signal profile)
        profile = contact.get('profile') or {}
        profile_given = (profile.get('givenName') or '').strip()
        profile_family = (profile.get('familyName') or '').strip()
        if profile_given or profile_family:
            return f"{profile_given} {profile_family}".strip()
        
        # Try contact book names
        given = (contact.get('givenName') or '').strip()
        family = (contact.get('familyName') or '').strip()
        if given or family:
            return f"{given} {family}".strip()
        
        # Try nickname
        nick_given = (contact.get('nickGivenName') or '').strip()
        if nick_given:
            return nick_given

        # Signal username (when set), often available without a formal "contact" name
        username = (contact.get('username') or '').strip()
        if username:
            return username

        # No name found - return empty string
        # This will prevent showing UUID/number as display name
        return ""

    def get_profile_name(self, identifier: str) -> str:
        """
        Get profile name for a specific identifier from contacts
        
        Note: This uses cached contact data. For linked devices, profile updates
        happen automatically when messages are received.
        
        Args:
            identifier: Phone number or UUID
            
        Returns:
            Profile name if available, empty string otherwise
        """
        try:
            # Get all contacts (this is cached and fast)
            contacts_info = self._get_contacts_info()
            
            # Look up by phone number or UUID
            contact = None
            if identifier.startswith('+'):
                contact = contacts_info['by_number'].get(identifier)
            else:
                contact = contacts_info['by_uuid'].get(identifier)
            
            if contact and contact.get('display_name'):
                return contact['display_name']
            
            return ""
            
        except Exception as e:
            logger.debug(f"Could not fetch profile for {identifier[:12]}...: {e}")
            return ""
    
    def get_group_members(self, group_id: str) -> List[Dict]:
        """
        Get all members of a Signal group with their display names
        
        Args:
            group_id: The group ID
            
        Returns:
            List of dictionaries with member info: {'identifier': str, 'display_name': str}
        """
        try:
            logger.info(f"Getting members for group: {group_id}")
            output = self._run_command(
                ["-o", "json", "listGroups", "-d", "-g", group_id],
                timeout=_signal_cli_list_groups_timeout_seconds(),
            )
            
            # Parse JSON output
            groups_data = json.loads(output)
            
            if not groups_data:
                logger.warning(f"No group data found for group ID: {group_id}")
                return []
            
            group = groups_data[0]  # Should be only one group since we specified ID
            members = group.get('members', [])
            
            # Get contact info for name resolution (as fallback)
            contacts_info = self._get_contacts_info()
            
            member_list = []
            from_group_json_profile = 0

            for member in members:
                # Get identifier (prefer phone number, fallback to UUID)
                identifier = member.get('number') or member.get('uuid')
                if not identifier:
                    continue

                # listGroups JSON is normally number/uuid/admin/labels only; some builds
                # may still embed a profile object — use it when present.
                display_name = ""
                profile = member.get('profile') or {}
                profile_given = (profile.get('givenName') or '').strip()
                profile_family = (profile.get('familyName') or '').strip()
                if profile_given or profile_family:
                    display_name = f"{profile_given} {profile_family}".strip()
                    from_group_json_profile += 1

                if not display_name:
                    if member.get('number') and member['number'] in contacts_info['by_number']:
                        display_name = contacts_info['by_number'][member['number']]['display_name']
                    elif member.get('uuid') and member['uuid'] in contacts_info['by_uuid']:
                        display_name = contacts_info['by_uuid'][member['uuid']]['display_name']

                member_list.append({
                    'identifier': identifier,
                    'display_name': display_name
                })

            named = sum(1 for m in member_list if m['display_name'])
            logger.info(
                "Found %s members in group (%s with a display name)",
                len(member_list),
                named,
            )
            if from_group_json_profile:
                logger.debug("Names from embedded listGroups member profile: %s", from_group_json_profile)
            return member_list
        
        except Exception as e:
            logger.error(f"Error getting group members: {e}")
            raise
    
    def send_message(self, recipient: str, message: str) -> bool:
        """
        Send a message to a recipient
        
        Args:
            recipient: Phone number or UUID of recipient
            message: Message to send
            
        Returns:
            True if successful, False otherwise
        """
        import tempfile
        import os
        
        try:
            logger.info(f"Sending message to {recipient}")
            
            # Check if message contains newlines - if so, use file-based approach
            if '\n' in message:
                # Use temporary file for multi-line messages to avoid shell parsing issues
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as temp_file:
                    temp_file.write(message)
                    temp_file_path = temp_file.name
                
                try:
                    # Use --message-from-stdin or file-based approach
                    cmd = ["send", "--message-from-stdin", recipient]
                    
                    # Run with stdin input
                    account_args = ["-a", self.account] if self.account else []
                    result = subprocess.run(
                        self._cli_argv(*account_args, *cmd),
                        input=message,
                        capture_output=True,
                        text=True,
                        shell=self._shell,
                        encoding='utf-8',
                        errors='replace'
                    )
                    
                    if result.returncode != 0:
                        logger.error(f"Command failed with code {result.returncode}")
                        logger.error(f"STDOUT: {result.stdout}")
                        logger.error(f"STDERR: {result.stderr}")
                        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
                    
                    logger.info(f"Multi-line message sent successfully to {recipient}")
                    return True
                    
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
            else:
                # For single-line messages, use the normal -m approach
                cmd = ["send", "-m", message, recipient]
                
                # Try sending the message
                try:
                    self._run_command(cmd)
                    logger.info(f"Message sent successfully to {recipient}")
                    return True
                except Exception as uuid_error:
                    # If UUID failed and it's a UUID (not phone number), try to get phone number from contacts
                    if not recipient.startswith('+'):
                        logger.warning(f"Direct UUID send failed: {uuid_error}")
                        logger.info(f"Attempting to find phone number for UUID: {recipient}")
                        
                        # Try to get contacts and find phone number for this UUID
                        try:
                            contacts_info = self._get_contacts_info()
                            if recipient in contacts_info['by_uuid']:
                                phone_number = contacts_info['by_uuid'][recipient]['number']
                                if phone_number:
                                    logger.info(f"Found phone number {phone_number} for UUID {recipient}")
                                    cmd = ["send", "-m", message, phone_number]
                                    self._run_command(cmd)
                                    logger.info(f"Message sent successfully to {phone_number} (resolved from UUID)")
                                    return True
                            
                            logger.error(f"No phone number found for UUID: {recipient}")
                            raise uuid_error
                        except Exception as fallback_error:
                            logger.error(f"Fallback to phone number also failed: {fallback_error}")
                            raise uuid_error
                    else:
                        # It was a phone number that failed
                        raise uuid_error
        
        except Exception as e:
            logger.error(f"Error sending message to {recipient}: {e}")
            return False
    
    def send_dm_to_group_members(self, group_id: str, message: str, delay: int = 2, parallel: bool = False, max_workers: int = 3, personalize: bool = True, second_message: str = None, message_delay: float = 2.0) -> Dict[str, bool]:
        """
        Send a direct message to all members of a group
        
        Args:
            group_id: The group ID
            message: Base message to send (will be personalized if personalize=True)
            delay: Delay between messages in seconds (ignored if parallel=True)
            parallel: Whether to send messages in parallel (faster but may hit rate limits)
            max_workers: Maximum number of parallel workers (only used if parallel=True)
            personalize: Whether to prepend "Hey <name>, " to the message
            second_message: Optional second message to send after a short delay
            message_delay: Delay between first and second message in seconds
            
        Returns:
            Dictionary mapping member identifiers to success status
        """
        try:
            members = self.get_group_members(group_id)
            results = {}
            
            if parallel and len(members) > 1:
                logger.info(f"Sending DM to {len(members)} members in parallel...")
                results = self._send_messages_parallel(members, message, max_workers, personalize, second_message, message_delay)
            else:
                logger.info(f"Sending DM to {len(members)} members sequentially...")
                results = self._send_messages_sequential(members, message, delay, personalize, second_message, message_delay)
            
            successful = sum(1 for success in results.values() if success)
            logger.info(f"Sent messages to {successful}/{len(members)} members successfully")
            
            return results
        
        except Exception as e:
            logger.error(f"Error sending DMs to group members: {e}")
            raise
    
    def _send_messages_sequential(self, members: List[Dict], message: str, delay: int, personalize: bool = True, second_message: str = None, message_delay: float = 2.0) -> Dict[str, bool]:
        """Send messages sequentially with humanized random delays"""
        results = {}
        for i, member_info in enumerate(members, 1):
            identifier = member_info['identifier']
            display_name = member_info['display_name']
            
            # Create personalized message(s)
            # Only personalize if display_name is not empty
            if personalize and display_name:
                template = load_personalization_template()
                personalization_prefix = template.format(display_name=display_name)
                personalized_message = f"{personalization_prefix}{message}"
                personalized_second = f"{second_message}" if second_message else None
            else:
                personalized_message = message
                personalized_second = second_message
            
            # Use display_name for logging if available, otherwise show identifier
            log_name = display_name if display_name else identifier[:12] + "..."
            logger.info(f"Sending to member {i}/{len(members)}: {log_name} ({identifier})")
            
            # Send first message
            success1 = self.send_message(identifier, personalized_message)
            
            # Send second message if provided
            success2 = True  # Default to success if no second message
            if personalized_second:
                # Short delay between messages to same person
                short_delay = random.uniform(message_delay * 0.8, message_delay * 1.2)
                logger.info(f"Waiting {short_delay:.1f} seconds before second message to {display_name}...")
                time.sleep(short_delay)
                
                logger.info(f"Sending second message to {display_name}")
                success2 = self.send_message(identifier, personalized_second)
            
            # Both messages need to succeed for overall success
            results[identifier] = success1 and success2
            
            # Add randomized delay between different members to simulate human behavior
            if i < len(members):
                # Add random variation: ±30% of base delay, minimum 1 second
                min_delay = max(1, int(delay * 0.7))
                max_delay = int(delay * 1.3) + 2  # Extra buffer for realism
                actual_delay = random.uniform(min_delay, max_delay)
                
                logger.info(f"Waiting {actual_delay:.1f} seconds before next member (humanized timing)...")
                time.sleep(actual_delay)
        
        return results
    
    def _send_messages_parallel(self, members: List[Dict], message: str, max_workers: int, personalize: bool = True, second_message: str = None, message_delay: float = 2.0) -> Dict[str, bool]:
        """Send messages in parallel using ThreadPoolExecutor with humanized timing"""
        results = {}
        
        def send_to_member(member_info: Dict) -> tuple[str, bool]:
            """Helper function for parallel execution"""
            try:
                identifier = member_info['identifier']
                display_name = member_info['display_name']
                
                # Create personalized message(s)
                # Only personalize if display_name is not empty
                if personalize and display_name:
                    template = load_personalization_template()
                    personalization_prefix = template.format(display_name=display_name)
                    personalized_message = f"{personalization_prefix}{message}"
                    personalized_second = f"{second_message}" if second_message else None
                else:
                    personalized_message = message
                    personalized_second = second_message
                
                # Add randomized delay to simulate human behavior even in parallel
                # Range: 0.5 to 3.0 seconds with random distribution
                random_delay = random.uniform(0.5, 3.0)
                time.sleep(random_delay)
                
                # Send first message
                success1 = self.send_message(identifier, personalized_message)
                
                # Send second message if provided
                success2 = True  # Default to success if no second message
                if personalized_second:
                    # Short delay between messages to same person
                    short_delay = random.uniform(message_delay * 0.8, message_delay * 1.2)
                    time.sleep(short_delay)
                    success2 = self.send_message(identifier, personalized_second)
                
                # Both messages need to succeed for overall success
                return identifier, success1 and success2
            except Exception as e:
                logger.error(f"Error sending to {member_info['display_name']} ({member_info['identifier']}) in parallel: {e}")
                return member_info['identifier'], False
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_member = {executor.submit(send_to_member, member_info): member_info for member_info in members}
            
            # Collect results
            for future in future_to_member:
                try:
                    identifier, success = future.result(timeout=30)
                    results[identifier] = success
                    status = "✓" if success else "✗"
                    # Get display name for logging
                    member_info = future_to_member[future]
                    logger.info(f"{status} {member_info['display_name']} ({identifier})")
                except Exception as e:
                    member_info = future_to_member[future]
                    identifier = member_info['identifier']
                    logger.error(f"✗ {member_info['display_name']} ({identifier}) - Exception: {e}")
                    results[identifier] = False
        
        return results
    
    def _load_previous_custom_names(self, safe_group_name: str) -> Dict[str, str]:
        """Load custom display names from previous exports of the same group
        
        Args:
            safe_group_name: The sanitized group name to search for
            
        Returns:
            Dictionary mapping identifiers to custom display names
        """
        custom_names = {}
        
        try:
            # Find all CSV files for this group (pattern: groupname_timestamp.csv)
            pattern = f"{safe_group_name}_*.csv"
            matching_files = sorted(DATA_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            
            if not matching_files:
                return custom_names
            
            # Process files from most recent to oldest
            # Most recent custom names take priority
            for csv_file in matching_files:
                try:
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            custom_name = row.get('custom_display_name', '').strip()
                            if not custom_name:
                                continue
                            
                            # Try to match by all available identifiers
                            # Only add if we don't already have a custom name for this person
                            phone = row.get('phone_number', '').strip()
                            uuid = row.get('uuid', '').strip()
                            identifier = row.get('identifier', '').strip()
                            
                            # Add mappings for all available identifiers
                            # Skip if already mapped (prioritizing more recent files)
                            if phone and phone not in custom_names:
                                custom_names[phone] = custom_name
                            if uuid and uuid not in custom_names:
                                custom_names[uuid] = custom_name
                            if identifier and identifier not in custom_names:
                                custom_names[identifier] = custom_name
                
                except Exception as e:
                    logger.warning(f"Error reading previous export {csv_file}: {e}")
                    continue
            
            if custom_names:
                logger.info(f"Found {len(set(custom_names.values()))} custom display names in {len(matching_files)} previous export(s)")
        
        except Exception as e:
            logger.warning(f"Error loading previous custom names: {e}")
        
        return custom_names
    
    def export_group_members_to_csv(self, group_id: str, group_name: str) -> str:
        """Export group members to a CSV file
        
        Args:
            group_id: The group ID
            group_name: The group name (for filename)
            
        Returns:
            Path to the created CSV file
        """
        try:
            members = self.get_group_members(group_id)
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_group_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in group_name)
            filename = f"{safe_group_name}_{timestamp}.csv"
            filepath = DATA_DIR / filename
            
            # Get detailed contact info
            contacts_info = self._get_contacts_info()
            
            # Look for previous exports of the same group and load custom display names
            previous_custom_names = self._load_previous_custom_names(safe_group_name)
            
            print(f"\nFound {len(members)} members in the group.")
            
            # Check how many members don't have display names
            missing_names = sum(1 for m in members if not m['display_name'])
            if missing_names > 0:
                print(f"⚠️  {missing_names} members have no display name available here.")
                print(
                    "Linked signal-cli only sees names it already has (contacts, usernames, people you have "
                    "chatted with, etc.). There is no reliable way to pull full names for every group member "
                    "from Signal alone. Edit custom_display_name in the CSV where you want a greeting name."
                )

            # Write CSV
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['identifier', 'phone_number', 'uuid', 'display_name', 'custom_display_name']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                
                for member in members:
                    identifier = member['identifier']
                    
                    # Get phone number and UUID separately
                    phone_number = identifier if identifier.startswith('+') else ''
                    uuid = identifier if not identifier.startswith('+') else ''
                    
                    # Try to get both from contacts if we only have one
                    if phone_number and not uuid:
                        contact_info = contacts_info['by_number'].get(phone_number, {})
                        uuid = contact_info.get('uuid', '')
                    elif uuid and not phone_number:
                        contact_info = contacts_info['by_uuid'].get(uuid, {})
                        phone_number = contact_info.get('number', '')
                    
                    # Get display name (already populated by get_group_members)
                    display_name = member['display_name']
                    
                    # Get custom display name from previous exports if available
                    # Try matching by phone, then uuid, then identifier
                    custom_name = ''
                    if phone_number and phone_number in previous_custom_names:
                        custom_name = previous_custom_names[phone_number]
                    elif uuid and uuid in previous_custom_names:
                        custom_name = previous_custom_names[uuid]
                    elif identifier in previous_custom_names:
                        custom_name = previous_custom_names[identifier]
                    
                    writer.writerow({
                        'identifier': identifier,
                        'phone_number': phone_number,
                        'uuid': uuid,
                        'display_name': display_name,
                        'custom_display_name': custom_name
                    })
            
            logger.info(f"Exported {len(members)} members to {filepath}")
            if previous_custom_names:
                logger.info(f"Merged {len(previous_custom_names)} custom display names from previous exports")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Error exporting group members: {e}")
            raise
    
    def load_members_from_csv(self, csv_path: str) -> List[Dict]:
        """Load member list from CSV file
        
        Args:
            csv_path: Path to CSV file
            
        Returns:
            List of member dictionaries
        """
        try:
            members = []
            with open(csv_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Use custom_display_name if provided, otherwise use display_name
                    display_name = row.get('custom_display_name', '').strip()
                    if not display_name:
                        display_name = row.get('display_name', '').strip()
                    
                    # Prefer phone_number, fallback to uuid, then identifier
                    identifier = row.get('phone_number', '').strip()
                    if not identifier:
                        identifier = row.get('uuid', '').strip()
                    if not identifier:
                        identifier = row.get('identifier', '').strip()
                    
                    if identifier and display_name:
                        members.append({
                            'identifier': identifier,
                            'display_name': display_name
                        })
            
            logger.info(f"Loaded {len(members)} members from {csv_path}")
            return members
            
        except Exception as e:
            logger.error(f"Error loading CSV file: {e}")
            raise

def get_available_csv_files() -> List[Path]:
    """Get list of available CSV files in data directory"""
    if not DATA_DIR.exists():
        return []
    return sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)

def load_message_from_file() -> Optional[str]:
    """Load message from message.txt if it exists"""
    message_file = DATA_DIR / "message.txt"
    if message_file.exists():
        try:
            with open(message_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Error reading message.txt: {e}")
    return None

def load_personalization_template() -> str:
    """Load personalization template from personalization.txt
    
    Returns:
        Personalization template string with {display_name} placeholder
    """
    personalization_file = DATA_DIR / "personalization.txt"
    default_template = "Hey {display_name},\n"
    
    if personalization_file.exists():
        try:
            with open(personalization_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content and '{display_name}' in content:
                    return content
                elif content:
                    logger.warning("personalization.txt doesn't contain {display_name} placeholder, using default")
        except Exception as e:
            logger.warning(f"Error reading personalization.txt: {e}")
    
    # Create default file if it doesn't exist
    try:
        with open(personalization_file, 'w', encoding='utf-8') as f:
            f.write(default_template)
        logger.info(f"Created default personalization template at {personalization_file}")
    except Exception as e:
        logger.warning(f"Could not create personalization.txt: {e}")
    
    return default_template

def save_personalization_template(template: str) -> bool:
    """Save personalization template to personalization.txt
    
    Args:
        template: Personalization template string
        
    Returns:
        True if successful, False otherwise
    """
    personalization_file = DATA_DIR / "personalization.txt"
    try:
        with open(personalization_file, 'w', encoding='utf-8') as f:
            f.write(template)
        logger.info(f"Saved personalization template to {personalization_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving personalization.txt: {e}")
        return False

def option_send_to_group(signal: 'SignalCLI'):
    """Option 1: Send messages to a Signal group"""
    print("\nFetching your Signal groups...")
    groups = signal.list_groups()
    
    if not groups:
        print("No groups found. Make sure you're a member of at least one group.")
        return
    
    # Display groups
    print("\nAvailable groups:")
    for i, group in enumerate(groups, 1):
        print(f"{i}. {group['name']}")
    
    # Get group selection
    while True:
        try:
            choice = input(f"\nSelect a group (1-{len(groups)}): ").strip()
            group_index = int(choice) - 1
            if 0 <= group_index < len(groups):
                selected_group = groups[group_index]
                break
            else:
                print(f"Please enter a number between 1 and {len(groups)}")
        except ValueError:
            print("Please enter a valid number")
    
    print(f"\nSelected group: {selected_group['name']}")
    members = None  # Will be fetched later
    source_name = selected_group['name']
    
    # Continue with message sending workflow
    _send_messages_workflow(signal, members, source_name, selected_group)

def option_export_group_to_csv(signal: 'SignalCLI'):
    """Option 2: Export group members to CSV"""
    print("\nFetching your Signal groups...")
    groups = signal.list_groups()
    
    if not groups:
        print("No groups found. Make sure you're a member of at least one group.")
        return
    
    print("\nAvailable groups:")
    for i, group in enumerate(groups, 1):
        print(f"{i}. {group['name']}")
    
    while True:
        try:
            choice = input(f"\nSelect a group to export (1-{len(groups)}): ").strip()
            group_index = int(choice) - 1
            if 0 <= group_index < len(groups):
                selected_group = groups[group_index]
                break
            else:
                print(f"Please enter a number between 1 and {len(groups)}")
        except ValueError:
            print("Please enter a valid number")
    
    print(f"\nExporting members from: {selected_group['name']}")
    csv_path = signal.export_group_members_to_csv(selected_group['id'], selected_group['name'])
    print(f"\n✓ Successfully exported to: {csv_path}")
    print("\nYou can now:")
    print("- Open this file in Excel or any spreadsheet program")
    print("- Edit the 'custom_display_name' column to customize how names appear in messages")
    print("- Use option 3 to send messages to these members")

def option_send_from_csv(signal: 'SignalCLI'):
    """Option 3: Send messages to members from CSV file"""
    csv_files = get_available_csv_files()
    
    if not csv_files:
        print(f"\nNo CSV files found in {DATA_DIR}")
        print("Please export a group first (option 2) or place CSV files in the data folder.")
        return
    
    print("\nAvailable CSV files:")
    for i, csv_file in enumerate(csv_files, 1):
        file_time = datetime.fromtimestamp(csv_file.stat().st_mtime)
        print(f"{i}. {csv_file.name} (modified: {file_time.strftime('%Y-%m-%d %H:%M')})")
    
    while True:
        try:
            choice = input(f"\nSelect a CSV file (1-{len(csv_files)}): ").strip()
            csv_index = int(choice) - 1
            if 0 <= csv_index < len(csv_files):
                selected_csv = csv_files[csv_index]
                break
            else:
                print(f"Please enter a number between 1 and {len(csv_files)}")
        except ValueError:
            print("Please enter a valid number")
    
    print(f"\nLoading members from: {selected_csv.name}")
    members = signal.load_members_from_csv(str(selected_csv))
    print(f"Loaded {len(members)} members")
    source_name = selected_csv.stem
    
    # Continue with message sending workflow
    _send_messages_workflow(signal, members, source_name, None)

def _send_messages_workflow(signal: 'SignalCLI', members: Optional[List[Dict]], source_name: str, selected_group: Optional[Dict]):
    """Common workflow for sending messages (used by both group and CSV options)"""
    # Get message
    saved_message = load_message_from_file()
    
    if saved_message:
        print("\n📄 Found saved message in message.txt:")
        print("-" * 60)
        preview = saved_message[:200] + ("..." if len(saved_message) > 200 else "")
        print(preview)
        print("-" * 60)
        
        use_saved = input("\nUse this message? (Y/n): ").strip().lower()
        if use_saved != 'n':
            message = saved_message
        else:
            saved_message = None
    
    if not saved_message:
        print("\nEnter the message to send to all members:")
        print("(Use \\n for line breaks, or type 'MULTILINE' for multi-line input)")
        print(f"Tip: You can also save your message to {DATA_DIR / 'message.txt'}")
        message = input("Message: ").strip()
        
        # Handle multi-line input
        if message.upper() == 'MULTILINE':
            print("\nEnter your multi-line message (press Ctrl+Z then Enter on Windows, or Ctrl+D on Unix when done):")
            try:
                lines = []
                while True:
                    try:
                        line = input()
                        lines.append(line)
                    except EOFError:
                        break
                message = '\n'.join(lines).strip()
            except KeyboardInterrupt:
                print("\nMessage input cancelled")
                return
        else:
            # Process escape sequences like \n, \t etc.
            message = message.encode().decode('unicode_escape')
    
    if not message:
        print("Message cannot be empty")
        return
    
    # Ask about second message
    second_message_choice = input("\nSend a second message to each person? (y/N): ").strip().lower()
    second_message = None
    message_delay = 10.0

    if second_message_choice == 'y':
        print("\nEnter the second message:")
        print("(Use \\n for line breaks, or type 'MULTILINE' for multi-line input)")
        second_message = input("Second message: ").strip()
        
        # Handle multi-line input for second message
        if second_message.upper() == 'MULTILINE':
            print("\nEnter your multi-line second message (press Ctrl+Z then Enter on Windows, or Ctrl+D on Unix when done):")
            try:
                lines = []
                while True:
                    try:
                        line = input()
                        lines.append(line)
                    except EOFError:
                        break
                second_message = '\n'.join(lines).strip()
            except KeyboardInterrupt:
                print("\nSecond message input cancelled")
                second_message = None
        else:
            # Process escape sequences like \n, \t etc.
            second_message = second_message.encode().decode('unicode_escape')
        
        if second_message:
            try:
                delay_input = input("Delay between first and second message (default: 10 seconds): ").strip()
                message_delay = float(delay_input) if delay_input else 10.0
                message_delay = max(0.5, min(10.0, message_delay))  # Clamp between 0.5-10 seconds
            except ValueError:
                message_delay = 10.0
            print(f"📱 Two messages will be sent to each person with ~{message_delay:.1f}s between them")
        else:
            print("Second message cannot be empty, skipping...")
            second_message = None
    
    # Ask about personalization
    personalize_choice = input("\nPersonalize messages with names? (Y/n): ").strip().lower()
    personalize = personalize_choice != 'n'
    
    if personalize:
        print("📝 First message: \"Hey <name>,\\n your message\"")
        if second_message:
            print("📝 Second message: \"your second message\"")
    else:
        print("📝 First message: \"your message\"")
        if second_message:
            print("📝 Second message: \"your second message\"")
    
    # Get delay and parallel options
    print(f"\nSending options:")
    print(f"1. Sequential (safer, slower) - sends messages one by one with delays")
    print(f"2. Parallel (faster, riskier) - sends multiple messages simultaneously")
    
    while True:
        mode_choice = input(f"\nChoose sending mode (1-2, default: 1): ").strip()
        if mode_choice == "2":
            parallel = True
            delay = 0
            try:
                max_workers = input("Max parallel workers (1-5, default: 3): ").strip()
                max_workers = int(max_workers) if max_workers else 3
                max_workers = max(1, min(5, max_workers))  # Clamp between 1-5
            except ValueError:
                max_workers = 3
            break
        elif mode_choice == "1" or mode_choice == "":
            parallel = False
            max_workers = 1
            try:
                delay = input("\nEnter base delay between messages in seconds (default: 30): ").strip()
                delay = int(delay) if delay else 30
                if delay < 1:
                    delay = 1
            except ValueError:
                delay = 30
            break
        else:
            print("Please enter 1 or 2")
    
    # Confirmation
    print(f"\nSummary:")
    print(f"Source: {source_name}")
    if members:
        print(f"Recipients: {len(members)} members from CSV")
    print(f"First message:")
    print(f"  {repr(message)}")
    if second_message:
        print(f"Second message:")
        print(f"  {repr(second_message)}")
        print(f"Delay between messages: ~{message_delay:.1f} seconds")
    if parallel:
        print(f"Mode: Parallel ({max_workers} workers)")
        print(f"⚠️  Warning: Parallel mode may trigger rate limits with large groups")
    else:
        print(f"Mode: Sequential (base delay: {delay} seconds, randomized ±30% for human-like timing)")
    
    confirm = input("\nProceed? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Operation cancelled")
        return
    
    # Send messages
    print("\nSending messages...")
    
    # Get members if not already loaded from CSV
    if members is None:
        members = signal.get_group_members(selected_group['id'])
    
    # Send via sequential or parallel method
    if parallel:
        results = signal._send_messages_parallel(members, message, max_workers, personalize, second_message, message_delay)
    else:
        results = signal._send_messages_sequential(members, message, delay, personalize, second_message, message_delay)
    
    # Display results
    print(f"\nResults:")
    successful = 0
    failed = 0
    
    # Create member lookup
    member_lookup = {m['identifier']: m['display_name'] for m in members}
    
    for identifier, success in results.items():
        status = "✓" if success else "✗"
        display_name = member_lookup.get(identifier, "")
        # Show identifier if no display name
        show_name = display_name if display_name else identifier[:12] + "..."
        print(f"{status} {show_name}")
        if success:
            successful += 1
        else:
            failed += 1
    
    print(f"\nSummary: {successful} successful, {failed} failed")

def option_personalization_settings(signal: 'SignalCLI'):
    """Option 4: View and edit personalization template"""
    personalization_file = DATA_DIR / "personalization.txt"
    
    print("\n" + "="*60)
    print("Personalization Template Settings")
    print("="*60)
    
    # Load current template
    current_template = load_personalization_template()
    
    print("\nCurrent personalization template:")
    print("-" * 60)
    print(current_template)
    print("-" * 60)
    
    print("\nThis template is prepended to your message when personalization is enabled.")
    print("Use {display_name} as a placeholder for the recipient's name.")
    print("Use \\n to represent a new line (equivalent to pressing Enter).")
    print(f"\nFile location: {personalization_file}")
    
    print("\nOptions:")
    print("1. Edit template now")
    print("2. View example")
    print("3. Reset to default")
    print("4. Back to main menu")
    
    while True:
        choice = input("\nChoose an option (1-4): ").strip()
        
        if choice == '1':
            print("\nEnter your new personalization template:")
            print("(Use {display_name} as placeholder, press Ctrl+Z then Enter when done)")
            print("Tip: Include line breaks as needed (e.g., \\n for newline)")
            
            try:
                lines = []
                while True:
                    try:
                        line = input()
                        lines.append(line)
                    except EOFError:
                        break
                new_template = '\n'.join(lines)
                
                # Process escape sequences
                new_template = new_template.encode().decode('unicode_escape')
                
                if not new_template.strip():
                    print("Template cannot be empty.")
                    continue
                
                if '{display_name}' not in new_template:
                    print("\n⚠️  Warning: Template doesn't contain {display_name} placeholder.")
                    confirm = input("Continue anyway? (y/N): ").strip().lower()
                    if confirm != 'y':
                        continue
                
                if save_personalization_template(new_template):
                    print("\n✓ Personalization template updated successfully!")
                    print("\nNew template:")
                    print("-" * 60)
                    print(new_template)
                    print("-" * 60)
                else:
                    print("\n✗ Failed to save template.")
                
            except KeyboardInterrupt:
                print("\nEdit cancelled.")
            break
            
        elif choice == '2':
            print("\nExample personalization templates:")
            print("-" * 60)
            print("1. Casual: \"Hey {display_name},\\n\"")
            print("2. Formal: \"{display_name},\\n\\n\"")
            print("3. Friendly: \"Hi {display_name}! 👋\\n\\n\"")
            print("4. Professional: \"Hello {display_name},\\n\\nI hope this message finds you well.\\n\\n\"")
            print("-" * 60)
            print("\nWith template \"Hey {display_name},\\n\" and message: \"Join us for the event!\"")
            print("\nBecomes:")
            print('  "Hey John,\n  Join us for the event!"')
            print("-" * 60)
            
        elif choice == '3':
            default = "Hey {display_name},\n"
            confirm = input(f"\nReset to default template? (y/N): ").strip().lower()
            if confirm == 'y':
                if save_personalization_template(default):
                    print("\n✓ Reset to default template:")
                    print("-" * 60)
                    print(default)
                    print("-" * 60)
                else:
                    print("\n✗ Failed to reset template.")
            break
            
        elif choice == '4':
            break
            
        else:
            print("Please enter 1, 2, 3, or 4")

def option_exit(signal: 'SignalCLI'):
    """Option 5: Exit the tool"""
    print("Exiting the tool...")
    exit(0)

def main():
    """Main function to run the script interactively"""
    # Define menu options with display names and corresponding functions
    MENU_OPTIONS = {
        '1': ('Send messages to a Signal group', option_send_to_group),
        '2': ('Export group members to CSV', option_export_group_to_csv),
        '3': ('Send messages to members from CSV file', option_send_from_csv),
        '4': ('View/Edit personalization template', option_personalization_settings),
        '5': ('Exit', option_exit)
    }
    
    try:
        print("Signal Group DM Tool")
        print("==================")
        
        # Initialize Signal CLI
        signal = SignalCLI(signal_cli_path=signal_cli_path)

        while True:
        
            # Display menu dynamically from options dict
            print("\nWhat would you like to do?")
            for key in sorted(MENU_OPTIONS.keys()):
                display_name, _ = MENU_OPTIONS[key]
                print(f"{key}. {display_name}")
            
            # Get user choice
            valid_options = set(MENU_OPTIONS.keys())
            while True:
                action = input(f"\nChoose an option ({'/'.join(sorted(valid_options))}): ").strip()
                if action in valid_options:
                    break
                print(f"Please enter {' or '.join(sorted(valid_options))}")
            
            # Execute selected option
            _, option_function = MENU_OPTIONS[action]
            option_function(signal)

        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
    except Exception as e:
        logger.error(f"Error in main: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()