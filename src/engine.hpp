#pragma once

#include <windows.h>

// Exported ABI intentionally stays tiny: the launcher EXE owns only startup
// and dynamic loading; all UI, cleanup policy and Windows logic run in this
// native C++ engine DLL.
extern "C" __declspec(dllexport) int WINAPI AsxelsEngineRun(HINSTANCE hostInstance, int showCommand);
