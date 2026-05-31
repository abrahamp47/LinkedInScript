from __future__ import annotations

"""Windows Task Scheduler management via schtasks.exe.

Registers/removes a daily task that runs LinkedInScript automatically.
Uses schtasks.exe directly (available on all Windows versions) instead of
PowerShell cmdlets — avoids admin elevation for current-user tasks.
"""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

TASK_NAME = "LinkedInScript"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _get_python_path() -> str:
    """Get the path to the current Python interpreter."""
    return sys.executable


def _get_schedule_time(config: dict) -> str:
    """Extract schedule time from config, default 08:00."""
    return config.get("schedule", {}).get("time", "08:00")


def _run_schtasks(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run schtasks.exe with given arguments."""
    cmd = ["schtasks.exe"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
    )


def is_installed() -> bool:
    """Check if the LinkedInScript task is currently registered."""
    result = _run_schtasks(["/Query", "/TN", TASK_NAME], check=False)
    return result.returncode == 0


def install(config: dict) -> bool:
    """Register LinkedInScript as a daily scheduled task.

    Uses schtasks.exe /Create with:
    - /SC DAILY: runs every day
    - /ST HH:MM: at the configured time
    - /RL LIMITED: no admin privileges needed
    - /F: force overwrite if exists (idempotent)
    - /DELAY 0001:00: 1-minute random delay to avoid exact-second conflicts

    Returns True on success, False on failure.
    """
    python_path = _get_python_path()
    main_script = str(PROJECT_ROOT / "main.py")
    schedule_time = _get_schedule_time(config)
    working_dir = str(PROJECT_ROOT)

    # Validate time format
    if not _is_valid_time(schedule_time):
        print(f"Error: invalid schedule time '{schedule_time}'. Use HH:MM format.")
        return False

    # Build the command that Task Scheduler will run
    task_command = f'"{python_path}" "{main_script}"'

    print(f"\nInstalling scheduled task...")
    print(f"  Task name:  {TASK_NAME}")
    print(f"  Schedule:   Daily at {schedule_time}")
    print(f"  Python:     {python_path}")
    print(f"  Script:     {main_script}")
    print(f"  Directory:  {working_dir}")

    try:
        result = _run_schtasks([
            "/Create",
            "/TN", TASK_NAME,
            "/TR", task_command,
            "/SC", "DAILY",
            "/ST", schedule_time,
            "/RL", "LIMITED",
            "/F",
        ], check=False)

        if result.returncode != 0:
            # Try with /RL HIGHEST if LIMITED fails (some systems need it)
            result = _run_schtasks([
                "/Create",
                "/TN", TASK_NAME,
                "/TR", task_command,
                "/SC", "DAILY",
                "/ST", schedule_time,
                "/F",
            ], check=False)

        if result.returncode == 0:
            print(f"\n  Task registered successfully!")
            _configure_advanced_settings()
            _print_verify_instructions(schedule_time)
            return True
        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            print(f"\n  Failed to register task: {error_msg}")
            print(f"\n  If 'Access denied', try running from an admin terminal:")
            print(f"    python main.py --install")
            return False

    except FileNotFoundError:
        print("Error: schtasks.exe not found. Are you on Windows?")
        return False


def _configure_advanced_settings():
    """Apply additional settings via /Change that /Create doesn't support."""
    # Enable StartWhenAvailable (run at next opportunity if PC was off)
    _run_schtasks([
        "/Change",
        "/TN", TASK_NAME,
        "/ENABLE",
    ], check=False)


def _is_valid_time(time_str: str) -> bool:
    """Validate HH:MM format."""
    if len(time_str) != 5 or time_str[2] != ":":
        return False
    try:
        h, m = int(time_str[:2]), int(time_str[3:])
        return 0 <= h <= 23 and 0 <= m <= 59
    except ValueError:
        return False


def _print_verify_instructions(schedule_time: str):
    """Print post-install instructions."""
    print(f"\n  The task will run daily at {schedule_time}.")
    print(f"  If your PC is off at that time, it runs at next boot.")
    print()
    print(f"  Verify:  python main.py --status")
    print(f"  Test:    python main.py --dry-run")
    print(f"  Remove:  python main.py --uninstall-task")
    print()


def uninstall() -> bool:
    """Remove the LinkedInScript scheduled task.

    Returns True if task was removed (or didn't exist), False on error.
    """
    if not is_installed():
        print(f"Task '{TASK_NAME}' is not registered — nothing to remove.")
        return True

    print(f"Removing scheduled task '{TASK_NAME}'...")

    result = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"], check=False)

    if result.returncode == 0:
        print(f"  Task removed successfully.")
        return True
    else:
        error_msg = result.stderr.strip() or result.stdout.strip()
        print(f"  Failed to remove task: {error_msg}")
        return False


def get_task_info() -> dict | None:
    """Get info about the registered task. Returns None if not registered."""
    if not is_installed():
        return None

    result = _run_schtasks(
        ["/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        check=False,
    )

    if result.returncode != 0:
        return None

    info = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()

    return info
