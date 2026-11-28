#!/usr/bin/env bash
# Build pointer_states against the pinned llama.cpp release, into ./build.
#
#   native/pointer_states/build.sh
#
# Needs cmake, a C++17 compiler, glslc and the Vulkan headers (Ubuntu:
# build-essential cmake glslc libvulkan-dev). Release binaries are built on
# Ubuntu 22.04, so they run on glibc 2.35 and newer.
set -euo pipefail
LLAMA_CPP_TAG=b12819
here="$(cd "$(dirname "$0")" && pwd)"
out="$here/build"
src="$out/llama.cpp-$LLAMA_CPP_TAG"
mkdir -p "$out"
if [ ! -d "$src" ]; then
  curl -fsSL "https://github.com/ggml-org/llama.cpp/archive/refs/tags/$LLAMA_CPP_TAG.tar.gz" | tar -xz -C "$out"
fi
cmake -S "$here" -B "$out/cmake" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CPP_SRC="$src"
cmake --build "$out/cmake" --target pointer_states -j "$(nproc)"
cp "$out/cmake/pointer_states" "$out/pointer_states"
echo "$out/pointer_states (llama.cpp $LLAMA_CPP_TAG)"
