#include <windows.h>
#include <string>
#include <iterator>

using EngineRun = int (WINAPI*)(HINSTANCE, int);

namespace {
std::wstring EnginePath() {
    wchar_t modulePath[MAX_PATH]{};
    const DWORD size = GetModuleFileNameW(nullptr, modulePath, static_cast<DWORD>(std::size(modulePath)));
    if (size == 0 || size >= std::size(modulePath)) return L"AsxelsEngine.dll";
    std::wstring path(modulePath, size);
    const auto separator = path.find_last_of(L"\\/");
    return separator == std::wstring::npos ? L"AsxelsEngine.dll" : path.substr(0, separator + 1) + L"AsxelsEngine.dll";
}
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int showCommand) {
    // Absolute, adjacent-path loading prevents DLL search-order hijacking.
    const std::wstring path = EnginePath();
    HMODULE engine = LoadLibraryW(path.c_str());
    if (!engine) {
        MessageBoxW(nullptr,
            L"Không thể nạp AsxelsEngine.dll. Hãy giữ AsxelsCleaner.exe và AsxelsEngine.dll trong cùng một thư mục.",
            L"Asxels Cleaner", MB_OK | MB_ICONERROR);
        return 2;
    }

    const auto run = reinterpret_cast<EngineRun>(GetProcAddress(engine, "AsxelsEngineRun"));
    if (!run) {
        MessageBoxW(nullptr, L"Engine không có điểm khởi động hợp lệ.", L"Asxels Cleaner", MB_OK | MB_ICONERROR);
        FreeLibrary(engine);
        return 3;
    }

    const int exitCode = run(instance, showCommand);
    FreeLibrary(engine);
    return exitCode;
}
