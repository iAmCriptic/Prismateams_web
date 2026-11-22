#include "app.h"
#include "settings.h"
#include "auth_manager.h"
#include "webdav_manager.h"
#include "file_router.h"
#include "../resources/resource.h"

#include <dwmapi.h>
#include <windowsx.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <wincrypt.h>
#include <gdiplus.h>
#include <thread>
#include <vector>

#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "uxtheme.lib")
#pragma comment(lib, "gdiplus.lib")
#pragma comment(lib, "crypt32.lib")

namespace Prismateams {

const wchar_t* const MAIN_WINDOW_CLASS = L"Prismateams_MainWindow_Class";
const int TITLEBAR_HEIGHT = 36;

App& App::Instance() {
    static App instance;
    return instance;
}

App::~App() {
    if (m_hBrNavbar) DeleteObject(m_hBrNavbar);
    if (m_hFontNav) DeleteObject(m_hFontNav);
    if (m_hPortalIcon) DestroyIcon(m_hPortalIcon);
}

void App::CheckSystemTheme() {
    DWORD lightTheme = 0;
    DWORD size = sizeof(lightTheme);
    HKEY hKey;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize", 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        RegQueryValueExW(hKey, L"AppsUseLightTheme", nullptr, nullptr, reinterpret_cast<LPBYTE>(&lightTheme), &size);
        RegCloseKey(hKey);
    }
    SetDarkMode(lightTheme == 0);
}

void App::SetDarkMode(bool isDark) {
    m_isDarkMode = isDark;

    if (m_hBrNavbar) DeleteObject(m_hBrNavbar);

    if (m_isDarkMode) {
        m_hBrNavbar = CreateSolidBrush(RGB(26, 26, 26));      // Styleguide Dark --portal-bg #1a1a1a
    } else {
        m_hBrNavbar = CreateSolidBrush(RGB(240, 242, 245));   // Styleguide Light --portal-bg #f0f2f5
    }

    if (!m_hFontNav) {
        m_hFontNav = CreateFontW(-12, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    }

    if (m_hWndMain) {
        BOOL val = m_isDarkMode ? TRUE : FALSE;
        DwmSetWindowAttribute(m_hWndMain, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &val, sizeof(val));
        InvalidateRect(m_hWndMain, nullptr, TRUE);
    }
}

void App::ApplyThemeMode(const std::wstring& themeMode) {
    if (themeMode == L"light") {
        SetDarkMode(false);
    } else if (themeMode == L"dark" || themeMode == L"oled") {
        SetDarkMode(true);
    } else {
        CheckSystemTheme();
    }
}

int App::Run(HINSTANCE hInstance, const std::wstring& cmdLine, int nCmdShow) {
    m_hInstance = hInstance;

    // Load local settings
    SettingsManager::Instance().Load();
    AuthManager::Instance().SetServerUrl(SettingsManager::Instance().Get().serverUrl);

    ApplyThemeMode(SettingsManager::Instance().Get().themeMode);

    // Parse command line
    if (!cmdLine.empty()) {
        if (cmdLine.find(L"--minimized") != std::string::npos) {
            m_isStartingMinimized = true;
        } else {
            std::wstring arg = cmdLine;
            if (arg.front() == L'"' && arg.back() == L'"' && arg.length() >= 2) {
                arg = arg.substr(1, arg.length() - 2);
            }
            m_initialFileArgument = arg;
        }
    }

    if (!RegisterAppClass()) {
        return 1;
    }

    int show = m_isStartingMinimized ? SW_HIDE : nCmdShow;
    if (!CreateMainWindow(show)) {
        return 1;
    }

    // System Tray
    m_trayIcon = std::make_unique<TrayIcon>(m_hWndMain, m_hInstance);
    m_trayIcon->Create();

    // Initialize WebView2 (serves both the Styleguide Login Screen and the Portal)
    m_webViewController = std::make_unique<WebViewController>(m_hWndMain);
    m_webViewController->Initialize([this](bool success) {
        if (!success) {
            MessageBoxW(
                m_hWndMain,
                L"Microsoft Edge WebView2 konnte nicht geladen werden.",
                L"Prismateams",
                MB_ICONERROR | MB_OK
            );
            return;
        }

        // Show Login Screen immediately so UI never blocks, then verify stored session asynchronously
        m_webViewController->SetVisible(true);
        m_webViewController->ShowLoginScreen();

        HWND hMain = m_hWndMain;
        std::thread([hMain]() {
            bool ok = AuthManager::Instance().VerifyStoredSession();
            if (IsWindow(hMain)) {
                PostMessageW(hMain, WM_APP_SESSION_VERIFIED, ok ? 1 : 0, 0);
            }
        }).detach();
    });

    // Message Loop
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    return static_cast<int>(msg.wParam);
}

bool App::RegisterAppClass() {
    WNDCLASSEXW wcex = { 0 };
    wcex.cbSize = sizeof(WNDCLASSEXW);
    wcex.style = CS_HREDRAW | CS_VREDRAW;
    wcex.lpfnWndProc = App::WndProc;
    wcex.hInstance = m_hInstance;
    wcex.hIcon = LoadIconW(m_hInstance, MAKEINTRESOURCEW(IDI_PRISMATEAMS));
    wcex.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wcex.hbrBackground = m_hBrNavbar;
    wcex.lpszClassName = MAIN_WINDOW_CLASS;
    wcex.hIconSm = LoadIconW(m_hInstance, MAKEINTRESOURCEW(IDI_SMALL));

    return (RegisterClassExW(&wcex) != 0);
}

bool App::CreateMainWindow(int nCmdShow) {
    m_hWndMain = CreateWindowExW(
        WS_EX_APPWINDOW,
        MAIN_WINDOW_CLASS,
        L"Prismateams Desktop",
        WS_POPUP | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_CLIPCHILDREN,
        CW_USEDEFAULT, CW_USEDEFAULT, 1360, 860,
        nullptr, nullptr, m_hInstance, this
    );

    if (!m_hWndMain) return false;

    BOOL val = m_isDarkMode ? TRUE : FALSE;
    DwmSetWindowAttribute(m_hWndMain, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &val, sizeof(val));

    // Enable Windows 11 drop shadow and rounded corners on frameless window
    MARGINS margins = { 1, 1, 1, 1 };
    DwmExtendFrameIntoClientArea(m_hWndMain, &margins);
    DragAcceptFiles(m_hWndMain, TRUE);

    if (nCmdShow != SW_HIDE) {
        ShowWindow(m_hWndMain, nCmdShow);
        UpdateWindow(m_hWndMain);
    }

    return true;
}

void App::LayoutViews(int width, int height) {
    if (m_webViewController) {
        m_webViewController->Resize(width, height);
    }
}

void App::OpenNativeSettings() {
    if (m_hWndMain) {
        ShowWindow(m_hWndMain, SW_RESTORE);
        SetForegroundWindow(m_hWndMain);
    }
    if (m_webViewController && m_isAuthenticated) {
        m_webViewController->PostJsonMessage(L"{\"type\":\"open_settings_modal\"}");
    }
}

void App::ShowTrayNotification(const std::wstring& title, const std::wstring& message) {
    if (m_trayIcon) {
        m_trayIcon->ShowNotification(title, message);
    }
}

void App::UpdatePortalBranding(const std::wstring& portalName, const std::wstring& logoDataUri) {
    bool changed = false;
    auto& s = SettingsManager::Instance().Get();

    if (!portalName.empty()) {
        if (s.portalName != portalName) {
            s.portalName = portalName;
            changed = true;
        }
        if (m_hWndMain) {
            SetWindowTextW(m_hWndMain, portalName.c_str());
        }
        if (m_trayIcon) {
            m_trayIcon->UpdateTooltip(portalName);
        }
    }

    if (!logoDataUri.empty()) {
        SettingsManager::Instance().SavePortalLogoFromDataUri(logoDataUri);

        size_t comma = logoDataUri.find(L",");
        if (comma != std::wstring::npos) {
            std::wstring b64 = logoDataUri.substr(comma + 1);
            DWORD binLen = 0;
            if (CryptStringToBinaryW(b64.c_str(), static_cast<DWORD>(b64.size()), CRYPT_STRING_BASE64, nullptr, &binLen, nullptr, nullptr) && binLen > 0) {
                std::vector<BYTE> pngBytes(binLen);
                if (CryptStringToBinaryW(b64.c_str(), static_cast<DWORD>(b64.size()), CRYPT_STRING_BASE64, pngBytes.data(), &binLen, nullptr, nullptr)) {
                    ULONG_PTR gpToken = 0;
                    Gdiplus::GdiplusStartupInput gpIn;
                    if (Gdiplus::GdiplusStartup(&gpToken, &gpIn, nullptr) == Gdiplus::Ok) {
                        IStream* pStream = SHCreateMemStream(pngBytes.data(), binLen);
                        if (pStream) {
                            Gdiplus::Bitmap* bmp = Gdiplus::Bitmap::FromStream(pStream);
                            if (bmp && bmp->GetLastStatus() == Gdiplus::Ok) {
                                HICON hNewIcon = nullptr;
                                if (bmp->GetHICON(&hNewIcon) == Gdiplus::Ok && hNewIcon) {
                                    if (m_hPortalIcon) DestroyIcon(m_hPortalIcon);
                                    m_hPortalIcon = hNewIcon;
                                    if (m_hWndMain) {
                                        SendMessageW(m_hWndMain, WM_SETICON, ICON_BIG, reinterpret_cast<LPARAM>(m_hPortalIcon));
                                        SendMessageW(m_hWndMain, WM_SETICON, ICON_SMALL, reinterpret_cast<LPARAM>(m_hPortalIcon));
                                    }
                                }
                                delete bmp;
                            }
                            pStream->Release();
                        }
                        Gdiplus::GdiplusShutdown(gpToken);
                    }
                }
            }
        }
    }

    if (changed) {
        SettingsManager::Instance().Save();
    }
}

void App::ResetPortalBranding() {
    if (m_hWndMain) {
        SetWindowTextW(m_hWndMain, L"Prismateams Desktop");
        HICON hBig = LoadIconW(m_hInstance, MAKEINTRESOURCEW(IDI_PRISMATEAMS));
        HICON hSmall = LoadIconW(m_hInstance, MAKEINTRESOURCEW(IDI_SMALL));
        SendMessageW(m_hWndMain, WM_SETICON, ICON_BIG, reinterpret_cast<LPARAM>(hBig));
        SendMessageW(m_hWndMain, WM_SETICON, ICON_SMALL, reinterpret_cast<LPARAM>(hSmall));
    }
    if (m_hPortalIcon) {
        DestroyIcon(m_hPortalIcon);
        m_hPortalIcon = nullptr;
    }
    if (m_trayIcon) {
        m_trayIcon->UpdateTooltip(L"Prismateams");
    }
}

void App::OnLoginSuccess() {
    m_isAuthenticated = true;

    // Auto mount WebDAV drive asynchronously if enabled in settings
    if (SettingsManager::Instance().Get().autoMountDrive) {
        HWND hMain = m_hWndMain;
        wchar_t preferred = SettingsManager::Instance().Get().driveLetter;
        std::wstring serverUrl = AuthManager::Instance().GetServerUrl();
        std::thread([hMain, preferred, serverUrl]() {
            auto creds = AuthManager::Instance().FetchWebDavCredentials();
            if (creds.success) {
                wchar_t assigned = L'P';
                std::wstring err;
                WebDavManager::Instance().MountDrive(
                    serverUrl,
                    creds.username,
                    creds.password,
                    preferred,
                    assigned,
                    err
                );
                if (IsWindow(hMain)) {
                    PostMessageW(hMain, WM_APP_WEBDAV_SYNC, static_cast<WPARAM>(assigned), 0);
                }
            }
        }).detach();
    }

    // Show WebView2 & Navigate
    if (m_webViewController) {
        m_webViewController->SetVisible(true);

        const std::wstring& token = AuthManager::Instance().GetAuthToken();
        const std::wstring& cookie = AuthManager::Instance().GetSessionCookie();

        if (!token.empty()) {
            // Direct SSO login via token -> clear any stale cookies so /desktop-login sets one clean host-only session cookie
            m_webViewController->ClearAllCookies();
        } else if (!cookie.empty()) {
            m_webViewController->SyncSessionCookie(AuthManager::Instance().GetServerUrl(), cookie);
        }

        if (!m_initialFileArgument.empty()) {
            HandleFileOpen(m_initialFileArgument);
            m_initialFileArgument.clear();
        } else if (!token.empty()) {
            // Direct SSO login via token -> lands directly on dashboard, 100% authenticated!
            std::wstring ssoUrl = AuthManager::Instance().GetServerUrl() + L"/desktop-login?token=" + token + L"&next=/dashboard";
            NavigateTo(ssoUrl);
        } else {
            NavigateTo(AuthManager::Instance().GetServerUrl() + L"/dashboard");
        }
        m_webViewController->PushStateSync();
    }

    RECT rc;
    GetClientRect(m_hWndMain, &rc);
    LayoutViews(rc.right - rc.left, rc.bottom - rc.top);
    InvalidateRect(m_hWndMain, nullptr, TRUE);
}

void App::OnLogout() {
    m_isAuthenticated = false;

    AuthManager::Instance().Logout();
    ResetPortalBranding();

    // Clear session cookies and show Styleguide Login Screen in WebView2
    if (m_webViewController) {
        m_webViewController->ClearAllCookies();
        m_webViewController->SetVisible(true);
        m_webViewController->ShowLoginScreen();
    }

    RECT rc;
    GetClientRect(m_hWndMain, &rc);
    LayoutViews(rc.right - rc.left, rc.bottom - rc.top);
    InvalidateRect(m_hWndMain, nullptr, TRUE);
}

void App::NavigateTo(const std::wstring& url) {
    if (m_webViewController && m_isAuthenticated) {
        m_webViewController->Navigate(url);
    }
}

void App::HandleFileOpen(const std::wstring& filePath) {
    if (!m_isAuthenticated) {
        m_initialFileArgument = filePath;
        return;
    }

    FileRouteResult route = FileRouter::Instance().RouteLocalPath(filePath);
    if (route.success && !route.navigationUrl.empty()) {
        NavigateTo(route.navigationUrl);
        if (m_trayIcon) {
            std::wstring notice = L"\xD6ffne " + (route.filename.empty() ? L"Datei" : route.filename) + L" in Prismateams...";
            m_trayIcon->ShowNotification(L"Live Bearbeiten", notice);
        }
    }
}

LRESULT CALLBACK App::WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    App& app = App::Instance();

    switch (message) {
    case WM_GETMINMAXINFO: {
        MINMAXINFO* pMMI = reinterpret_cast<MINMAXINFO*>(lParam);
        HMONITOR hMon = MonitorFromWindow(hWnd, MONITOR_DEFAULTTONEAREST);
        if (hMon) {
            MONITORINFO mi = { sizeof(MONITORINFO) };
            if (GetMonitorInfoW(hMon, &mi)) {
                // rcWork excludes the taskbar, so maximized window never covers the taskbar
                pMMI->ptMaxPosition.x = mi.rcWork.left - mi.rcMonitor.left;
                pMMI->ptMaxPosition.y = mi.rcWork.top - mi.rcMonitor.top;
                pMMI->ptMaxSize.x = mi.rcWork.right - mi.rcWork.left;
                pMMI->ptMaxSize.y = mi.rcWork.bottom - mi.rcWork.top;
            }
        }
        return 0;
    }

    case WM_NCCALCSIZE: {
        if (wParam == TRUE) {
            // WM_GETMINMAXINFO already constrains maximized size to mi.rcWork;
            // do not inset rgrc[0] here, otherwise an 8px gap appears around the client area.
            return 0;
        }
        break;
    }

    case WM_NCHITTEST: {
        POINT pt = { GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam) };
        ScreenToClient(hWnd, &pt);

        RECT rcClient;
        GetClientRect(hWnd, &rcClient);
        int winW = rcClient.right;
        int winH = rcClient.bottom;

        if (!IsZoomed(hWnd)) {
            int resizeBorder = 6;
            if (pt.y < resizeBorder) {
                if (pt.x < resizeBorder) return HTTOPLEFT;
                if (pt.x > winW - resizeBorder) return HTTOPRIGHT;
                return HTTOP;
            }
            if (pt.y > winH - resizeBorder) {
                if (pt.x < resizeBorder) return HTBOTTOMLEFT;
                if (pt.x > winW - resizeBorder) return HTBOTTOMRIGHT;
                return HTBOTTOM;
            }
            if (pt.x < resizeBorder) return HTLEFT;
            if (pt.x > winW - resizeBorder) return HTRIGHT;
        }

        // Top area: treat as caption for dragging (except window control buttons on top right)
        if (pt.y <= 52 && pt.x < winW - 140) {
            return HTCAPTION;
        }

        return HTCLIENT;
    }

    case WM_SIZE: {
        int width = LOWORD(lParam);
        int height = HIWORD(lParam);
        // Disable Windows 11 rounded corners while maximized so edges sit 100% flush
        DWORD cornerPref = IsZoomed(hWnd) ? 1 /* DWMWCP_DONOTROUND */ : 2 /* DWMWCP_ROUND */;
        DwmSetWindowAttribute(hWnd, 33 /* DWMWA_WINDOW_CORNER_PREFERENCE */, &cornerPref, sizeof(cornerPref));
        app.LayoutViews(width, height);
        InvalidateRect(hWnd, nullptr, FALSE);
        return 0;
    }

    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);
        RECT rc;
        GetClientRect(hWnd, &rc);
        FillRect(hdc, &rc, app.m_hBrNavbar);
        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        switch (wmId) {
        case ID_NAV_SETTINGS:
        case ID_TRAY_SETTINGS:
            app.OpenNativeSettings();
            break;
        case IDM_POPUP_BACK:
            if (app.m_webViewController) app.m_webViewController->GoBack();
            break;
        case IDM_POPUP_FORWARD:
            if (app.m_webViewController) app.m_webViewController->GoForward();
            break;
        case IDM_POPUP_RELOAD:
            if (app.m_webViewController) app.m_webViewController->Reload();
            break;
        case IDM_POPUP_HOME:
            app.NavigateTo(SettingsManager::Instance().Get().serverUrl + L"/dashboard");
            break;
        case ID_TRAY_OPEN_EXPLORER:
        case IDM_POPUP_EXPLORER:
            WebDavManager::Instance().OpenInExplorer();
            break;
        case ID_TRAY_MOUNT: {
            auto creds = AuthManager::Instance().FetchWebDavCredentials();
            if (creds.success) {
                wchar_t assigned = L'P';
                std::wstring err;
                WebDavManager::Instance().MountDrive(
                    AuthManager::Instance().GetServerUrl(),
                    creds.username,
                    creds.password,
                    SettingsManager::Instance().Get().driveLetter,
                    assigned,
                    err
                );
                if (app.m_trayIcon && WebDavManager::Instance().IsMounted()) {
                    std::wstring msg = L"Netzlaufwerk " + std::wstring(1, assigned) + L": erfolgreich eingebunden.";
                    app.m_trayIcon->ShowNotification(L"Prismateams", msg);
                }
            }
            break;
        }
        case ID_TRAY_UNMOUNT:
            WebDavManager::Instance().UnmountCurrentDrive(true);
            if (app.m_trayIcon) {
                app.m_trayIcon->ShowNotification(L"Prismateams", L"Netzlaufwerk getrennt.");
            }
            break;
        case ID_TRAY_OPEN:
            ShowWindow(hWnd, SW_RESTORE);
            SetForegroundWindow(hWnd);
            break;
        case ID_TRAY_LOGOUT:
            app.OnLogout();
            break;
        case ID_TRAY_EXIT:
            DestroyWindow(hWnd);
            break;
        }
        return 0;
    }

    case WM_APP_SESSION_VERIFIED: {
        if (wParam == 1 && !app.m_isAuthenticated) {
            app.OnLoginSuccess();
        }
        return 0;
    }

    case WM_APP_POST_JSON: {
        std::wstring* pJson = reinterpret_cast<std::wstring*>(lParam);
        if (pJson) {
            if (app.m_webViewController) {
                app.m_webViewController->PostJsonMessage(*pJson);
            }
            delete pJson;
        }
        return 0;
    }

    case WM_APP_LOGIN_SUCCESS: {
        app.OnLoginSuccess();
        return 0;
    }

    case WM_APP_WEBDAV_SYNC: {
        if (app.m_webViewController) {
            app.m_webViewController->PushStateSync();
        }
        if (app.m_trayIcon && WebDavManager::Instance().IsMounted()) {
            wchar_t letter = static_cast<wchar_t>(wParam);
            std::wstring msg = L"Netzlaufwerk " + std::wstring(1, letter) + L": erfolgreich verbunden.";
            app.m_trayIcon->ShowNotification(L"Prismateams", msg);
        }
        return 0;
    }

    case WM_SETTINGCHANGE: {
        app.ApplyThemeMode(SettingsManager::Instance().Get().themeMode);
        return 0;
    }

    case WM_DROPFILES: {
        HDROP hDrop = reinterpret_cast<HDROP>(wParam);
        wchar_t filePath[MAX_PATH] = { 0 };
        if (DragQueryFileW(hDrop, 0, filePath, MAX_PATH) > 0) {
            app.HandleFileOpen(filePath);
        }
        DragFinish(hDrop);
        return 0;
    }

    case WM_TRAYICON: {
        if (lParam == WM_LBUTTONDBLCLK) {
            ShowWindow(hWnd, SW_RESTORE);
            SetForegroundWindow(hWnd);
        } else if (lParam == WM_RBUTTONUP) {
            if (app.m_trayIcon) {
                app.m_trayIcon->ShowContextMenu(hWnd);
            }
        }
        return 0;
    }

    case WM_COPYDATA: {
        PCOPYDATASTRUCT pcds = reinterpret_cast<PCOPYDATASTRUCT>(lParam);
        if (pcds && pcds->lpData && pcds->cbData > 0) {
            std::wstring filePath(reinterpret_cast<const wchar_t*>(pcds->lpData), pcds->cbData / sizeof(wchar_t));
            ShowWindow(hWnd, SW_RESTORE);
            SetForegroundWindow(hWnd);
            app.HandleFileOpen(filePath);
        }
        return TRUE;
    }

    case WM_CLOSE: {
        if (SettingsManager::Instance().Get().minimizeToTray) {
            ShowWindow(hWnd, SW_HIDE);
            if (app.m_trayIcon) {
                app.m_trayIcon->ShowNotification(L"Prismateams", L"Die Anwendung l\xE4uft im Hintergrund weiter.");
            }
            return 0;
        }
        break;
    }

    case WM_DESTROY: {
        WebDavManager::Instance().UnmountCurrentDrive(true);
        PostQuitMessage(0);
        return 0;
    }
    }

    return DefWindowProcW(hWnd, message, wParam, lParam);
}

} // namespace Prismateams
