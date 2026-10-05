# Asxels Cleaner

> Trình dọn dẹp cache Windows có giao diện desktop hiện đại, **an toàn theo phạm vi** và có tính năng yêu cầu Windows trim bộ nhớ cho các tiến trình người dùng.

![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-4E8CFF?style=flat-square) ![Python](https://img.shields.io/badge/Python-3.10%2B-3DDBC0?style=flat-square) ![License](https://img.shields.io/badge/license-MIT-9CADCB?style=flat-square)

## Điểm nổi bật

- **Xem trước trước khi xóa:** quét dung lượng và số lượng mục trước khi hiện hộp xác nhận.
- **Không dọn kiểu “quét toàn ổ”:** chỉ dùng các đường dẫn cache/tạm đã định nghĩa; không đụng đến `Documents`, `Downloads`, `Desktop`, ảnh, dự án, Registry hay startup.
- **Chống xóa vượt phạm vi:** symbolic link/junction được xóa như một liên kết, không đi theo để xóa thư mục mà nó trỏ đến.
- **Tôn trọng tệp đang dùng:** không cố ép xóa file bị khóa/hệ thống bảo vệ; hiển thị số mục đã bỏ qua.
- **Tối ưu bộ nhớ có trách nhiệm:** gửi yêu cầu `EmptyWorkingSet` của Windows đến các tiến trình người dùng có quyền truy cập. Ứng dụng **không kết thúc process** và không tuyên bố tạo thêm RAM vật lý.
- **Chạy nền mượt:** việc quét, dọn và tối ưu bộ nhớ chạy ở luồng riêng để giao diện không bị treo.
- **Nhật ký cục bộ:** `%LOCALAPPDATA%\AsxelsCleaner\logs\activity.log`.
- **Không dependency runtime:** chương trình dùng Python standard library; chỉ cài PyInstaller khi đóng gói.

## Các khu vực dọn dẹp

| Hạng mục | Mặc định | Phạm vi |
|---|:---:|---|
| Tệp tạm người dùng | ✓ | `%TEMP%` / `%TMP%` của người dùng |
| Thumbnail & icon cache | ✓ | `%LOCALAPPDATA%\Microsoft\Windows\Explorer` |
| DirectX / GPU shader cache | ✓ | D3D/NVIDIA/AMD cache đã biết |
| Báo cáo lỗi Windows | ✓ | Windows Error Reporting trong tài khoản hiện tại |
| Internet cache hệ thống | ✓ | INetCache của tài khoản hiện tại |
| Cache trình duyệt |  | Chrome, Edge, Brave, Firefox; **không** đụng cookie/lịch sử/mật khẩu |
| Windows Temp |  | `C:\Windows\Temp`; có thể cần Administrator |
| Delivery Optimization |  | cache tải Windows Update; có thể cần Administrator |

> **Khuyến nghị:** đóng trình duyệt trước khi dọn browser cache. Tệp đang bị dùng vẫn sẽ được ứng dụng bỏ qua thay vì ép xóa.

## Chạy từ mã nguồn

Yêu cầu: Windows 10/11 và Python 3.10 trở lên.

```bat
python main.py
```

Tùy chọn dòng lệnh (phù hợp automation có kiểm soát):

```bat
:: Chỉ xem trước thư mục tạm của user (mặc định)
python main.py --scan

:: Chỉ dọn sau khi xác nhận rõ ràng bằng --yes
python main.py --clean --yes --categories user_temp,thumbs,shader
```

Các key hợp lệ: `user_temp`, `thumbs`, `shader`, `reports`, `internet`, `browser`, `windows_temp`, `delivery`.

## Build file `.exe` bằng PyInstaller

### Cách nhanh nhất

Nhấp đúp `BUILD_EXE.bat`, hoặc chạy:

```bat
BUILD_EXE.bat
```

Kết quả: `dist\AsxelsCleaner.exe`

### PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\BUILD_EXE.ps1
```

File exe dạng **one-file, windowed**. Windows SmartScreen có thể hiện cảnh báo với một exe mới chưa có chữ ký code; đó là hành vi bình thường. Hãy build từ mã nguồn tin cậy hoặc ký code trước khi phát hành thương mại.

## GitHub Actions

Workflow `.github/workflows/build-windows.yml` tự build EXE trên `windows-latest` khi:

- chạy thủ công tại tab **Actions**; hoặc
- push tag theo dạng `v*`, ví dụ `v1.0.0`.

EXE xuất hiện trong **Artifacts** của workflow. Workflow không có quyền ghi repo và không chứa token bí mật.

## Kiến trúc

```text
main.py                  GUI Tkinter + worker thread + Windows APIs
BUILD_EXE.bat            Build PyInstaller trên Windows
BUILD_EXE.ps1            Build PyInstaller bằng PowerShell
version_info.txt         Version metadata nhúng vào EXE
.github/workflows/       CI build Windows executable
```

## Lưu ý kỹ thuật về “giải phóng bộ nhớ”

Windows quản lý RAM bằng cache và working set. Nút **Tối ưu bộ nhớ** gọi `EmptyWorkingSet` cho các process người dùng phù hợp, sau đó Windows tự quyết định cách phân phối RAM. Điều này có thể tăng RAM khả dụng nhanh, nhưng một số app có thể cần nạp lại dữ liệu vào RAM sau đó. Đây không phải “RAM booster” thần kỳ và không tắt ứng dụng.

## Bảo mật khi đóng góp

- Không commit PAT, token, khóa API hay file `.env`.
- Không thêm lệnh xóa mù quáng như `rd /s /q C:\` hoặc lệnh PowerShell xóa đường dẫn do người dùng nhập.
- Nếu mở rộng danh sách vị trí dọn, hãy bổ sung test và mô tả rõ phạm vi trong README.

## License

MIT © 2026 Asxels
