# 0006: CPU only, no torch, lazy-load and unload heavy modules

**Status:** Accepted

**Context.** KURAMA runs all day next to VS Code and Chrome on 8 GB with no GPU.

**Decision.** No PyTorch or TensorFlow. Small ONNX models (fastembed, openwakeword) and APIs instead. Heavy
modules (cv2, mediapipe, playwright, fastembed) are imported inside the tool that needs them and released when
idle; only one camera feature runs at a time. Budget: idle core under 600 MB, hard cap 1.5 GB with daemons
(`make rss`, `process_resident_memory_bytes` in /metrics).

**Consequences.** + Starts fast, stays light. - The first use of a heavy tool is slower (it loads then).
