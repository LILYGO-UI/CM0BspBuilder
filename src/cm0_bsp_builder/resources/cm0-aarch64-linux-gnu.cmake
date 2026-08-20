# CM0 AArch64 Linux cross-compilation toolchain.
#
# A generated BSP installs this file at usr/share/cm0-bsp/toolchain.cmake.
# CM0_SDK_ROOT may also be supplied explicitly or through the environment.

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(CM0_MULTIARCH "aarch64-linux-gnu" CACHE STRING
    "Target Debian multiarch tuple")

get_filename_component(_CM0_BUNDLED_SYSROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
if(DEFINED ENV{CM0_SDK_ROOT} AND NOT DEFINED CM0_SDK_ROOT)
    set(CM0_SDK_ROOT "$ENV{CM0_SDK_ROOT}")
endif()
if(NOT DEFINED CM0_SDK_ROOT)
    set(CM0_SDK_ROOT "${_CM0_BUNDLED_SYSROOT}")
endif()
set(CM0_SDK_ROOT "${CM0_SDK_ROOT}" CACHE PATH
    "Path to the CM0 BSP sysroot")

# Releases may contain either the sysroot directly or one enclosing directory.
if(NOT EXISTS "${CM0_SDK_ROOT}/usr/include" OR
   NOT EXISTS "${CM0_SDK_ROOT}/usr/lib")
    file(GLOB _CM0_EXTRACTED_DIRS LIST_DIRECTORIES true "${CM0_SDK_ROOT}/*")
    foreach(_CM0_EXTRACTED_DIR IN LISTS _CM0_EXTRACTED_DIRS)
        if(EXISTS "${_CM0_EXTRACTED_DIR}/usr/include" AND
           EXISTS "${_CM0_EXTRACTED_DIR}/usr/lib")
            set(CM0_SDK_ROOT "${_CM0_EXTRACTED_DIR}" CACHE PATH
                "Path to the CM0 BSP sysroot" FORCE)
            break()
        endif()
    endforeach()
endif()

list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES
    CM0_SDK_ROOT
    CM0_MULTIARCH)

if(NOT EXISTS "${CM0_SDK_ROOT}/usr/include" OR
   NOT EXISTS "${CM0_SDK_ROOT}/usr/lib")
    message(FATAL_ERROR
        "CM0 BSP sysroot is missing or incomplete: ${CM0_SDK_ROOT}\n"
        "Set CM0_SDK_ROOT to an extracted BSP sysroot.")
endif()

set(CMAKE_SYSROOT "${CM0_SDK_ROOT}" CACHE PATH
    "Sysroot used for CM0 cross builds" FORCE)
set(CMAKE_SYSROOT_COMPILE "${CMAKE_SYSROOT}" CACHE PATH
    "Compile sysroot used for CM0 cross builds" FORCE)
set(CMAKE_SYSROOT_LINK "${CMAKE_SYSROOT}" CACHE PATH
    "Link sysroot used for CM0 cross builds" FORCE)

# Homebrew's compiler does not add Debian's multiarch include automatically.
set(CMAKE_C_STANDARD_INCLUDE_DIRECTORIES
    "${CMAKE_SYSROOT}/usr/include/${CM0_MULTIARCH}" CACHE STRING
    "Target multiarch C system include directory" FORCE)
set(CMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES
    "${CMAKE_SYSROOT}/usr/include/${CM0_MULTIARCH}" CACHE STRING
    "Target multiarch C++ system include directory" FORCE)

find_program(_CM0_C_COMPILER NAMES aarch64-linux-gnu-gcc REQUIRED)
set(CMAKE_C_COMPILER "${_CM0_C_COMPILER}" CACHE FILEPATH
    "AArch64 Linux C compiler" FORCE)

find_program(_CM0_CXX_COMPILER NAMES aarch64-linux-gnu-g++)
if(_CM0_CXX_COMPILER)
    set(CMAKE_CXX_COMPILER "${_CM0_CXX_COMPILER}" CACHE FILEPATH
        "AArch64 Linux C++ compiler" FORCE)
endif()

set(CMAKE_LIBRARY_ARCHITECTURE "${CM0_MULTIARCH}")
set(CMAKE_FIND_ROOT_PATH "${CMAKE_SYSROOT}" CACHE STRING
    "Root paths for cross find_* calls" FORCE)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

list(PREPEND CMAKE_PREFIX_PATH
    "${CMAKE_SYSROOT}/usr"
    "${CMAKE_SYSROOT}/usr/lib/${CM0_MULTIARCH}/cmake"
    "${CMAKE_SYSROOT}/usr/local")

set(ENV{PKG_CONFIG_SYSROOT_DIR} "${CMAKE_SYSROOT}")
set(ENV{PKG_CONFIG_PATH} "")
set(ENV{PKG_CONFIG_LIBDIR}
    "${CMAKE_SYSROOT}/usr/local/lib/${CM0_MULTIARCH}/pkgconfig:${CMAKE_SYSROOT}/usr/local/lib/pkgconfig:${CMAKE_SYSROOT}/usr/lib/${CM0_MULTIARCH}/pkgconfig:${CMAKE_SYSROOT}/usr/lib/pkgconfig:${CMAKE_SYSROOT}/usr/share/pkgconfig:${CMAKE_SYSROOT}/lib/${CM0_MULTIARCH}/pkgconfig")

file(GLOB _CM0_GCC_RUNTIME_DIRS LIST_DIRECTORIES true
    "${CMAKE_SYSROOT}/usr/lib/gcc/${CM0_MULTIARCH}/*")
set(_CM0_MULTIARCH_LIB_DIR "${CMAKE_SYSROOT}/usr/lib/${CM0_MULTIARCH}")
if(_CM0_GCC_RUNTIME_DIRS)
    list(SORT _CM0_GCC_RUNTIME_DIRS COMPARE NATURAL ORDER DESCENDING)
    list(GET _CM0_GCC_RUNTIME_DIRS 0 CM0_GCC_RUNTIME_DIR)
    set(CM0_GCC_RUNTIME_DIR "${CM0_GCC_RUNTIME_DIR}" CACHE PATH
        "GCC runtime directory inside the CM0 sysroot")
    set(_CM0_SYSROOT_LINK_FLAGS
        "-B${_CM0_MULTIARCH_LIB_DIR}/ -B${CM0_GCC_RUNTIME_DIR}/ -Wl,-rpath-link,${_CM0_MULTIARCH_LIB_DIR} -L${_CM0_MULTIARCH_LIB_DIR}")
    string(APPEND CMAKE_EXE_LINKER_FLAGS_INIT " ${_CM0_SYSROOT_LINK_FLAGS}")
    string(APPEND CMAKE_SHARED_LINKER_FLAGS_INIT " ${_CM0_SYSROOT_LINK_FLAGS}")
endif()
