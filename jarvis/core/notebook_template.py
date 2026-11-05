"""The ready-to-run training notebook (.ipynb) that links a Colab or Kaggle run to KURAMA. 0 tokens: a fixed
template, never AI-written code. Steps are markdown cells in plain words; the code cells run as they are.

    build(cell, platform)  ->  notebook JSON text
      cell      the KURAMA link cell (training.colab_cell: this laptop's private channel + the run's name)
      platform  "colab" | "kaggle" (only the setup steps differ; the link cell works on both)
"""
from __future__ import annotations

import json

_GPU = {
    "colab": "**Runtime → Change runtime type → T4 GPU → Save.** (Free; a session stops after ~12 h or when idle.)",
    "kaggle": ("**Right panel → Session options → Accelerator → GPU T4 x2**, and **Internet → On** (Internet needs a "
               "phone-verified Kaggle account: Settings → Phone verification). Free: ~30 GPU hours a week."),
}
_OPEN = {
    "colab": "Open https://colab.research.google.com → **File → Upload notebook** → choose this file.",
    "kaggle": "Open https://www.kaggle.com/code → **New Notebook** → **File → Import Notebook** → choose this file.",
}
_DATA = {
    "colab": ("Your data: upload it (left bar → Files), or keep it on Google Drive (the next cell mounts it, so "
              "checkpoints saved under `/content/drive/MyDrive` survive the session)."),
    "kaggle": ("Your data: **Add Input** (right panel) → a Kaggle dataset or your own upload. It appears under "
               "`/kaggle/input/<name>/`. Save outputs in `/kaggle/working/` (kept after the run as Output)."),
}
_DATA_CODE = {
    "colab": ("# Optional: Google Drive (skip if your data is uploaded or downloaded in the notebook)\n"
              "from google.colab import drive\n"
              "drive.mount('/content/drive')\n"
              "import os; os.makedirs('/content/drive/MyDrive/kurama_runs', exist_ok=True)\n"),
    "kaggle": ("# Your inputs (Add Input in the right panel) are listed here\n"
               "import os\n"
               "for root, dirs, files in os.walk('/kaggle/input'):\n"
               "    print(root, len(files), 'files')\n"
               "os.chdir('/kaggle/working')  # outputs saved here are kept\n"),
}
_SECRETS = {
    "colab": "left bar → **key icon (Secrets)** → add `KURAMA_TG_TOKEN` and `KURAMA_TG_CHAT`, turn on notebook access",
    "kaggle": "**Add-ons → Secrets** → add `KURAMA_TG_TOKEN` and `KURAMA_TG_CHAT`, tick them for this notebook",
}

GPU_CHECK = """# Is the GPU on? (it prints the GPU name; "False" means the runtime has no GPU yet: see step 1)
import subprocess, sys
print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"], capture_output=True, text=True).stdout or "no GPU")
try:
    import torch
    print("torch", torch.__version__, "CUDA:", torch.cuda.is_available())
except ImportError:
    print("torch not installed")
"""

PYTORCH_DEMO = """# A complete, tiny PyTorch training that reports to KURAMA (runs in seconds, on GPU or CPU).
# Replace the data, model and loop with yours: keep the three KURAMA lines marked  # <- KURAMA
import torch, torch.nn as nn

device = "cuda" if torch.cuda.is_available() else "cpu"
X = torch.randn(4000, 20)
y = (X[:, :5].sum(1) > 0).long()
model = nn.Sequential(nn.Linear(20, 64), nn.ReLU(), nn.Linear(64, 2)).to(device)
opt = torch.optim.Adam(model.parameters(), lr=1e-3)
loss_fn = nn.CrossEntropyLoss()
EPOCHS = 10

for epoch in range(1, EPOCHS + 1):
    model.train()
    perm = torch.randperm(len(X))
    for i in range(0, len(X), 64):
        idx = perm[i:i + 64]
        xb, yb = X[idx].to(device), y[idx].to(device)
        opt.zero_grad()
        loss = loss_fn(model(xb), yb)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        acc = (model(X.to(device)).argmax(1).cpu() == y).float().mean().item()
    print(f"epoch {epoch}/{EPOCHS}  loss {loss.item():.4f}  acc {acc:.3f}")
    kurama(epoch=epoch, epochs=EPOCHS, loss=loss.item(), acc=acc)   # <- KURAMA: progress
    if kurama_should_stop():                                         # <- KURAMA: you said "stop training"
        print("KURAMA asked to stop: saving and ending")
        break

torch.save(model.state_dict(), "model.pt")
kurama("done", loss=loss.item(), acc=acc)                            # <- KURAMA: finished
print(kurama_send("model.pt"))  # the checkpoint arrives on your laptop (data/outputs/colab/...)
"""

KERAS = """# Keras / TensorFlow: one callback does everything (progress, stop, done)
# model.fit(x_train, y_train, epochs=20, validation_data=(x_val, y_val), callbacks=[KuramaKeras()])
# model.save("model.keras"); print(kurama_send("model.keras"))
"""

HF = """# Hugging Face Trainer: one callback does everything (progress, stop, done)
# from transformers import Trainer
# trainer = Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds,
#                   callbacks=[KuramaCallback()])
# trainer.train(); trainer.save_model("out"); print(kurama_send("out/model.safetensors"))
"""


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(keepends=True)}


def _code(src: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": src.strip("\n").splitlines(keepends=True)}


def build(cell: str, platform: str = "colab") -> str:
    """The whole notebook as .ipynb JSON (nbformat 4)."""
    p = "kaggle" if platform == "kaggle" else "colab"
    name = "Kaggle" if p == "kaggle" else "Google Colab"
    cells = [
        _md(f"""# KURAMA training notebook ({name})
This notebook trains on the free GPU and **reports to KURAMA on your laptop**: live epochs, loss and accuracy
("how is my training going?"), an alert when it finishes, fails or the loss becomes NaN, "stop training" from your
laptop or phone, and the finished model sent back to your laptop.

**How to use it (once):**
0. {_OPEN[p]}
1. {_GPU[p]}
2. Run the cells **from top to bottom** (Shift+Enter). Cell 3 (the KURAMA link) must run before your training.
3. Train: run the demo (cell 5) to see it working, then put your own training in its place.
4. On the laptop say **"training status"**, **"stop training"** (after this epoch) or **"stop training now"**."""),
        _md("## 1. Check the GPU"),
        _code(GPU_CHECK),
        _md(f"## 2. Your data\n{_DATA[p]}"),
        _code(_DATA_CODE[p]),
        _md("""## 3. Link this run to KURAMA (run once, at the top)
It prints `KURAMA is linked to this notebook`, and KURAMA says the run started. It only sends numbers (epoch,
loss, accuracy...) over a private channel made for your laptop, never your data or code.
It works while your laptop sleeps: KURAMA catches up when it wakes. For alerts on your phone even when the laptop
is off, add two secrets (optional): """ + _SECRETS[p] + "."),
        _code(cell),
        _md("## 4. Test the link (optional)\nKURAMA shows this run in \"training status\" within a minute."),
        _code('kurama("progress", force=True, note="hello from the notebook")\nprint("sent")'),
        _md("""## 5. Train (the demo first, then yours)
A complete tiny PyTorch training: run it to see the epochs arrive in KURAMA. To use your own model, keep the three
lines marked `# <- KURAMA` in your loop:
- each epoch: `kurama(epoch=e, epochs=N, loss=l, acc=a)` (any numbers you like: `val_loss=`, `lr=`...)
- `if kurama_should_stop(): break` (so "stop training" ends it cleanly after the epoch)
- at the end: `kurama("done")` and `kurama_send("model.pt")` (files up to 15 MB; bigger ones: run
  `kurama_drive_login()` once first, Colab only)"""),
        _code(PYTORCH_DEMO),
        _md("## 6. Keras or Hugging Face instead of a PyTorch loop\nUncomment the lines and use your own model and data."),
        _code(KERAS),
        _code(HF),
        _md("""## If something doesn't work
- **No "KURAMA is linked" line:** run cell 3 again; on Kaggle check **Internet → On**.
- **KURAMA shows nothing:** say "training status" on the laptop; the laptop needs internet (it reads the run's
  private channel). A laptop that slept catches up when it wakes.
- **Stop doesn't stop:** the loop must call `kurama_should_stop()` each epoch (Keras / HF callbacks do it).
  "stop training now" interrupts at once.
- **Session ended (Colab ~12 h / idle):** save checkpoints regularly (`torch.save(...)`, on Drive or
  `/kaggle/working`)."""),
    ]
    meta = {"kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"},
            "accelerator": "GPU"}
    if p == "colab":
        meta["colab"] = {"name": "KURAMA_colab.ipynb", "provenance": []}
    else:
        meta["kaggle"] = {"accelerator": "gpu", "isInternetEnabled": True}
    return json.dumps({"nbformat": 4, "nbformat_minor": 0, "metadata": meta, "cells": cells}, indent=1,
                      ensure_ascii=False)
