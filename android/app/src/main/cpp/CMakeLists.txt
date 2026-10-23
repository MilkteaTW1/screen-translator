# Whisper (whisper.cpp, MIT) for offline speech recognition with automatic language detection.
cmake_minimum_required(VERSION 3.22)
project(stwhisper C CXX)
set(CMAKE_CXX_STANDARD 17)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)  # built for every phone, not for this computer
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_LLAMAFILE OFF CACHE BOOL "" FORCE)

add_subdirectory(whisper.cpp)

add_library(stwhisper SHARED jni.cpp)
target_link_libraries(stwhisper PRIVATE whisper log)
if (NOT CMAKE_BUILD_TYPE STREQUAL "Debug")
    target_compile_options(stwhisper PRIVATE -O3)
endif ()
