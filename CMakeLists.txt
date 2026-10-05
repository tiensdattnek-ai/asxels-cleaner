cmake_minimum_required(VERSION 3.24)
project(AsxelsCleaner VERSION 2.0.0 LANGUAGES CXX)

if(NOT WIN32)
  message(FATAL_ERROR "Asxels Cleaner is a native Windows application and must be built on Windows.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(AsxelsEngine SHARED
  src/engine.cpp
  src/engine.hpp
)
target_compile_definitions(AsxelsEngine PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(AsxelsEngine PRIVATE user32 gdi32 shell32 ole32 psapi dwmapi)

add_executable(AsxelsCleaner WIN32
  src/launcher.cpp
  src/app.rc
)
target_compile_definitions(AsxelsCleaner PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(AsxelsCleaner PRIVATE user32 shell32)

if(MSVC)
  target_compile_options(AsxelsEngine PRIVATE /W4 /permissive- /EHsc /utf-8)
  target_compile_options(AsxelsCleaner PRIVATE /W4 /permissive- /EHsc /utf-8)
endif()

# The launcher deliberately loads the engine from its own directory.  Keeping
# both runtime files together is therefore required when distributing the app.
set_target_properties(AsxelsCleaner AsxelsEngine PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

install(TARGETS AsxelsCleaner AsxelsEngine RUNTIME DESTINATION ".")
