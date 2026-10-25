"""kaggle_train: run a training script/notebook/project on Kaggle's free GPU, watch it, download results (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="watch", safety="safe",
      description="Train on Kaggle's free GPU: send a .py/.ipynb or project folder, watch it, download the results "
                  "when done (desktop + Telegram alert); or show the runs' status; or set up the Kaggle tool.")
def kaggle_train(action: Literal["run", "status", "setup"] = "run", path: str = "", gpu: bool = True) -> str:
    """Kaggle GPU.

    Args:
        action: run (send path), status (recent runs), setup (install the Kaggle tool once).
        path: The script, notebook or project folder (loose names / 'this' work).
        gpu: Use a GPU (True) or CPU only.
    """
    from jarvis.core import kaggle_gpu as kg
    try:
        if action == "setup":
            return kg.setup()
        if action == "status":
            return kg.status_text()
        from jarvis.core.paths import resolve_target
        target = resolve_target(path or "this")
        if isinstance(target, str):
            return target
        return kg.run(target, gpu)
    except kg.KaggleError as e:
        return f"error: {e}"
