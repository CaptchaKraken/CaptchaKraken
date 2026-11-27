# pointer_states

The CaptchaKraken pointer models on llama.cpp, for GPUs the vLLM build has no
kernels for (NVIDIA compute capability below 7.5) and, through Vulkan, any GPU
with a Vulkan driver. Stock `libllama` and `libmtmd` run the language model and
the vision encoder over the board's prompt, and this program returns the final
hidden state of every token. The pointer heads read those states in Python
(`captchakraken.pointer.llamacpp_engine`).

`captchakraken fetch` downloads the release binary and checks its sha256, so
users never build it.

## Building

The release build, in Docker, so the binary runs on glibc 2.35 and newer:

```bash
docker build --output native/pointer_states/dist native/pointer_states
```

On the machine itself (cmake, a C++17 compiler, glslc and the Vulkan headers;
on Ubuntu 24.04 `build-essential cmake glslc libvulkan-dev`):

```bash
native/pointer_states/build.sh
```

Both download the llama.cpp release pinned in `build.sh` and link it in
statically. The result needs only `libvulkan.so.1` and glibc at run time.

## Publishing a new build

1. Change `LLAMA_CPP_TAG` in `build.sh` and `POINTER_STATES_RELEASE` in
   `python/src/captchakraken/selfhost.py` together (a test checks they match).
2. Build with Docker, upload `dist/pointer_states` as the asset
   `pointer_states-linux-x86_64` of the GitHub release
   `pointer-states-<tag>`.
3. Put its `sha256sum` in `POINTER_STATES_SHA256`.
4. Score the GGUF models through it against the full-precision reference
   before it ships: llama.cpp's vision path has cost accuracy before.

## Protocol

```text
pointer_states MODEL.gguf MMPROJ.gguf [--threads N] [--ctx N] [--batch N] [--device PCI | --cpu]
pointer_states --list-devices
```

It prints `{"ready": true, "n_embd": D, "marker": "<__media__>"}`, then
answers one JSON line per request line:

```text
{"prompt": "...<__media__>...", "media": [{"rgb": PATH, "w": W, "h": H, "video": false}], "out": PATH}
{"ok": true, "n_embd": D, "ms": T, "chunks": [{"text": [ids]}, {"media": N, "grid": [W, H]}, ...]}
```

Each `rgb` file is raw RGB bytes, `W*H*3`. Video frames are marked `"video":
true`; two adjacent frames are one temporal patch, as Qwen merges them. `out`
receives float32 `[n_tokens, D]` in prompt order, and `chunks` is the token
layout behind it, which the caller checks against the model's own processor.
