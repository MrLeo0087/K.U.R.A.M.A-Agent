"""python_env: check a Python environment, or install a missing module into the RIGHT project venv (safe; installing
asks first and warns about heavy packages like torch). Replaces env_doctor (alias kept)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Literal

from jarvis.core import safety
from jarvis.core.registry import alias, tool

# import name -> pip name, for the usual mismatches
PIP_NAME = {"cv2": "opencv-python", "sklearn": "scikit-learn", "PIL": "pillow", "yaml": "pyyaml", "bs4": "beautifulsoup4",
            "dotenv": "python-dotenv", "skimage": "scikit-image", "Crypto": "pycryptodome", "docx": "python-docx",
            "pptx": "python-pptx", "fitz": "pymupdf", "dateutil": "python-dateutil", "jwt": "pyjwt", "magic": "python-magic",
            "serial": "pyserial", "usb": "pyusb", "attr": "attrs", "google.generativeai": "google-generativeai",
            "tensorflow_datasets": "tensorflow-datasets", "sentence_transformers": "sentence-transformers",
            "faiss": "faiss-cpu", "gi": "PyGObject", "speech_recognition": "SpeechRecognition", "telegram": "python-telegram-bot"}
HEAVY = ("torch", "tensorflow", "jax", "jaxlib", "torchvision", "torchaudio", "xformers", "nvidia-", "cupy", "triton",
         "bitsandbytes", "vllm", "deepspeed", "flash-attn")


def project_python(folder: Path) -> tuple[str, str]:
    """(python of the project's venv or the system python3, where it came from)."""
    for p in [folder, *folder.parents][:4]:
        for name in ("venv", ".venv", "env"):
            py = p / name / "bin" / "python"
            if py.is_file():
                return str(py), f"{p.name}/{name}"
    return "python3", "system python (no venv found: consider python3 -m venv .venv)"


def pip_name(text: str) -> str:
    m = re.search(r"No module named ['\"]?([\w.]+)", text)
    mod = m.group(1) if m else text.strip().split()[0]
    return PIP_NAME.get(mod, PIP_NAME.get(mod.split(".")[0], mod.split(".")[0].replace("_", "-")))


@tool(group="dev", safety="safe",
      description="Python environment: check it (python/venv/pip, disk, RAM, tools), or install a missing module / "
                  "package into the right project venv (from a ModuleNotFoundError or a name; asks first).")
def python_env(action: Literal["check", "install"] = "check", package: str = "", folder: str = ".") -> str:
    """Python environment.

    Args:
        action: check = environment report; install = pip install `package` into `folder`'s venv.
        package: A package name, an import name (cv2, sklearn) or the error text ("No module named 'timm'").
        folder: The project folder (loose names work); its venv/.venv/env is used.
    """
    from jarvis.tools.interactive import _proc
    try:
        wd = _proc.resolve_dir(folder or ".")
    except _proc.ProcError as e:
        return f"error: {e}"
    if action == "check":
        from jarvis.tools.interactive.env_doctor import env_doctor
        return env_doctor(str(wd))
    if not package.strip():
        return "error: which package should I install?"
    pkg = pip_name(package)
    if not re.fullmatch(r"[A-Za-z0-9][\w.\-]*(?:\[[\w,\-]+\])?(?:[=<>!~]=?[\w.*]+)?", pkg):
        return f"error: {pkg!r} doesn't look like a package name"
    py, where = project_python(wd)
    heavy = any(pkg.lower().startswith(h) for h in HEAVY)
    warn = (" It is HEAVY (GPU/CUDA libraries, often 2+ GB); on this laptop prefer the CPU build or Colab."
            if heavy else "")
    if not safety.ask(f"Install {pkg} into {where}?{warn}"):
        return "The user said no, so nothing was installed."
    args = [py, "-m", "pip", "install", "--disable-pip-version-check", pkg]
    if heavy and pkg.lower().startswith("torch"):
        args += ["--index-url", "https://download.pytorch.org/whl/cpu"]  # CPU wheels: no CUDA download
    try:
        cp = subprocess.run(args, capture_output=True, text=True, timeout=900, cwd=wd)
    except subprocess.TimeoutExpired:
        return "error: pip took longer than 15 minutes; try it in a terminal."
    if cp.returncode != 0:
        last = [ln for ln in (cp.stderr or cp.stdout).splitlines() if ln.strip()][-3:]
        return f"pip failed for {pkg} in {where}:\n" + "\n".join(last)
    done = [ln for ln in cp.stdout.splitlines() if ln.startswith("Successfully installed")]
    return (done[-1] if done else f"{pkg} is already installed") + f" ({where})."


alias("env_doctor", "python_env", lambda a: {"folder": a.get("path", ".")}, action="check")
