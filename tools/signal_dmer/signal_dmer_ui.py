from __future__ import annotations

import hashlib
import os
import subprocess
import time
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import pandas as pd
import streamlit as st

from DMAllMembersOfASignal import (
    SignalCLI,
    default_signal_cli_path,
    load_personalization_template,
    save_personalization_template,
    use_shell_for_signal_cli,
)

TAB_EXPORT = "Export members to CSV"
TAB_VIEW = "View CSV"
TAB_SEND = "Send messages"

def _find_windows_jdk_installer() -> Optional[Path]:
    """
    If a JDK installer is shipped alongside this project, surface it in the UI.

    We prefer JDK 25 because signal-cli 0.14.x requires Java 25+.
    """
    if sys.platform != "win32":
        return None
    root = Path(__file__).resolve().parent
    candidates = sorted(root.glob("jdk-*_windows-x64_bin.exe"), key=lambda p: p.name.lower())
    if not candidates:
        return None
    # Prefer 25 if present
    for p in candidates:
        if "jdk-25" in p.name.lower():
            return p
    return candidates[-1]


def _launch_installer(exe_path: Path) -> None:
    """Launch an installer EXE without blocking the UI."""
    try:
        subprocess.Popen([str(exe_path)], shell=False)  # noqa: S603
        st.success("Installer launched. Finish the wizard, then re-run prerequisite checks.")
        st.info("After installing Java, close and reopen this browser tab (or click 'Run prerequisite checks').")
    except Exception as e:
        st.error(f"Could not launch installer: {e}")


def _java_home_walkthrough() -> None:
    st.markdown(
        """
**How to set JAVA_HOME (Windows)**

1. Press the **Windows key** and type: **Environment Variables**
2. Click **Edit the system environment variables**
3. Click **Environment Variables…**
4. Under **System variables**, click **New…**
   - **Variable name**: `JAVA_HOME`
   - **Variable value**: the JDK folder (example): `C:\\Program Files\\Java\\jdk-25`
5. Still in **System variables**, find **Path** → **Edit…** → **New…**
   - Add: `%JAVA_HOME%\\bin`
6. Click **OK** on all dialogs
7. **Close and reopen** Command Prompt / PowerShell

To verify, open a NEW Command Prompt and run:
```
java -version
```
You should see **25** (or newer).
        """.strip()
    )


def _mask(s: str, keep: int = 6) -> str:
    if not s:
        return ""
    if len(s) <= keep * 2:
        return s
    return f"{s[:keep]}…{s[-keep:]}"


def _extract_link_url(text: str) -> Optional[str]:
    for pattern in (r"sgnl://linkdevice\?[^\s]+", r"tsdevice:/\?[^\s]+"):
        m = re.search(pattern, text)
        if m:
            return m.group(0)
    return None


def _run_link_and_get_url(signal_cli_exe: str, shell: bool) -> Tuple[subprocess.Popen, str]:
    link_name = os.environ.get("SIGNAL_CLI_LINK_NAME", "signal-cli-on-desktop")
    cmd = [signal_cli_exe, "link", "-n", link_name]
    config = os.environ.get("SIGNAL_CLI_CONFIG")
    if config:
        cmd = [signal_cli_exe, "-c", config, "link", "-n", link_name]
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=shell,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    start = time.time()
    collected = ""
    url = None
    while time.time() - start < 20:
        if p.stdout is None:
            break
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            time.sleep(0.05)
            continue
        collected += line
        url = _extract_link_url(line) or url
        if url:
            break

    if not url:
        try:
            p.terminate()
        except Exception:
            pass
        raise RuntimeError(
            "Could not extract link-device URL from signal-cli output. "
            "Open 'signal_dm.log' for details, and confirm signal-cli runs on this machine."
        )
    return p, url


def _signal_cli_data_dir() -> Path:
    env = os.environ.get("SIGNAL_DM_DATA_DIR")
    if env:
        path = Path(env).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).resolve().parent / "signal_cli_data"


def _list_csv_paths() -> list[Path]:
    d = _signal_cli_data_dir()
    if not d.exists():
        return []
    return sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


def _qr_image(url: str):
    """Return PNG bytes Streamlit can display (qrcode's PilImage is not accepted as-is)."""
    import io
    import qrcode

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    raw = qr.make_image(fill_color="black", back_color="white")
    pil_img = getattr(raw, "_img", None) or raw.convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()


def _parse_java_major(version_text: str) -> Optional[int]:
    if not version_text:
        return None
    m = re.search(r'version "(\d+)', version_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _run(cmd: list[str], *, shell: bool = False, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=shell,
        timeout=timeout,
    )


def _check_python_modules() -> Dict[str, bool]:
    # We check modules (not packages) so it works across pip/apt installs.
    needed = {"qrcode": False, "PIL": False}
    for mod in needed.keys():
        try:
            __import__(mod)
            needed[mod] = True
        except Exception:
            needed[mod] = False
    return needed


def _preflight(signal_cli_path: str) -> Dict[str, Any]:
    exe = Path(signal_cli_path)
    shell = use_shell_for_signal_cli(signal_cli_path)
    java_required = signal_cli_path.lower().endswith(".bat")

    results: Dict[str, Any] = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": sys.version_info >= (3, 9),
        "python_modules": _check_python_modules(),
        "signal_cli_exists": exe.is_file(),
        "signal_cli_version_ok": False,
        "signal_cli_version_text": "",
        "java_required": java_required,
        "java_ok": None,
        "java_major": None,
    }

    results["python_deps_ok"] = all(results["python_modules"].values())

    if results["signal_cli_exists"]:
        try:
            r = _run([str(exe), "--version"], shell=shell, timeout=30)
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            results["signal_cli_version_text"] = (out[:400] + ("…" if len(out) > 400 else "")) if out else ""
            results["signal_cli_version_ok"] = (r.returncode == 0)
        except Exception as e:
            results["signal_cli_version_text"] = str(e)
            results["signal_cli_version_ok"] = False

    if java_required:
        try:
            r = _run(["java", "-version"], shell=False, timeout=20)
            out = (r.stderr or "") + (r.stdout or "")
            major = _parse_java_major(out)
            results["java_major"] = major
            results["java_ok"] = bool(major is not None and major >= 25)
        except Exception:
            results["java_major"] = None
            results["java_ok"] = False

    results["ok"] = (
        results["python_ok"]
        and results["python_deps_ok"]
        and results["signal_cli_exists"]
        and results["signal_cli_version_ok"]
        and (True if not java_required else bool(results["java_ok"]))
    )

    return results


def _pip_install_requirements() -> Tuple[bool, str]:
    try:
        req = Path(__file__).resolve().parent / "requirements.txt"
        r = _run([sys.executable, "-m", "pip", "install", "-r", str(req)], shell=False, timeout=600)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return (r.returncode == 0), (out[-4000:] if out else "")
    except Exception as e:
        return False, str(e)


st.set_page_config(page_title="Signal DM Tool", page_icon="✉️", layout="centered")
st.title("Signal Group DM Tool")
st.caption("A simple UI for exporting group members and sending DMs.")


if "signal_cli_path" not in st.session_state:
    st.session_state.signal_cli_path = str(default_signal_cli_path())
if "account" not in st.session_state:
    st.session_state.account = None
if "link_process" not in st.session_state:
    st.session_state.link_process = None
if "link_url" not in st.session_state:
    st.session_state.link_url = None
if "main_nav_tab" not in st.session_state:
    st.session_state.main_nav_tab = TAB_EXPORT
# Apply tab switches requested on the previous run (cannot mutate a widget key after it exists).
_pending_nav = st.session_state.pop("_pending_main_nav", None)
if _pending_nav in (TAB_EXPORT, TAB_VIEW, TAB_SEND):
    st.session_state.main_nav_tab = _pending_nav


def _green_check_corner() -> None:
    st.markdown(
        '<div style="text-align:right;font-size:1.75rem;line-height:1;padding-top:0.35rem">'
        '<span style="color:#22c55e;font-weight:700">✓</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def _maybe_auto_detect_account(signal_cli_path: str, pf: Dict[str, Any]) -> None:
    """When prerequisites pass, detect the linked account once per path (re-runs after path change)."""
    if not pf.get("ok"):
        return
    if st.session_state.get("_auto_acct_path") != signal_cli_path:
        st.session_state._auto_acct_path = signal_cli_path
        st.session_state._auto_acct_done = False
    if st.session_state.get("_auto_acct_done"):
        return
    try:
        cli = SignalCLI(signal_cli_path=signal_cli_path, auto_setup_account=False)
        st.session_state.account = cli.detect_registered_account()
        st.session_state._auto_account_error = None
    except Exception as e:
        st.session_state._auto_account_error = str(e)
    finally:
        st.session_state._auto_acct_done = True


# Preflight from current path so expander open/collapsed state updates on each rerun.
signal_cli_path = st.session_state.signal_cli_path
pf = _preflight(signal_cli_path)
st.session_state.preflight = pf

pr_col_left, pr_col_right = st.columns([11, 1])
with pr_col_left:
    with st.expander("Prerequisites (required first)", expanded=not pf["ok"]):
        st.write("This checks required prerequisites and offers to install missing Python packages.")

        signal_cli_path = st.text_input(
            "signal-cli path",
            value=st.session_state.signal_cli_path,
            help="Windows default is the bundled 'signal-cli-0.14.2\\bin\\signal-cli.bat'.",
        )
        st.session_state.signal_cli_path = signal_cli_path

        pf = _preflight(signal_cli_path)
        st.session_state.preflight = pf

        if st.button("Run prerequisite checks"):
            pf = _preflight(signal_cli_path)
            st.session_state.preflight = pf
            st.session_state._auto_acct_path = None
            st.session_state._auto_acct_done = False

        def _row(ok: bool, label: str, detail: str = ""):
            st.write(("✅ " if ok else "❌ ") + f"**{label}**" + (f" — {detail}" if detail else ""))

        _row(pf["python_ok"], "Python 3.9+", pf["python_version"])
        _row(
            pf["python_deps_ok"],
            "Python packages installed",
            ", ".join([k for k, v in pf["python_modules"].items() if v]) if pf["python_deps_ok"] else
            "Missing: " + ", ".join([k for k, v in pf["python_modules"].items() if not v]),
        )
        _row(pf["signal_cli_exists"], "signal-cli file exists", signal_cli_path)
        _row(
            pf["signal_cli_version_ok"],
            "signal-cli runs",
            pf["signal_cli_version_text"] or "(no output)",
        )
        if pf["java_required"]:
            _row(bool(pf["java_ok"]), "Java 25+ (required for signal-cli.bat)", f"Detected: {pf['java_major']}")
            if not pf["java_ok"]:
                st.warning(
                    "Java is required to run Signal CLI on Windows. "
                    "The app needs **Java 25+** because signal-cli 0.14.x was built for Java 25."
                )
                installer = _find_windows_jdk_installer()
                if installer:
                    st.write(f"Good news: a Java installer was found next to this app: `{installer.name}`")
                    if st.button("Install Java now (recommended)", key="install_java_btn"):
                        _launch_installer(installer)
                else:
                    st.info(
                        "No bundled Java installer was found. Install **JDK 25** (recommended) from Adoptium "
                        "or run the included installer if you have one."
                    )
                    st.code("https://adoptium.net/", language="text")

                with st.expander("Step-by-step: fix JAVA_HOME / java on PATH", expanded=False):
                    _java_home_walkthrough()
        else:
            st.write("✅ **Java** — not required for this `signal-cli` binary/launcher")

        col_i, col_j = st.columns(2)
        with col_i:
            if st.button("Install/Update Python dependencies"):
                ok, out = _pip_install_requirements()
                if ok:
                    st.success("Python dependencies installed. Re-running checks…")
                else:
                    st.error("Install failed. Output below.")
                if out:
                    st.code(out, language="text")
                pf = _preflight(signal_cli_path)
                st.session_state.preflight = pf
                st.session_state._auto_acct_path = None
                st.session_state._auto_acct_done = False

        with col_j:
            if not pf["java_required"] or pf["java_ok"]:
                st.success("Ready to continue.")
            else:
                st.warning("Install Java 25+, then re-run checks.")

with pr_col_right:
    if st.session_state.preflight.get("ok"):
        _green_check_corner()

pf = st.session_state.preflight
signal_cli_path = st.session_state.signal_cli_path

prev_pf_ok = st.session_state.get("_prev_pf_ok_state")
curr_pf_ok = bool(pf.get("ok"))
if prev_pf_ok is False and curr_pf_ok:
    st.session_state._auto_acct_done = False
st.session_state._prev_pf_ok_state = curr_pf_ok

# Auto-detect linked account once prerequisites pass (after path / checks are synced).
_maybe_auto_detect_account(signal_cli_path, pf)

account_ok = bool(st.session_state.account)
# Expand Setup only when prerequisites pass but no linked account yet.
setup_expanded = bool(pf.get("ok")) and not account_ok

su_col_left, su_col_right = st.columns([11, 1])
with su_col_left:
    with st.expander("Setup (link your Signal account)", expanded=setup_expanded):
        if not pf.get("ok"):
            st.info("Complete the prerequisites above first.")
        st.write("Link once (QR), then use Export / Send tabs.")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Check account"):
                try:
                    s = SignalCLI(signal_cli_path=signal_cli_path, auto_setup_account=False)
                    acct = s.detect_registered_account()
                    st.session_state.account = acct
                    st.session_state._auto_acct_done = True
                    if acct:
                        st.success(f"Linked account found: `{acct}`")
                    else:
                        st.warning("No linked account found yet. Use 'Start linking (QR)'.")
                except Exception as e:
                    st.error(str(e))

        with col_b:
            if st.button("Start linking (QR)"):
                try:
                    shell = use_shell_for_signal_cli(signal_cli_path)
                    p, url = _run_link_and_get_url(signal_cli_path, shell=shell)
                    st.session_state.link_process = p
                    st.session_state.link_url = url
                    st.session_state.account = None
                    st.success("QR ready. Scan it with Signal, then click 'Finish linking'.")
                except Exception as e:
                    st.error(str(e))

        err = st.session_state.get("_auto_account_error")
        if err and pf.get("ok") and not st.session_state.account:
            st.warning(f"Automatic account check failed: {err}")

        if st.session_state.link_url:
            st.subheader("Scan this QR code")
            st.image(_qr_image(st.session_state.link_url), caption="Signal → Settings → Linked Devices → Link New Device")
            st.code(st.session_state.link_url, language="text")

            if st.button("Finish linking"):
                p = st.session_state.link_process
                try:
                    if p and p.poll() is None:
                        try:
                            p.terminate()
                            p.wait(timeout=5)
                        except Exception:
                            try:
                                p.kill()
                            except Exception:
                                pass

                    s = SignalCLI(signal_cli_path=signal_cli_path, auto_setup_account=False)
                    acct = s.detect_registered_account()
                    st.session_state.account = acct
                    st.session_state.link_process = None
                    st.session_state.link_url = None
                    if acct:
                        st.success(f"Linked! Account: `{acct}`")
                    else:
                        st.warning("Still no account detected. If your phone didn't finish linking, try again.")
                except Exception as e:
                    st.error(str(e))

with su_col_right:
    if account_ok:
        _green_check_corner()


main_nav = st.radio(
    "Section",
    options=[TAB_EXPORT, TAB_VIEW, TAB_SEND],
    horizontal=True,
    label_visibility="collapsed",
    key="main_nav_tab",
)


def _get_signal_ready() -> SignalCLI:
    pf = st.session_state.get("preflight") or _preflight(st.session_state.signal_cli_path)
    if not pf.get("ok"):
        raise RuntimeError("Prerequisites are not satisfied yet. Use the Prerequisites section first.")
    s = SignalCLI(signal_cli_path=st.session_state.signal_cli_path, auto_setup_account=False)
    acct = st.session_state.account or s.detect_registered_account()
    if not acct:
        raise RuntimeError("No linked Signal account detected yet. Use Setup → Start linking (QR).")
    s.set_account(acct)
    st.session_state.account = acct
    return s


if main_nav == TAB_EXPORT:
    st.subheader("Export group members")
    st.write(
        "This creates a CSV in `signal_cli_data/` — after export you’ll jump to **View CSV** "
        "to edit `custom_display_name` (or open it in Excel if you prefer)."
    )
    if not (st.session_state.get("preflight") or {}).get("ok"):
        st.info("Complete Prerequisites first.")
        st.stop()

    if st.button("Load groups"):
        try:
            s = _get_signal_ready()
            st.session_state.groups = s.list_groups()
        except Exception as e:
            st.error(str(e))

    groups = st.session_state.get("groups") or []
    if groups:
        group_name = st.selectbox("Choose a group", options=[g["name"] for g in groups])
        selected = next(g for g in groups if g["name"] == group_name)
        if st.button("Export CSV"):
            try:
                s = _get_signal_ready()
                csv_path = s.export_group_members_to_csv(selected["id"], selected["name"])
                st.session_state.view_csv_focus_name = Path(csv_path).name
                st.session_state._export_just_completed = True
                st.session_state._pending_main_nav = TAB_VIEW
                st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        st.info("Click 'Load groups' first.")


elif main_nav == TAB_VIEW:
    st.subheader("View CSV")
    if st.session_state.pop("_export_just_completed", None):
        st.success("Export complete — the new file is selected below. Edit, then **Save CSV** when done.")
    st.write(
        "Open any exported CSV from `signal_cli_data/`, edit columns like `custom_display_name`, "
        "then save. Use **Send messages** → CSV file when you’re ready to message."
    )
    paths = _list_csv_paths()
    if not paths:
        st.info("No CSV files yet — export a group first on the Export tab.")
    else:
        names = [p.name for p in paths]
        focus = st.session_state.pop("view_csv_focus_name", None)
        default_ix = names.index(focus) if focus and focus in names else 0

        picked = st.selectbox("CSV file", options=names, index=min(default_ix, len(names) - 1))

        picked_path = _signal_cli_data_dir() / picked
        picked_h = hashlib.md5(picked.encode("utf-8")).hexdigest()

        sync_key = "_view_csv_loaded_name"
        if st.session_state.get(sync_key) != picked:
            try:
                st.session_state["_view_csv_df_cache"] = pd.read_csv(
                    picked_path,
                    dtype=str,
                    keep_default_na=False,
                )
                st.session_state["_view_csv_table_err"] = None
            except Exception as e:
                st.session_state["_view_csv_df_cache"] = None
                st.session_state["_view_csv_table_err"] = str(e)
            st.session_state[sync_key] = picked

        err = st.session_state.get("_view_csv_table_err")
        df = st.session_state.get("_view_csv_df_cache")
        if err or df is None:
            st.error(f"Could not load this file as a table: {err or 'unknown error'}")
            try:
                raw = picked_path.read_text(encoding="utf-8")
                st.text_area("Raw file contents", value=raw, height=300, disabled=True)
            except OSError:
                pass
        else:
            st.caption(
                "Edit cells in the table (e.g. custom_display_name for greetings). "
                "Avoid changing column names — the Send step expects the same headers."
            )
            edited = st.data_editor(
                df,
                key=f"csv_data_editor_{picked_h}",
                use_container_width=True,
                height=420,
                num_rows="fixed",
                hide_index=True,
            )

            row_save, _ = st.columns([1, 4])
            with row_save:
                if st.button("Save CSV"):
                    try:
                        edited.to_csv(picked_path, index=False, encoding="utf-8")
                        st.session_state["_view_csv_df_cache"] = pd.read_csv(
                            picked_path,
                            dtype=str,
                            keep_default_na=False,
                        )
                        st.success(f"Saved `{picked}`.")
                    except OSError as e:
                        st.error(f"Could not save: {e}")

elif main_nav == TAB_SEND:
    st.subheader("Send DMs")
    st.write("Tip: For large groups, use sequential mode with a bigger delay.")
    if not (st.session_state.get("preflight") or {}).get("ok"):
        st.info("Complete Prerequisites first.")
        st.stop()

    mode = st.radio("Recipient source", options=["Group", "CSV file"], horizontal=True)

    group_id = None
    csv_path = None

    if mode == "Group":
        if st.button("Load groups", key="load_groups_send"):
            try:
                s = _get_signal_ready()
                st.session_state.groups_send = s.list_groups()
            except Exception as e:
                st.error(str(e))

        groups_send = st.session_state.get("groups_send") or []
        if groups_send:
            group_name = st.selectbox("Choose group", options=[g["name"] for g in groups_send], key="send_group_name")
            selected = next(g for g in groups_send if g["name"] == group_name)
            group_id = selected["id"]
        else:
            st.info("Load groups to choose a group.")
    else:
        st.write("Pick a CSV from `signal_cli_data/` and send to its rows.")
        csv_files = _list_csv_paths()
        if not csv_files:
            st.info("No CSV files found yet. Use the Export tab first.")
        else:
            csv_choice = st.selectbox("CSV file", options=[p.name for p in csv_files])
            csv_path = str(next(p for p in csv_files if p.name == csv_choice))

    st.divider()

    message1 = st.text_area("Message (first)", height=160, placeholder="Type your message…")
    message2_enabled = st.checkbox("Send a second message")
    message2 = ""
    message_delay = 10.0
    if message2_enabled:
        message2 = st.text_area("Message (second)", height=120, key="send_message_second")
        message_delay = float(
            st.slider("Delay between message 1 and 2 (seconds)", min_value=1, max_value=10, value=10)
        )

    personalize = st.checkbox("Personalize greeting (uses your personalization template + names when available)", value=True)

    if personalize:
        st.caption(
            "Edit the greeting that is prepended to your message when a display name is known. "
            "Use `{display_name}` where each recipient’s name should go."
        )
        st.text_area(
            "Personalization greeting template",
            value=load_personalization_template(),
            height=140,
            key="personalization_tpl_editor",
            help="Stored in signal_cli_data/personalization.txt",
        )
        bsave, _ = st.columns([1, 4])
        with bsave:
            if st.button("Save greeting template"):
                text = str(st.session_state.get("personalization_tpl_editor", "")).strip()
                if not text:
                    st.warning("Template cannot be empty.")
                else:
                    if "{display_name}" not in text:
                        st.warning(
                            "Recommended: include `{display_name}` so recipient names can be inserted."
                        )
                    if save_personalization_template(text):
                        st.success("Saved to signal_cli_data/personalization.txt")
                    else:
                        st.error("Could not save personalization.txt.")

    send_mode = st.radio("Send mode", options=["Sequential (safer)", "Parallel (faster)"], horizontal=True)
    if send_mode.startswith("Sequential"):
        delay = st.number_input("Base delay between recipients (seconds)", min_value=1, max_value=600, value=30)
        parallel = False
        max_workers = 1
    else:
        max_workers = st.number_input("Parallel workers", min_value=1, max_value=5, value=3)
        parallel = True
        delay = 0

    if mode == "Group":
        can_send = bool(group_id and message1.strip())
        if st.button("Send now", disabled=not can_send):
            try:
                s = _get_signal_ready()
                st.write(f"Using account: `{st.session_state.account}`")
                with st.spinner("Fetching members…"):
                    members = s.get_group_members(group_id)
                st.write(f"Recipients: **{len(members)}**")

                second = message2.strip() if (message2_enabled and message2 and message2.strip()) else None
                with st.spinner("Sending… (watch `signal_dm.log` for live details)"):
                    if parallel:
                        results = s._send_messages_parallel(
                            members, message1, int(max_workers), personalize, second, float(message_delay)
                        )
                    else:
                        results = s._send_messages_sequential(
                            members, message1, int(delay), personalize, second, float(message_delay)
                        )

                success = sum(1 for v in results.values() if v)
                st.success(f"Done. Successful: {success}/{len(results)}")
                with st.expander("Details"):
                    for ident, ok in results.items():
                        st.write(("✅" if ok else "❌") + f" `{_mask(ident)}`")
            except Exception as e:
                st.error(str(e))

    else:
        can_send = bool(csv_path and message1.strip())
        if st.button("Send now (CSV)", disabled=not can_send):
            try:
                s = _get_signal_ready()
                members = s.load_members_from_csv(csv_path)
                st.write(f"Recipients: **{len(members)}**")

                second = message2.strip() if (message2_enabled and message2 and message2.strip()) else None
                with st.spinner("Sending… (watch `signal_dm.log` for live details)"):
                    if parallel:
                        results = s._send_messages_parallel(
                            members, message1, int(max_workers), personalize, second, float(message_delay)
                        )
                    else:
                        results = s._send_messages_sequential(
                            members, message1, int(delay), personalize, second, float(message_delay)
                        )

                success = sum(1 for v in results.values() if v)
                st.success(f"Done. Successful: {success}/{len(results)}")
                with st.expander("Details"):
                    for ident, ok in results.items():
                        st.write(("✅" if ok else "❌") + f" `{_mask(ident)}`")
            except Exception as e:
                st.error(str(e))

