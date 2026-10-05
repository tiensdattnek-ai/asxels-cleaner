#include "engine.hpp"

#include <windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#include <psapi.h>
#include <shlobj.h>
#include <shellapi.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <cwchar>
#include <cwctype>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

constexpr wchar_t kAppName[] = L"Asxels Cleaner";
constexpr wchar_t kWindowClass[] = L"AsxelsCleanerNativeWindow";
constexpr UINT kMsgStatus = WM_APP + 10;
constexpr UINT kMsgScanDone = WM_APP + 11;
constexpr UINT kMsgCleanDone = WM_APP + 12;
constexpr UINT kMsgMemoryDone = WM_APP + 13;

constexpr COLORREF kBg = RGB(10, 16, 32);
constexpr COLORREF kPanel = RGB(17, 26, 46);
constexpr COLORREF kPanelAlt = RGB(23, 35, 59);
constexpr COLORREF kBorder = RGB(38, 54, 83);
constexpr COLORREF kText = RGB(243, 247, 255);
constexpr COLORREF kMuted = RGB(156, 173, 203);
constexpr COLORREF kAccent = RGB(78, 140, 255);
constexpr COLORREF kAccentSoft = RGB(31, 56, 99);
constexpr COLORREF kTeal = RGB(61, 219, 192);
constexpr COLORREF kSuccess = RGB(109, 227, 168);
constexpr COLORREF kAmber = RGB(240, 163, 107);

struct Target {
    std::wstring path;
    bool clearContents{true};
};

struct ScanStats {
    std::uint64_t bytes{};
    std::uint64_t files{};
    std::uint64_t inaccessible{};
    std::uint64_t targets{};
};

struct CleanStats {
    std::uint64_t bytes{};
    std::uint64_t files{};
    std::uint64_t folders{};
    std::uint64_t skipped{};
    std::uint64_t errors{};
};

struct MemoryStats {
    std::uint64_t total{};
    std::uint64_t available{};
    DWORD load{};
    DWORD tried{};
    DWORD trimmed{};
};

struct ScanPayload {
    ScanStats stats;
    std::vector<Target> targets;
    bool continueToClean{};
};

struct CategorySpec {
    const wchar_t* title;
    const wchar_t* description;
    bool enabledByDefault;
};

constexpr std::array<CategorySpec, 8> kCategories{{
    {L"Tệp tạm người dùng", L"TEMP/TMP trong Local AppData", true},
    {L"Thumbnail & icon cache", L"Windows Explorer sẽ tự tạo lại", true},
    {L"DirectX / GPU shader cache", L"Cache đồ họa có thể tạo lại", true},
    {L"Báo cáo lỗi Windows", L"Windows Error Reporting (WER)", true},
    {L"Internet cache hệ thống", L"INetCache của tài khoản hiện tại", true},
    {L"Cache trình duyệt", L"Chrome, Edge, Brave, Firefox — nên đóng trước", false},
    {L"Windows Temp", L"Có thể cần quyền Administrator", false},
    {L"Delivery Optimization", L"Cache tải Windows Update; có thể cần quyền cao", false},
}};

std::wstring Join(const std::wstring& base, const std::wstring& tail) {
    if (base.empty()) return tail;
    if (tail.empty()) return base;
    if (base.back() == L'\\' || base.back() == L'/') return base + tail;
    return base + L"\\" + tail;
}

std::wstring Lower(std::wstring text) {
    std::transform(text.begin(), text.end(), text.begin(), [](wchar_t c) {
        return static_cast<wchar_t>(std::towlower(c));
    });
    return text;
}

std::wstring FullPath(const std::wstring& path) {
    const DWORD length = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
    if (!length) return path;
    std::wstring result(length, L'\0');
    const DWORD written = GetFullPathNameW(path.c_str(), length, result.data(), nullptr);
    if (!written || written >= length) return path;
    result.resize(written);
    while (result.size() > 3 && (result.back() == L'\\' || result.back() == L'/')) result.pop_back();
    return result;
}

bool IsUnder(const std::wstring& child, const std::wstring& parent) {
    const std::wstring candidate = Lower(FullPath(child));
    const std::wstring root = Lower(FullPath(parent));
    if (candidate.empty() || root.empty()) return false;
    return candidate == root || (candidate.size() > root.size() && candidate.compare(0, root.size(), root) == 0 &&
                                 (candidate[root.size()] == L'\\' || candidate[root.size()] == L'/'));
}

bool IsDot(const wchar_t* name) {
    return std::wcscmp(name, L".") == 0 || std::wcscmp(name, L"..") == 0;
}

DWORD Attributes(const std::wstring& path) {
    return GetFileAttributesW(path.c_str());
}

bool IsDirectory(const std::wstring& path, bool rejectReparse = true) {
    const DWORD attrs = Attributes(path);
    return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY) &&
           (!rejectReparse || !(attrs & FILE_ATTRIBUTE_REPARSE_POINT));
}

std::wstring KnownFolder(REFKNOWNFOLDERID id) {
    PWSTR raw = nullptr;
    const HRESULT result = SHGetKnownFolderPath(id, KF_FLAG_DEFAULT, nullptr, &raw);
    if (FAILED(result) || !raw) return L"";
    std::wstring path(raw);
    CoTaskMemFree(raw);
    return path;
}

std::wstring LocalAppData() {
    return KnownFolder(FOLDERID_LocalAppData);
}

std::wstring RoamingAppData() {
    return KnownFolder(FOLDERID_RoamingAppData);
}

std::wstring WindowsDirectory() {
    std::array<wchar_t, 32768> buffer{};
    const UINT size = GetWindowsDirectoryW(buffer.data(), static_cast<UINT>(buffer.size()));
    if (!size || size >= buffer.size()) return L"C:\\Windows";
    return std::wstring(buffer.data(), size);
}

std::wstring TempDirectory(const std::wstring& localAppData) {
    const DWORD needed = GetTempPathW(0, nullptr);
    if (needed) {
        std::wstring candidate(needed + 1, L'\0');
        const DWORD written = GetTempPathW(static_cast<DWORD>(candidate.size()), candidate.data());
        if (written && written < candidate.size()) {
            candidate.resize(written);
            if (IsUnder(candidate, localAppData)) return candidate;
        }
    }
    // Never expand scope to an arbitrary externally-configured TEMP directory.
    return Join(localAppData, L"Temp");
}

void AddContentTarget(std::vector<Target>& targets, const std::wstring& path) {
    if (IsDirectory(path, true)) targets.push_back({FullPath(path), true});
}

void AddFileTarget(std::vector<Target>& targets, const std::wstring& path) {
    const DWORD attrs = Attributes(path);
    if (attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY)) targets.push_back({FullPath(path), false});
}

template <typename Callback>
bool ForEachEntry(const std::wstring& folder, Callback callback) {
    WIN32_FIND_DATAW data{};
    const std::wstring query = Join(folder, L"*");
    HANDLE find = FindFirstFileW(query.c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return false;
    do {
        if (!IsDot(data.cFileName)) callback(data, Join(folder, data.cFileName));
    } while (FindNextFileW(find, &data));
    FindClose(find);
    return true;
}

void AddPatternFiles(std::vector<Target>& targets, const std::wstring& folder, const std::wstring& pattern) {
    if (!IsDirectory(folder, true)) return;
    WIN32_FIND_DATAW data{};
    const std::wstring query = Join(folder, pattern);
    HANDLE find = FindFirstFileW(query.c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return;
    do {
        if (!IsDot(data.cFileName) && !(data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
            AddFileTarget(targets, Join(folder, data.cFileName));
        }
    } while (FindNextFileW(find, &data));
    FindClose(find);
}

std::vector<std::wstring> ChildDirectories(const std::wstring& folder) {
    std::vector<std::wstring> children;
    if (!IsDirectory(folder, true)) return children;
    ForEachEntry(folder, [&](const WIN32_FIND_DATAW& data, const std::wstring& path) {
        if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && !(data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) {
            children.push_back(path);
        }
    });
    return children;
}

void AddBrowserRoot(std::vector<Target>& targets, const std::wstring& userDataRoot) {
    for (const auto& profile : ChildDirectories(userDataRoot)) {
        AddContentTarget(targets, Join(profile, L"Cache"));
        AddContentTarget(targets, Join(profile, L"Code Cache"));
        AddContentTarget(targets, Join(profile, L"GPUCache"));
        AddContentTarget(targets, Join(Join(profile, L"Service Worker"), L"CacheStorage"));
    }
}

void AddFirefoxCaches(std::vector<Target>& targets, const std::wstring& profileRoot) {
    for (const auto& profile : ChildDirectories(profileRoot)) {
        AddContentTarget(targets, Join(profile, L"cache2"));
    }
}

void Deduplicate(std::vector<Target>& targets) {
    std::set<std::pair<std::wstring, bool>> seen;
    std::vector<Target> unique;
    unique.reserve(targets.size());
    for (auto& target : targets) {
        target.path = FullPath(target.path);
        const auto key = std::make_pair(Lower(target.path), target.clearContents);
        if (!target.path.empty() && seen.insert(key).second) unique.push_back(std::move(target));
    }
    targets = std::move(unique);
}

std::vector<Target> ResolveTargets(const std::array<bool, kCategories.size()>& selected) {
    std::vector<Target> targets;
    const std::wstring local = LocalAppData();
    const std::wstring roaming = RoamingAppData();
    const std::wstring windows = WindowsDirectory();

    if (selected[0] && !local.empty()) AddContentTarget(targets, TempDirectory(local));
    if (selected[1] && !local.empty()) {
        const std::wstring explorer = Join(Join(Join(local, L"Microsoft"), L"Windows"), L"Explorer");
        AddPatternFiles(targets, explorer, L"thumbcache*.db");
        AddPatternFiles(targets, explorer, L"iconcache*.db");
    }
    if (selected[2] && !local.empty()) {
        AddContentTarget(targets, Join(local, L"D3DSCache"));
        AddContentTarget(targets, Join(Join(local, L"NVIDIA"), L"DXCache"));
        AddContentTarget(targets, Join(Join(local, L"NVIDIA"), L"GLCache"));
        AddContentTarget(targets, Join(Join(local, L"AMD"), L"DxCache"));
        AddContentTarget(targets, Join(Join(local, L"AMD"), L"GLCache"));
    }
    if (selected[3] && !local.empty()) {
        const std::wstring wer = Join(Join(Join(Join(local, L"Microsoft"), L"Windows"), L"WER"), L"ReportArchive");
        AddContentTarget(targets, wer);
        AddContentTarget(targets, Join(Join(Join(Join(local, L"Microsoft"), L"Windows"), L"WER"), L"ReportQueue"));
        AddContentTarget(targets, Join(Join(Join(Join(local, L"Microsoft"), L"Windows"), L"WER"), L"Temp"));
    }
    if (selected[4] && !local.empty()) {
        AddContentTarget(targets, Join(Join(Join(local, L"Microsoft"), L"Windows"), L"INetCache"));
        AddContentTarget(targets, Join(TempDirectory(local), L"INetCache"));
    }
    if (selected[5] && !local.empty()) {
        AddBrowserRoot(targets, Join(Join(Join(local, L"Google"), L"Chrome"), L"User Data"));
        AddBrowserRoot(targets, Join(Join(Join(local, L"Microsoft"), L"Edge"), L"User Data"));
        AddBrowserRoot(targets, Join(Join(Join(local, L"BraveSoftware"), L"Brave-Browser"), L"User Data"));
        if (!roaming.empty()) AddFirefoxCaches(targets, Join(Join(roaming, L"Mozilla"), L"Firefox\\Profiles"));
    }
    if (selected[6]) AddContentTarget(targets, Join(windows, L"Temp"));
    if (selected[7]) AddContentTarget(targets, Join(Join(Join(windows, L"SoftwareDistribution"), L"DeliveryOptimization"), L"Cache"));

    Deduplicate(targets);
    return targets;
}

std::uint64_t FindSize(const WIN32_FIND_DATAW& data) {
    return (static_cast<std::uint64_t>(data.nFileSizeHigh) << 32u) | data.nFileSizeLow;
}

std::uint64_t FileSize(const std::wstring& path) {
    WIN32_FILE_ATTRIBUTE_DATA data{};
    if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data)) return 0;
    return (static_cast<std::uint64_t>(data.nFileSizeHigh) << 32u) | data.nFileSizeLow;
}

void ScanEntry(const std::wstring& path, ScanStats& stats, const std::atomic_bool& cancelled, unsigned depth = 0) {
    if (cancelled || depth > 128) {
        if (depth > 128) ++stats.inaccessible;
        return;
    }
    const DWORD attrs = Attributes(path);
    if (attrs == INVALID_FILE_ATTRIBUTES) {
        ++stats.inaccessible;
        return;
    }
    if (attrs & FILE_ATTRIBUTE_REPARSE_POINT) {
        ++stats.files; // Link itself is an item; its target is never traversed.
        return;
    }
    if (!(attrs & FILE_ATTRIBUTE_DIRECTORY)) {
        stats.bytes += FileSize(path);
        ++stats.files;
        return;
    }
    const bool opened = ForEachEntry(path, [&](const WIN32_FIND_DATAW&, const std::wstring& child) {
        ScanEntry(child, stats, cancelled, depth + 1);
    });
    if (!opened) ++stats.inaccessible;
}

ScanStats ScanTargets(const std::vector<Target>& targets, HWND window, const std::atomic_bool& cancelled) {
    ScanStats stats{};
    stats.targets = targets.size();
    for (const auto& target : targets) {
        if (cancelled) break;
        auto status = std::make_unique<std::wstring>(L"Đang kiểm tra: " + target.path);
        PostMessageW(window, kMsgStatus, 0, reinterpret_cast<LPARAM>(status.release()));
        if (target.clearContents) {
            const bool opened = ForEachEntry(target.path, [&](const WIN32_FIND_DATAW&, const std::wstring& child) {
                ScanEntry(child, stats, cancelled);
            });
            if (!opened) ++stats.inaccessible;
        } else {
            ScanEntry(target.path, stats, cancelled);
        }
    }
    return stats;
}

bool DeleteFileWithRetry(const std::wstring& path, DWORD attrs) {
    if (DeleteFileW(path.c_str())) return true;
    if (attrs & FILE_ATTRIBUTE_READONLY) {
        SetFileAttributesW(path.c_str(), attrs & ~FILE_ATTRIBUTE_READONLY);
        return DeleteFileW(path.c_str()) != FALSE;
    }
    return false;
}

bool RemoveDirectoryWithRetry(const std::wstring& path, DWORD attrs) {
    if (RemoveDirectoryW(path.c_str())) return true;
    if (attrs & FILE_ATTRIBUTE_READONLY) {
        SetFileAttributesW(path.c_str(), attrs & ~FILE_ATTRIBUTE_READONLY);
        return RemoveDirectoryW(path.c_str()) != FALSE;
    }
    return false;
}

void MarkDeletionFailure(CleanStats& stats) {
    const DWORD error = GetLastError();
    if (error == ERROR_ACCESS_DENIED || error == ERROR_SHARING_VIOLATION || error == ERROR_LOCK_VIOLATION ||
        error == ERROR_DIR_NOT_EMPTY || error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) {
        ++stats.skipped;
    } else {
        ++stats.errors;
    }
}

void CleanEntry(const std::wstring& path, CleanStats& stats, const std::atomic_bool& cancelled, unsigned depth = 0) {
    if (cancelled || depth > 128) {
        if (depth > 128) ++stats.skipped;
        return;
    }
    const DWORD attrs = Attributes(path);
    if (attrs == INVALID_FILE_ATTRIBUTES) return;

    // A reparse point is removed as a link. Its destination is never opened or walked.
    if ((attrs & FILE_ATTRIBUTE_REPARSE_POINT) || !(attrs & FILE_ATTRIBUTE_DIRECTORY)) {
        const std::uint64_t size = (attrs & FILE_ATTRIBUTE_DIRECTORY) ? 0 : FileSize(path);
        const bool isDirectoryLink = (attrs & FILE_ATTRIBUTE_DIRECTORY) != 0;
        const bool removed = isDirectoryLink ? RemoveDirectoryWithRetry(path, attrs) : DeleteFileWithRetry(path, attrs);
        if (removed) {
            stats.bytes += size;
            ++stats.files;
        } else {
            MarkDeletionFailure(stats);
        }
        return;
    }

    const bool opened = ForEachEntry(path, [&](const WIN32_FIND_DATAW&, const std::wstring& child) {
        CleanEntry(child, stats, cancelled, depth + 1);
    });
    if (!opened) {
        ++stats.skipped;
        return;
    }
    if (RemoveDirectoryWithRetry(path, attrs)) {
        ++stats.folders;
    } else {
        MarkDeletionFailure(stats);
    }
}

CleanStats CleanTargets(const std::vector<Target>& targets, HWND window, const std::atomic_bool& cancelled) {
    CleanStats stats{};
    for (const auto& target : targets) {
        if (cancelled) break;
        auto status = std::make_unique<std::wstring>(L"Đang dọn an toàn: " + target.path);
        PostMessageW(window, kMsgStatus, 0, reinterpret_cast<LPARAM>(status.release()));
        if (target.clearContents) {
            const bool opened = ForEachEntry(target.path, [&](const WIN32_FIND_DATAW&, const std::wstring& child) {
                CleanEntry(child, stats, cancelled);
            });
            if (!opened) ++stats.skipped;
        } else {
            CleanEntry(target.path, stats, cancelled);
        }
    }
    return stats;
}

MemoryStats ReadMemory() {
    MEMORYSTATUSEX state{};
    state.dwLength = sizeof(state);
    if (!GlobalMemoryStatusEx(&state)) return {};
    return {state.ullTotalPhys, state.ullAvailPhys, state.dwMemoryLoad, 0, 0};
}

std::wstring ProcessName(HANDLE process) {
    std::array<wchar_t, 32768> buffer{};
    DWORD size = static_cast<DWORD>(buffer.size());
    if (!QueryFullProcessImageNameW(process, 0, buffer.data(), &size) || !size) return L"";
    std::wstring full(buffer.data(), size);
    const auto slash = full.find_last_of(L"\\/");
    return Lower(slash == std::wstring::npos ? full : full.substr(slash + 1));
}

MemoryStats TrimWorkingSets(HWND window, const std::atomic_bool& cancelled) {
    MemoryStats result = ReadMemory();
    std::array<DWORD, 8192> pids{};
    DWORD bytesNeeded{};
    if (!EnumProcesses(pids.data(), static_cast<DWORD>(sizeof(pids)), &bytesNeeded)) return result;

    const std::set<std::wstring> excluded{
        L"system", L"registry", L"smss.exe", L"csrss.exe", L"wininit.exe", L"winlogon.exe", L"services.exe",
        L"lsass.exe", L"fontdrvhost.exe", L"dwm.exe", L"memory compression"
    };
    const DWORD count = std::min<DWORD>(static_cast<DWORD>(pids.size()), bytesNeeded / sizeof(DWORD));
    const DWORD ownPid = GetCurrentProcessId();
    for (DWORD index = 0; index < count && !cancelled; ++index) {
        const DWORD pid = pids[index];
        if (pid <= 4 || pid == ownPid) continue;
        HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA, FALSE, pid);
        if (!process) continue;
        const std::wstring name = ProcessName(process);
        if (!name.empty() && !excluded.contains(name)) {
            ++result.tried;
            if (EmptyWorkingSet(process)) ++result.trimmed;
        }
        CloseHandle(process);
    }
    result = [&] {
        MemoryStats after = ReadMemory();
        after.tried = result.tried;
        after.trimmed = result.trimmed;
        return after;
    }();
    auto status = std::make_unique<std::wstring>(L"Windows đã xử lý " + std::to_wstring(result.trimmed) + L" / " +
                                                 std::to_wstring(result.tried) + L" tiến trình phù hợp");
    PostMessageW(window, kMsgStatus, 0, reinterpret_cast<LPARAM>(status.release()));
    return result;
}

std::wstring FormatBytes(std::uint64_t bytes) {
    constexpr std::array<const wchar_t*, 5> units{L"B", L"KB", L"MB", L"GB", L"TB"};
    double amount = static_cast<double>(bytes);
    size_t unit = 0;
    while (amount >= 1024.0 && unit + 1 < units.size()) {
        amount /= 1024.0;
        ++unit;
    }
    std::wostringstream output;
    if (unit == 0) output << static_cast<std::uint64_t>(amount) << L" " << units[unit];
    else output << std::fixed << std::setprecision(1) << amount << L" " << units[unit];
    return output.str();
}

std::wstring FormatNumber(std::uint64_t number) {
    std::wstring raw = std::to_wstring(number);
    for (int position = static_cast<int>(raw.size()) - 3; position > 0; position -= 3) raw.insert(position, L".");
    return raw;
}

void AppendLog(const std::wstring& line) {
    const std::wstring local = LocalAppData();
    if (local.empty()) return;
    const std::filesystem::path folder = std::filesystem::path(local) / L"AsxelsCleaner" / L"logs";
    std::error_code error;
    std::filesystem::create_directories(folder, error);
    if (error) return;
    SYSTEMTIME now{};
    GetLocalTime(&now);
    std::wostringstream record;
    record << L"[" << std::setfill(L'0') << std::setw(4) << now.wYear << L"-" << std::setw(2) << now.wMonth << L"-"
           << std::setw(2) << now.wDay << L" " << std::setw(2) << now.wHour << L":" << std::setw(2) << now.wMinute
           << L":" << std::setw(2) << now.wSecond << L"] " << line << L"\r\n";
    std::wofstream file(folder / L"activity.log", std::ios::app);
    if (file) file << record.str();
}

void OpenLogFolder() {
    const std::wstring local = LocalAppData();
    if (local.empty()) return;
    const std::wstring folder = Join(Join(local, L"AsxelsCleaner"), L"logs");
    std::error_code error;
    std::filesystem::create_directories(folder, error);
    ShellExecuteW(nullptr, L"open", folder.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
}

HFONT CreateUiFont(int height, int weight = FW_NORMAL) {
    return CreateFontW(-height, 0, 0, 0, weight, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                       CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
}

void FillRectColor(HDC dc, const RECT& rect, COLORREF color) {
    HBRUSH brush = CreateSolidBrush(color);
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
}

void RoundCard(HDC dc, const RECT& rect, COLORREF fill, COLORREF border, int radius = 12) {
    HBRUSH brush = CreateSolidBrush(fill);
    HPEN pen = CreatePen(PS_SOLID, 1, border);
    HGDIOBJ oldBrush = SelectObject(dc, brush);
    HGDIOBJ oldPen = SelectObject(dc, pen);
    RoundRect(dc, rect.left, rect.top, rect.right, rect.bottom, radius, radius);
    SelectObject(dc, oldBrush);
    SelectObject(dc, oldPen);
    DeleteObject(brush);
    DeleteObject(pen);
}

void Text(HDC dc, const std::wstring& value, const RECT& rect, HFONT font, COLORREF color, UINT flags) {
    const HGDIOBJ old = SelectObject(dc, font);
    SetTextColor(dc, color);
    SetBkMode(dc, TRANSPARENT);
    DrawTextW(dc, value.c_str(), static_cast<int>(value.size()), const_cast<RECT*>(&rect), flags);
    SelectObject(dc, old);
}

bool Inside(const RECT& rect, int x, int y) {
    return x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom;
}

class Application {
public:
    explicit Application(HINSTANCE instance) : instance_(instance) {
        for (size_t i = 0; i < kCategories.size(); ++i) selected_[i] = kCategories[i].enabledByDefault;
        titleFont_ = CreateUiFont(24, FW_SEMIBOLD);
        headingFont_ = CreateUiFont(11, FW_SEMIBOLD);
        bodyFont_ = CreateUiFont(10);
        smallFont_ = CreateUiFont(8, FW_NORMAL);
        metricFont_ = CreateUiFont(20, FW_SEMIBOLD);
    }

    ~Application() {
        cancelled_ = true;
        if (worker_.joinable()) worker_.join();
        DeleteObject(titleFont_);
        DeleteObject(headingFont_);
        DeleteObject(bodyFont_);
        DeleteObject(smallFont_);
        DeleteObject(metricFont_);
    }

    int Run(int showCommand) {
        WNDCLASSEXW wc{};
        wc.cbSize = sizeof(wc);
        wc.hInstance = instance_;
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        wc.hbrBackground = CreateSolidBrush(kBg);
        wc.lpszClassName = kWindowClass;
        wc.lpfnWndProc = WindowProc;
        wc.style = CS_HREDRAW | CS_VREDRAW;
        if (!RegisterClassExW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return 1;

        hwnd_ = CreateWindowExW(0, kWindowClass, L"Asxels Cleaner  •  Native Engine v2.0", WS_OVERLAPPED | WS_CAPTION |
                                    WS_SYSMENU | WS_MINIMIZEBOX,
                                CW_USEDEFAULT, CW_USEDEFAULT, 1120, 820, nullptr, nullptr, instance_, this);
        if (!hwnd_) return 2;
        EnableDarkTitleBar();
        ShowWindow(hwnd_, showCommand);
        UpdateWindow(hwnd_);

        MSG message{};
        while (GetMessageW(&message, nullptr, 0, 0) > 0) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        return static_cast<int>(message.wParam);
    }

private:
    HINSTANCE instance_{};
    HWND hwnd_{};
    std::array<bool, kCategories.size()> selected_{};
    std::array<RECT, kCategories.size()> categoryRects_{};
    RECT previewRect_{};
    RECT cleanRect_{};
    RECT memoryRect_{};
    RECT logsRect_{};
    std::wstring status_{L"Sẵn sàng. Bấm “XEM TRƯỚC” để xem chính xác trước khi dọn."};
    ScanStats lastScan_{};
    MemoryStats memory_{};
    bool hasScan_{};
    std::atomic_bool busy_{false};
    std::atomic_bool cancelled_{false};
    std::thread worker_;
    HFONT titleFont_{};
    HFONT headingFont_{};
    HFONT bodyFont_{};
    HFONT smallFont_{};
    HFONT metricFont_{};

    static LRESULT CALLBACK WindowProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam) {
        Application* app = nullptr;
        if (message == WM_NCCREATE) {
            const auto create = reinterpret_cast<CREATESTRUCTW*>(lParam);
            app = static_cast<Application*>(create->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
            app->hwnd_ = hwnd;
        } else {
            app = reinterpret_cast<Application*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        }
        if (app) return app->HandleMessage(message, wParam, lParam);
        return DefWindowProcW(hwnd, message, wParam, lParam);
    }

    void EnableDarkTitleBar() {
        const BOOL enabled = TRUE;
        constexpr DWORD kDwmUseImmersiveDarkMode = 20;
        DwmSetWindowAttribute(hwnd_, kDwmUseImmersiveDarkMode, &enabled, sizeof(enabled));
        const COLORREF caption = kBg;
        const COLORREF text = kText;
        constexpr DWORD kDwmCaptionColor = 35;
        constexpr DWORD kDwmTextColor = 36;
        DwmSetWindowAttribute(hwnd_, kDwmCaptionColor, &caption, sizeof(caption));
        DwmSetWindowAttribute(hwnd_, kDwmTextColor, &text, sizeof(text));
    }

    void Layout(int width, int height) {
        const int margin = 26;
        const int leftWidth = std::min(660, std::max(570, width - 410));
        const int rightX = margin + leftWidth + 16;
        const int rightWidth = std::max(310, width - rightX - margin);
        const int categoryTop = 187;
        constexpr int rowHeight = 53;
        for (size_t i = 0; i < categoryRects_.size(); ++i) {
            categoryRects_[i] = {margin, categoryTop + static_cast<int>(i) * rowHeight,
                                 margin + leftWidth, categoryTop + static_cast<int>(i + 1) * rowHeight - 5};
        }
        previewRect_ = {margin, categoryTop + static_cast<int>(kCategories.size()) * rowHeight + 8,
                        margin + 170, categoryTop + static_cast<int>(kCategories.size()) * rowHeight + 52};
        cleanRect_ = {margin + 182, previewRect_.top, margin + 440, previewRect_.bottom};
        memoryRect_ = {rightX + 18, 340, rightX + rightWidth - 18, 384};
        logsRect_ = {rightX + rightWidth - 92, 656, rightX + rightWidth - 18, 690};
        (void)height;
    }

    void DrawMetric(HDC dc, const RECT& rect, const std::wstring& title, const std::wstring& value, COLORREF valueColor) {
        RoundCard(dc, rect, kPanel, kBorder);
        RECT titleRect{rect.left + 16, rect.top + 13, rect.right - 12, rect.top + 30};
        RECT valueRect{rect.left + 16, rect.top + 34, rect.right - 12, rect.bottom - 8};
        Text(dc, title, titleRect, smallFont_, kMuted, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
        Text(dc, value, valueRect, metricFont_, valueColor, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
    }

    void DrawCheck(HDC dc, const RECT& bounds, bool checked) {
        RECT box{bounds.left + 15, bounds.top + 16, bounds.left + 32, bounds.top + 33};
        RoundCard(dc, box, checked ? kAccent : kPanel, checked ? kAccent : kMuted, 4);
        if (checked) {
            HPEN pen = CreatePen(PS_SOLID, 2, RGB(255, 255, 255));
            HGDIOBJ old = SelectObject(dc, pen);
            MoveToEx(dc, box.left + 4, box.top + 9, nullptr);
            LineTo(dc, box.left + 7, box.bottom - 5);
            LineTo(dc, box.right - 3, box.top + 4);
            SelectObject(dc, old);
            DeleteObject(pen);
        }
    }

    void DrawButton(HDC dc, const RECT& rect, const std::wstring& title, bool accent, bool enabled) {
        const COLORREF fill = !enabled ? RGB(38, 49, 73) : (accent ? kAccent : kPanelAlt);
        const COLORREF border = !enabled ? RGB(38, 49, 73) : (accent ? kAccent : kBorder);
        RoundCard(dc, rect, fill, border, 9);
        Text(dc, title, rect, headingFont_, enabled ? kText : kMuted, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }

    void Paint(HDC dc) {
        RECT client{};
        GetClientRect(hwnd_, &client);
        FillRectColor(dc, client, kBg);
        Layout(client.right - client.left, client.bottom - client.top);

        RECT brand{26, 19, 350, 35};
        Text(dc, L"ASXELS  /  NATIVE C++ ENGINE", brand, smallFont_, kAccent, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        RECT title{26, 38, 720, 72};
        Text(dc, L"Dọn sạch thông minh. Có kiểm soát.", title, titleFont_, kText, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        RECT subtitle{26, 72, 750, 91};
        Text(dc, L"Cache và tệp tạm đã biết — không quét toàn ổ, không đụng dữ liệu cá nhân.", subtitle, bodyFont_, kMuted,
             DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        RECT nativeBadge{client.right - 180, 28, client.right - 27, 56};
        RoundCard(dc, nativeBadge, RGB(24, 55, 92), RGB(31, 72, 121), 8);
        Text(dc, L"NATIVE / WINDOWS", nativeBadge, smallFont_, RGB(218, 235, 255), DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        const int metricTop = 108;
        const int metricWidth = (client.right - 52 - 16) / 3;
        DrawMetric(dc, {26, metricTop, 26 + metricWidth, metricTop + 67}, L"SẴN SÀNG DỌN",
                   hasScan_ ? FormatBytes(lastScan_.bytes) : L"Chưa kiểm tra", kTeal);
        DrawMetric(dc, {26 + metricWidth + 8, metricTop, 26 + 2 * metricWidth + 8, metricTop + 67}, L"RAM KHẢ DỤNG",
                   memory_.total ? FormatBytes(memory_.available) : L"Đang tải…", kTeal);
        DrawMetric(dc, {26 + 2 * (metricWidth + 8), metricTop, client.right - 26, metricTop + 67}, L"MỤC ĐÃ KIỂM TRA",
                   hasScan_ ? FormatNumber(lastScan_.files) : L"Chưa có dữ liệu", kText);

        const int leftWidth = categoryRects_[0].right - categoryRects_[0].left;
        RECT leftPanel{26, 174, 26 + leftWidth, previewRect_.bottom + 15};
        RoundCard(dc, leftPanel, kPanel, kBorder);
        Text(dc, L"KHU VỰC DỌN DẸP", {44, 180, 350, 204}, headingFont_, kText, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        Text(dc, L"BẤM ĐỂ CHỌN", {leftPanel.right - 150, 180, leftPanel.right - 17, 204}, smallFont_, kAccent,
             DT_RIGHT | DT_VCENTER | DT_SINGLELINE);

        for (size_t i = 0; i < kCategories.size(); ++i) {
            const RECT row = categoryRects_[i];
            RoundCard(dc, row, selected_[i] ? kAccentSoft : kPanel, selected_[i] ? RGB(55, 91, 153) : kBorder, 8);
            DrawCheck(dc, row, selected_[i]);
            RECT rowTitle{row.left + 43, row.top + 7, row.right - 12, row.top + 25};
            RECT rowSubtitle{row.left + 43, row.top + 25, row.right - 12, row.bottom - 3};
            Text(dc, kCategories[i].title, rowTitle, headingFont_, kText, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
            Text(dc, kCategories[i].description, rowSubtitle, smallFont_, kMuted, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
        }
        DrawButton(dc, previewRect_, L"↻  XEM TRƯỚC", false, !busy_);
        DrawButton(dc, cleanRect_, L"✦  DỌN DẸP AN TOÀN", true, !busy_);

        const int rightX = leftPanel.right + 16;
        RECT rightPanel{rightX, 174, client.right - 26, 707};
        RoundCard(dc, rightPanel, kPanel, kBorder);
        Text(dc, L"BỘ NHỚ TỨC THÌ", {rightX + 18, 185, rightPanel.right - 18, 210}, headingFont_, kText,
             DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        Text(dc, L"Gửi yêu cầu Windows trim working set cho ứng dụng phù hợp. Không đóng tiến trình, không tạo thêm RAM vật lý.",
             {rightX + 18, 213, rightPanel.right - 18, 270}, bodyFont_, kMuted, DT_LEFT | DT_WORDBREAK);
        const std::wstring memoryLine = memory_.total
            ? FormatBytes(memory_.available) + L" khả dụng / " + FormatBytes(memory_.total) + L" tổng  •  đang dùng " +
                  std::to_wstring(memory_.load) + L"%"
            : L"Đang tải thông tin bộ nhớ…";
        Text(dc, memoryLine, {rightX + 18, 282, rightPanel.right - 18, 306}, smallFont_, kText, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        RECT bar{rightX + 18, 315, rightPanel.right - 18, 322};
        RoundCard(dc, bar, RGB(15, 25, 48), RGB(15, 25, 48), 3);
        if (memory_.load) {
            RECT used = bar;
            used.right = used.left + ((bar.right - bar.left) * static_cast<int>(memory_.load)) / 100;
            RoundCard(dc, used, kTeal, kTeal, 3);
        }
        DrawButton(dc, memoryRect_, L"⚡  TỐI ƯU BỘ NHỚ", false, !busy_);

        HPEN divider = CreatePen(PS_SOLID, 1, kBorder);
        HGDIOBJ oldPen = SelectObject(dc, divider);
        MoveToEx(dc, rightX + 18, 420, nullptr); LineTo(dc, rightPanel.right - 18, 420);
        SelectObject(dc, oldPen); DeleteObject(divider);
        Text(dc, L"MINH BẠCH & AN TOÀN", {rightX + 18, 433, rightPanel.right - 18, 455}, headingFont_, kText,
             DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        const std::array<std::wstring, 4> notes{{
            L"✓  Không đụng Documents, Downloads, Desktop hoặc Registry.",
            L"✓  Không đi theo symbolic link hoặc junction khi xóa.",
            L"✓  Tệp đang dùng / cần quyền cao sẽ được bỏ qua.",
            L"✓  Luôn quét trước, rồi mới yêu cầu xác nhận xóa."
        }};
        for (size_t i = 0; i < notes.size(); ++i) {
            Text(dc, notes[i], {rightX + 18, 468 + static_cast<int>(i) * 36, rightPanel.right - 18,
                                 498 + static_cast<int>(i) * 36}, bodyFont_, i == 0 ? kSuccess : kMuted,
                 DT_LEFT | DT_WORDBREAK);
        }
        Text(dc, L"NHẬT KÝ HOẠT ĐỘNG CỤC BỘ", {rightX + 18, 659, rightPanel.right - 100, 688}, smallFont_, kMuted,
             DT_LEFT | DT_VCENTER | DT_SINGLELINE);
        DrawButton(dc, logsRect_, L"MỞ", false, true);

        HPEN footPen = CreatePen(PS_SOLID, 1, kBorder);
        oldPen = SelectObject(dc, footPen);
        MoveToEx(dc, 26, client.bottom - 42, nullptr); LineTo(dc, client.right - 26, client.bottom - 42);
        SelectObject(dc, oldPen); DeleteObject(footPen);
        Text(dc, busy_ ? L"ĐANG XỬ LÝ  •  " + status_ : status_, {26, client.bottom - 33, client.right - 185, client.bottom - 7},
             bodyFont_, busy_ ? kTeal : kMuted, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
        Text(dc, L"v2.0  •  100% native C++", {client.right - 185, client.bottom - 33, client.right - 26, client.bottom - 7},
             smallFont_, kMuted, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
    }

    std::array<bool, kCategories.size()> SelectedSnapshot() const { return selected_; }

    void JoinFinishedWorker() {
        if (worker_.joinable() && !busy_) worker_.join();
    }

    void StartScan(bool continueToClean) {
        if (busy_) return;
        bool any = false;
        for (bool selected : selected_) any = any || selected;
        if (!any) {
            MessageBoxW(hwnd_, L"Hãy chọn ít nhất một khu vực để kiểm tra.", kAppName, MB_OK | MB_ICONINFORMATION);
            return;
        }
        JoinFinishedWorker();
        cancelled_ = false;
        busy_ = true;
        status_ = continueToClean ? L"Đang kiểm tra lần cuối trước khi dọn…" : L"Đang kiểm tra các khu vực đã chọn…";
        InvalidateRect(hwnd_, nullptr, FALSE);
        const auto selection = SelectedSnapshot();
        worker_ = std::thread([this, selection, continueToClean] {
            auto targets = ResolveTargets(selection);
            const ScanStats stats = ScanTargets(targets, hwnd_, cancelled_);
            auto payload = std::make_unique<ScanPayload>(ScanPayload{stats, std::move(targets), continueToClean});
            PostMessageW(hwnd_, kMsgScanDone, 0, reinterpret_cast<LPARAM>(payload.release()));
        });
    }

    void StartClean(std::vector<Target> targets) {
        if (busy_) return;
        JoinFinishedWorker();
        cancelled_ = false;
        busy_ = true;
        status_ = L"Đang dọn các tệp cache/tạm đã được xác nhận…";
        InvalidateRect(hwnd_, nullptr, FALSE);
        worker_ = std::thread([this, targets = std::move(targets)]() mutable {
            const CleanStats stats = CleanTargets(targets, hwnd_, cancelled_);
            auto payload = std::make_unique<CleanStats>(stats);
            PostMessageW(hwnd_, kMsgCleanDone, 0, reinterpret_cast<LPARAM>(payload.release()));
        });
    }

    void StartMemoryTrim() {
        if (busy_) return;
        JoinFinishedWorker();
        cancelled_ = false;
        busy_ = true;
        status_ = L"Đang gửi yêu cầu trim working set đến Windows…";
        InvalidateRect(hwnd_, nullptr, FALSE);
        worker_ = std::thread([this] {
            const MemoryStats stats = TrimWorkingSets(hwnd_, cancelled_);
            auto payload = std::make_unique<MemoryStats>(stats);
            PostMessageW(hwnd_, kMsgMemoryDone, 0, reinterpret_cast<LPARAM>(payload.release()));
        });
    }

    void HandleScanDone(std::unique_ptr<ScanPayload> payload) {
        busy_ = false;
        lastScan_ = payload->stats;
        hasScan_ = true;
        status_ = L"Tìm thấy " + FormatBytes(lastScan_.bytes) + L" trong " + FormatNumber(lastScan_.files) + L" mục";
        if (lastScan_.inaccessible) status_ += L"  •  " + FormatNumber(lastScan_.inaccessible) + L" mục không đọc được";
        InvalidateRect(hwnd_, nullptr, FALSE);

        if (!payload->continueToClean) return;
        if (payload->targets.empty() || !lastScan_.files) {
            MessageBoxW(hwnd_, L"Không tìm thấy tệp cache/tạm phù hợp trong các khu vực đã chọn.", kAppName,
                        MB_OK | MB_ICONINFORMATION);
            return;
        }
        const std::wstring confirmation = L"Xóa an toàn tối đa " + FormatBytes(lastScan_.bytes) + L" từ " +
            FormatNumber(lastScan_.files) + L" mục cache/tạm?\n\n"
            L"• Chỉ các vị trí cache/tạm cố định của ứng dụng.\n"
            L"• Tệp đang dùng hoặc hệ thống bảo vệ sẽ được bỏ qua.\n"
            L"• Không thể hoàn tác thao tác này.";
        if (MessageBoxW(hwnd_, confirmation.c_str(), L"Xác nhận dọn dẹp", MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) == IDYES) {
            StartClean(std::move(payload->targets));
        } else {
            status_ = L"Đã hủy. Không có tệp nào bị thay đổi.";
            InvalidateRect(hwnd_, nullptr, FALSE);
        }
    }

    void HandleCleanDone(std::unique_ptr<CleanStats> result) {
        busy_ = false;
        status_ = L"Đã dọn " + FormatBytes(result->bytes) + L" từ " + FormatNumber(result->files) + L" mục";
        if (result->skipped) status_ += L"  •  bỏ qua " + FormatNumber(result->skipped) + L" mục";
        if (result->errors) status_ += L"  •  lỗi " + FormatNumber(result->errors);
        AppendLog(status_);
        InvalidateRect(hwnd_, nullptr, FALSE);
        std::wstring message = status_ + L"\n\nCác tệp bị khóa hoặc được Windows bảo vệ không bị ép xóa.";
        MessageBoxW(hwnd_, message.c_str(), kAppName, MB_OK | MB_ICONINFORMATION);
    }

    void HandleMemoryDone(std::unique_ptr<MemoryStats> result) {
        busy_ = false;
        memory_ = *result;
        status_ = L"Windows đã trim working set cho " + std::to_wstring(memory_.trimmed) + L" / " +
                  std::to_wstring(memory_.tried) + L" tiến trình phù hợp.";
        AppendLog(status_);
        InvalidateRect(hwnd_, nullptr, FALSE);
        const std::wstring message = status_ + L"\n\nKhông có tiến trình nào bị đóng. Một số ứng dụng có thể nạp lại dữ liệu vào RAM khi cần.";
        MessageBoxW(hwnd_, message.c_str(), kAppName, MB_OK | MB_ICONINFORMATION);
    }

    LRESULT HandleMessage(UINT message, WPARAM wParam, LPARAM lParam) {
        switch (message) {
        case WM_CREATE:
            memory_ = ReadMemory();
            SetTimer(hwnd_, 1, 5000, nullptr);
            return 0;
        case WM_TIMER:
            if (!busy_) {
                memory_ = ReadMemory();
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT paint{};
            HDC dc = BeginPaint(hwnd_, &paint);
            Paint(dc);
            EndPaint(hwnd_, &paint);
            return 0;
        }
        case WM_LBUTTONUP: {
            if (busy_) return 0;
            const int x = GET_X_LPARAM(lParam);
            const int y = GET_Y_LPARAM(lParam);
            for (size_t i = 0; i < categoryRects_.size(); ++i) {
                if (Inside(categoryRects_[i], x, y)) {
                    selected_[i] = !selected_[i];
                    hasScan_ = false;
                    status_ = L"Lựa chọn đã thay đổi. Bấm “XEM TRƯỚC” để tính lại chính xác.";
                    InvalidateRect(hwnd_, nullptr, FALSE);
                    return 0;
                }
            }
            if (Inside(previewRect_, x, y)) StartScan(false);
            else if (Inside(cleanRect_, x, y)) StartScan(true);
            else if (Inside(memoryRect_, x, y)) StartMemoryTrim();
            else if (Inside(logsRect_, x, y)) OpenLogFolder();
            return 0;
        }
        case WM_KEYUP:
            if (wParam == VK_F5) StartScan(false);
            else if (wParam == VK_RETURN) StartScan(true);
            else if (wParam == VK_ESCAPE && !busy_) SendMessageW(hwnd_, WM_CLOSE, 0, 0);
            return 0;
        case kMsgStatus: {
            std::unique_ptr<std::wstring> text(reinterpret_cast<std::wstring*>(lParam));
            if (text) {
                status_ = *text;
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            return 0;
        }
        case kMsgScanDone:
            HandleScanDone(std::unique_ptr<ScanPayload>(reinterpret_cast<ScanPayload*>(lParam)));
            return 0;
        case kMsgCleanDone:
            HandleCleanDone(std::unique_ptr<CleanStats>(reinterpret_cast<CleanStats*>(lParam)));
            return 0;
        case kMsgMemoryDone:
            HandleMemoryDone(std::unique_ptr<MemoryStats>(reinterpret_cast<MemoryStats*>(lParam)));
            return 0;
        case WM_CLOSE:
            if (busy_) {
                MessageBoxW(hwnd_, L"Tác vụ đang chạy. Hãy chờ tác vụ hoàn tất để bảo đảm kết quả minh bạch.", kAppName,
                            MB_OK | MB_ICONINFORMATION);
                return 0;
            }
            DestroyWindow(hwnd_);
            return 0;
        case WM_DESTROY:
            KillTimer(hwnd_, 1);
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(hwnd_, message, wParam, lParam);
        }
    }
};

} // namespace

extern "C" __declspec(dllexport) int WINAPI AsxelsEngineRun(HINSTANCE hostInstance, int showCommand) {
    // Per-monitor V2 avoids a blurred UI on high-DPI Windows displays. The call
    // is harmless if a process compatibility setting has already chosen a mode.
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    Application app(hostInstance);
    return app.Run(showCommand);
}
