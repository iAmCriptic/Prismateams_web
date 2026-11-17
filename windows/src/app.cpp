#include "app.h"
#include "settings.h"
#include "auth_manager.h"
#include "webdav_manager.h"
#include "file_router.h"
#include "native_settings_window.h"
#include "../resources/resource.h"

#include <dwmapi.h>
#include <windowsx.h>
#include <shellapi.h>

#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "uxtheme.lib")

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
        m_hBrNavbar = CreateSolidBrush(RGB(22, 22, 32));      // Dark background
    } else {
        m_hBrNavbar = CreateSolidBrush(RGB(248, 250, 252));    // Light background
    }

    if (!m_hFontNav) {
        m_hFontNav = CreateFontW(-12, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    }

    if (m_hWndMain) {
        BOOL val = m_isDarkMode ? TRUE : FALSE;
        DwmSetWindowAttribute(m_hWndMain, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &val, sizeof(val));

        if (m_nativeLoginView) {
            m_nativeLoginView->SetTheme(m_isDarkMode);
        }

        InvalidateRect(m_hWndMain, nullptr, TRUE);
    }
}

int App::Run(HINSTANCE hInstance, const std::wstring& cmdLine, int nCmdShow) {
    m_hInstance = hInstance;

    // Load local settings
    SettingsManager::Instance().Load();
    AuthManager::Instance().SetServerUrl(SettingsManager::Instance().Get().serverUrl);

    CheckSystemTheme();

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

    // Native Login View (created as child view)
    m_nativeLoginView = std::make_unique<NativeLoginView>(m_hWndMain, m_hInstance);
    m_nativeLoginView->Create();
    m_nativeLoginView->SetOnLoginSuccess([this]() {
        OnLoginSuccess();
    });

    // Initialize WebView2
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

        // Verify existing stored session
        if (AuthManager::Instance().VerifyStoredSession()) {
            OnLoginSuccess();
        } else {
            // Not authenticated: Show NATIVE LOGIN VIEW
            OnLogout();
        }
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

    if (nCmdShow != SW_HIDE) {
        ShowWindow(m_hWndMain, nCmdShow);
        UpdateWindow(m_hWndMain);
    }

    return true;
}

void App::LayoutViews(int width, int height) {
    if (m_nativeLoginView && !m_isAuthenticated) {
        m_nativeLoginView->Resize(width, height);
        SetWindowPos(m_nativeLoginView->GetHwnd(), nullptr, 0, 0, width, height, SWP_NOZORDER);
    }

    if (m_webViewController && m_isAuthenticated) {
        m_webViewController->Resize(width, height);
    }
}

void App::OpenNativeSettings() {
    NativeSettingsWindow::Show(m_hWndMain, m_hInstance, m_isDarkMode);
}

void App::OnLoginSuccess() {
    m_isAuthenticated = true;

    // Auto mount WebDAV drive
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
        if (m_trayIcon && WebDavManager::Instance().IsMounted()) {
            std::wstring msg = L"Netzlaufwerk " + std::wstring(1, assigned) + L": erfolgreich eingebunden.";
            m_trayIcon->ShowNotification(L"Prismateams", msg);
        }
    }

    // Hide native login view
    if (m_nativeLoginView) {
        m_nativeLoginView->Show(false);
    }

    // Show WebView2 & Navigate
    if (m_webViewController) {
        m_webViewController->SetVisible(true);

        const std::wstring& token = AuthManager::Instance().GetAuthToken();
        const std::wstring& cookie = AuthManager::Instance().GetSessionCookie();
        if (!cookie.empty()) {
            m_webViewController->SyncSessionCookie(AuthManager::Instance().GetServerUrl(), cookie);
        }

        if (!m_initialFileArgument.empty()) {
            HandleFileOpen(m_initialFileArgument);
        } else if (!token.empty()) {
            // Direct SSO login via token -> lands directly on dashboard, 100% authenticated!
            std::wstring ssoUrl = AuthManager::Instance().GetServerUrl() + L"/desktop-login?token=" + token + L"&next=/dashboard";
            NavigateTo(ssoUrl);
        } else {
            NavigateTo(AuthManager::Instance().GetServerUrl() + L"/dashboard");
        }
    }

    RECT rc;
    GetClientRect(m_hWndMain, &rc);
    LayoutViews(rc.right - rc.left, rc.bottom - rc.top);
    InvalidateRect(m_hWndMain, nullptr, TRUE);
}

void App::OnLogout() {
    m_isAuthenticated = false;

    // Clear session cookies and hide WebView2
    if (m_webViewController) {
        m_webViewController->ClearAllCookies();
        m_webViewController->SetVisible(false);
        m_webViewController->Navigate(L"about:blank");
    }

    AuthManager::Instance().Logout();

    // Show native login view
    if (m_nativeLoginView) {
        m_nativeLoginView->Show(true);
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
            if (IsZoomed(hWnd)) {
                NCCALCSIZE_PARAMS* pParams = reinterpret_cast<NCCALCSIZE_PARAMS*>(lParam);
                int borderX = GetSystemMetrics(SM_CXFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER);
                int borderY = GetSystemMetrics(SM_CYFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER);
                pParams->rgrc[0].left += borderX;
                pParams->rgrc[0].top += borderY;
                pParams->rgrc[0].right -= borderX;
                pParams->rgrc[0].bottom -= borderY;
            }
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

    case WM_SETTINGCHANGE: {
        app.CheckSystemTheme();
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
