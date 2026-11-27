cmake_minimum_required(VERSION 3.21)
project(pointer_states CXX)

# One static binary: llama.cpp's sources at the tag build.sh pins, its
# Vulkan backend for any vendor's GPU, and nothing to install beside it.
set(LLAMA_CPP_SRC "" CACHE PATH "llama.cpp source tree")
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(GGML_VULKAN ON CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_MTMD ON CACHE BOOL "" FORCE)
add_subdirectory(${LLAMA_CPP_SRC} llama.cpp EXCLUDE_FROM_ALL)

add_executable(pointer_states pointer_states.cpp)
target_include_directories(pointer_states PRIVATE ${LLAMA_CPP_SRC}/vendor)
target_link_libraries(pointer_states PRIVATE llama mtmd)
target_compile_features(pointer_states PRIVATE cxx_std_17)
target_link_options(pointer_states PRIVATE -static-libstdc++ -static-libgcc)
