# The release build of pointer_states: Ubuntu 22.04, so the binary runs on glibc
# 2.35 and newer, with the Vulkan SDK packages llama.cpp's own release uses.
#
#   docker build --output native/pointer_states/dist native/pointer_states
FROM ubuntu:22.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends wget gnupg ca-certificates curl \
 && wget -qO - https://packages.lunarg.com/lunarg-signing-key-pub.asc | apt-key add - \
 && wget -qO /etc/apt/sources.list.d/lunarg-vulkan-jammy.list https://packages.lunarg.com/vulkan/lunarg-vulkan-jammy.list \
 && apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake shaderc vulkan-headers libvulkan-dev spirv-headers \
 && rm -rf /var/lib/apt/lists/*
COPY CMakeLists.txt build.sh pointer_states.cpp /src/
RUN /src/build.sh

FROM scratch
COPY --from=build /src/build/pointer_states /
