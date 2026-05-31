"""LinkedInScript setup — single-command installer.

Handles:
1. Checks Python version (requires 3.9+), installs via winget if missing/old
2. Creates virtual environment
3. Installs pip dependencies
4. Installs Playwright Chromium
5. Generates config.yaml

Run: python setup.py
Or if Python is too old/missing: download from python.org and run again.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 9)
MAX_PYTHON = (3, 12)  # numpy/pandas don't ship wheels for 3.13+ yet
IDEAL_PYTHON = "3.12"


def check_python_version():
    """Check if current Python is in the supported range (3.9–3.12)."""
    if MIN_PYTHON <= sys.version_info[:2] <= MAX_PYTHON:
        return True
    return False


def find_suitable_python():
    """Try to find Python 3.9–3.12 on the system using py launcher."""
    try:
        result = subprocess.run(
            ["py", "--list"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            # Prefer 3.12, then 3.11, 3.10, 3.9
            candidates = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("-"):
                    version_str = line.split()[0].lstrip("-V:")
                    try:
                        parts = version_str.split(".")
                        major, minor = int(parts[0]), int(parts[1])
                        if MIN_PYTHON <= (major, minor) <= MAX_PYTHON:
                            candidates.append((major, minor))
                    except (ValueError, IndexError):
                        continue
            if candidates:
                best = max(candidates)
                return f"py -{best[0]}.{best[1]}"
    except FileNotFoundError:
        pass
    return None


def _find_python312_path():
    """Find python 3.12 executable after installation."""
    # Check common install locations on Windows
    common_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe",
        Path("C:/Python312/python.exe"),
        Path("C:/Program Files/Python312/python.exe"),
        Path("C:/Program Files (x86)/Python312/python.exe"),
        Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "python.exe",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)

    # Try py launcher (may pick it up immediately)
    try:
        result = subprocess.run(
            ["py", "-3.12", "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    return None


def install_python():
    """Install Python 3.12 via winget and return the path to it."""
    print(f"\n  Installing Python 3.12 via winget...")
    try:
        result = subprocess.run(
            ["winget", "install", "Python.Python.3.12",
             "--accept-package-agreements", "--accept-source-agreements",
             "--silent"],
            check=False,
        )
        if result.returncode == 0:
            print("  Python 3.12 installed!")
            # Find the newly installed Python
            py_path = _find_python312_path()
            if py_path:
                print(f"  Found at: {py_path}")
                return py_path
            else:
                print("\n  Installed but could not locate python.exe.")
                print("  Close this terminal, open a new one, and re-run:")
                print(f"    cd {PROJECT_ROOT}")
                print("    python setup.py")
                return None
        else:
            print("  winget install failed (may need admin privileges).")
    except FileNotFoundError:
        print("  winget not available on this system.")

    # Fallback: direct download instructions
    print(f"\n  Please install Python 3.12 manually:")
    print(f"    https://www.python.org/downloads/release/python-3129/")
    print(f"  Check 'Add Python to PATH' during installation.")
    print(f"  Then re-run: python setup.py")
    print(f"\n  Note: Python 3.13+ is NOT supported (numpy/pandas lack pre-built wheels).")
    return None


def create_venv(python_cmd):
    """Create virtual environment."""
    venv_path = PROJECT_ROOT / ".venv"
    if venv_path.exists():
        print("[2/5] Virtual environment already exists.")
        return True

    print("[2/5] Creating virtual environment...")
    if isinstance(python_cmd, str) and python_cmd.startswith("py "):
        cmd = python_cmd.split() + ["-m", "venv", str(venv_path)]
    else:
        cmd = [python_cmd, "-m", "venv", str(venv_path)]

    result = subprocess.run(cmd, check=False)
    if result.returncode == 0:
        print("  .venv created.")
        return True
    else:
        print("  Failed to create venv.")
        return False


def get_venv_python():
    """Get the path to Python inside the venv."""
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    # Linux/Mac fallback
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return None


def install_dependencies(python_path):
    """Install pip packages and Playwright."""
    print("[3/5] Installing Python packages...")
    req_file = PROJECT_ROOT / "requirements.txt"
    result = subprocess.run(
        [python_path, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
        check=False,
    )
    result = subprocess.run(
        [python_path, "-m", "pip", "install", "-r", str(req_file), "--quiet"],
        check=False,
    )
    if result.returncode != 0:
        print("  WARNING: pip install had issues. Run manually:")
        print(f"    {python_path} -m pip install -r requirements.txt")
    else:
        print("  Packages installed.")

    print("[4/5] Installing Playwright Chromium...")
    result = subprocess.run(
        [python_path, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print("  WARNING: Playwright install had issues. Run manually:")
        print(f"    {python_path} -m playwright install chromium")
    else:
        print("  Chromium browser installed.")


def generate_config():
    """Copy config.example.yaml to config.yaml if missing."""
    config_path = PROJECT_ROOT / "config.yaml"
    example_path = PROJECT_ROOT / "config.example.yaml"

    if config_path.exists():
        print("[5/5] config.yaml already exists.")
        return

    if example_path.exists():
        import shutil
        shutil.copy(example_path, config_path)
        print("[5/5] config.yaml created from template.")
    else:
        print("[5/5] WARNING: config.example.yaml not found.")


def main():
    print()
    print("=" * 50)
    print("  LinkedInScript Setup")
    print("=" * 50)
    print()

    # Step 1: Check Python version
    print(f"[1/5] Checking Python version (need 3.9–3.12)...")
    if check_python_version():
        print(f"  Python {sys.version_info.major}.{sys.version_info.minor} — OK")
        python_cmd = sys.executable
    else:
        if sys.version_info[:2] > MAX_PYTHON:
            print(f"  Python {sys.version_info.major}.{sys.version_info.minor} — too new (numpy lacks wheels)")
        else:
            print(f"  Python {sys.version_info.major}.{sys.version_info.minor} — too old")
        print(f"  Looking for Python 3.9–3.12 on this system...")
        suitable = find_suitable_python()
        if suitable:
            print(f"  Found: {suitable}")
            python_cmd = suitable
        else:
            installed_path = install_python()
            if installed_path:
                python_cmd = installed_path
            else:
                sys.exit(1)

    # Step 2: Create venv
    if not create_venv(python_cmd):
        sys.exit(1)

    # Step 3-4: Install dependencies
    venv_python = get_venv_python()
    if not venv_python:
        print("ERROR: Could not find Python in .venv")
        sys.exit(1)

    install_dependencies(venv_python)

    # Step 5: Generate config
    generate_config()

    # Done
    print()
    print("=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print()
    print("  1. Create .env file with your email password:")
    print("     EMAIL_PASSWORD=your_gmail_app_password")
    print()
    print("  2. Edit config.yaml (email settings, keywords, etc.)")
    print()
    print("  3. Activate the environment and run:")
    if os.name == "nt":
        print("     .venv\\Scripts\\activate")
    else:
        print("     source .venv/bin/activate")
    print("     python main.py --test-email")
    print("     python main.py --dry-run")
    print("     python main.py --install    (schedule daily runs)")
    print()


if __name__ == "__main__":
    main()
