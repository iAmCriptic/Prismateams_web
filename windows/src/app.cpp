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
    if (m_hBrBtnHover) DeleteObject(m_hBrBtnHover);
    if (m_hBrCloseHover) DeleteObject(m_hBrCloseHover);
    if (m_hPenNavBorder) DeleteObject(m_hPenNavBorder);
    if (m_hFontNav) DeleteObject(m_hFontNav);
    if (m_hFontCaption) DeleteObject(m_hFontCaption);
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
    if (m_hBrBtnHover) DeleteObject(m_hBrBtnHover);
    if (m_hBrCloseHover) DeleteObject(m_hBrCloseHover);
    if (m_hPenNavBorder) DeleteObject(m_hPenNavBorder);

    if (m_isDarkMode) {
        m_hBrNavbar = CreateSolidBrush(RGB(22, 22, 32));      // Antigravity dark navbar
        m_hBrBtnHover = CreateSolidBrush(RGB(40, 40, 58));    // Hover tab
        m_hBrCloseHover = CreateSolidBrush(RGB(225, 29, 72)); // Red close hover
        m_hPenNavBorder = CreatePen(PS_SOLID, 1, RGB(42, 42, 60));
    } else {
        m_hBrNavbar = CreateSolidBrush(RGB(248, 250, 252));    // Light navbar
        m_hBrBtnHover = CreateSolidBrush(RGB(226, 232, 240));  // Light hover
        m_hBrCloseHover = CreateSolidBrush(RGB(225, 29, 72));
        m_hPenNavBorder = CreatePen(PS_SOLID, 1, RGB(226, 232, 240));
    }

    if (!m_hFontNav) {
        m_hFontNav = CreateFontW(-12, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontCaption = CreateFontW(-11, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
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
        0,
        MAIN_WINDOW_CLASS,
        L"Prismateams Desktop",
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
        CW_USEDEFAULT, CW_USEDEFAULT, 1360, 860,
        nullptr, nullptr, m_hInstance, this
    );

    if (!m_hWndMain) return false;

    BOOL val = m_isDarkMode ? TRUE : FALSE;
    DwmSetWindowAttribute(m_hWndMain, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &val, sizeof(val));

    MARGINS margins = { 0, 0, 1, 0 };
    DwmExtendFrameIntoClientArea(m_hWndMain, &margins);

    CreateTitlebarControls(m_hWndMain);

    if (nCmdShow != SW_HIDE) {
        ShowWindow(m_hWndMain, nCmdShow);
        UpdateWindow(m_hWndMain);
    }

    return true;
}

void App::CreateTitlebarControls(HWND hWnd) {
    // Menu items inside the single custom titlebar
    m_btnPrismaMenu = CreateWindowExW(0, L"BUTTON", L"Prismateams \x25BE",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
        34, 4, 115, 28, hWnd, (HMENU)(INT_PTR)ID_NAV_PRISMATEAMS, m_hInstance, nullptr);

    m_btnSettings = CreateWindowExW(0, L"BUTTON", L"Einstellungen",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
        155, 4, 105, 28, hWnd, (HMENU)(INT_PTR)ID_NAV_SETTINGS, m_hInstance, nullptr);
}

void App::ShowPrismateamsDropdownMenu() {
    HMENU hMenu = CreatePopupMenu();
    if (!hMenu) return;

    const std::wstring& serverUrl = SettingsManager::Instance().Get().serverUrl;
    std::wstring domainInfo = L"Server: " + (serverUrl.empty() ? L"Nicht konfiguriert" : serverUrl);

    AppendMenuW(hMenu, MF_STRING | MF_DISABLED, IDM_POPUP_DOMAIN, domainInfo.c_str());
    AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(hMenu, MF_STRING, IDM_POPUP_BACK, L"\x25C0  Zur\xFCck\tAlt + Links");
    AppendMenuW(hMenu, MF_STRING, IDM_POPUP_FORWARD, L"\x25B6  Vorw\xE4rts\tAlt + Rechts");
    AppendMenuW(hMenu, MF_STRING, IDM_POPUP_RELOAD, L"\x21BB  Neu laden\tF5");
    AppendMenuW(hMenu, MF_STRING, IDM_POPUP_HOME, L"\x2302  Startseite / Dashboard");

    if (WebDavManager::Instance().IsMounted()) {
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);
        wchar_t driveLetter = WebDavManager::Instance().GetMountedDriveLetter();
        std::wstring driveItem = L"\x229E  Netzlaufwerk " + std::wstring(1, driveLetter) + L": im Explorer \xF6ffnen";
        AppendMenuW(hMenu, MF_STRING, IDM_POPUP_EXPLORER, driveItem.c_str());
    }

    RECT rcBtn;
    GetWindowRect(m_btnPrismaMenu, &rcBtn);

    SetForegroundWindow(m_hWndMain);
    TrackPopupMenuEx(hMenu, TPM_LEFTALIGN | TPM_TOPALIGN, rcBtn.left, rcBtn.bottom + 2, m_hWndMain, nullptr);
    DestroyMenu(hMenu);
}

void App::DrawNavbarButton(LPDRAWITEMSTRUCT pdis) {
    HDC hdc = pdis->hDC;
    RECT rc = pdis->rcItem;
    bool isSelected = (pdis->itemState & ODS_SELECTED);

    HBRUSH hBr = isSelected ? m_hBrBtnHover : m_hBrNavbar;
    FillRect(hdc, &rc, hBr);

    SetBkMode(hdc, TRANSPARENT);
    COLORREF txtColor = m_isDarkMode ? RGB(226, 232, 240) : RGB(30, 41, 59);
    SetTextColor(hdc, txtColor);

    HFONT hOldFont = (HFONT)SelectObject(hdc, m_hFontNav);

    wchar_t text[64];
    GetWindowTextW(pdis->hwndItem, text, 64);
    DrawTextW(hdc, text, -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

    SelectObject(hdc, hOldFont);
}

void App::LayoutViews(int width, int height) {
    int contentY = TITLEBAR_HEIGHT;
    int contentH = height - TITLEBAR_HEIGHT;
    if (contentH < 0) contentH = 0;

    if (m_nativeLoginView && !m_isAuthenticated) {
        m_nativeLoginView->Resize(width, contentH);
        SetWindowPos(m_nativeLoginView->GetHwnd(), nullptr, 0, contentY, width, contentH, SWP_NOZORDER);
    }

    if (m_webViewController && m_isAuthenticated) {
        m_webViewController->Resize(width, contentH);
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
            std::wstring ssoUrl = AuthManager::Instance().GetServerUrl() + L"/auth/desktop-login?token=" + token + L"&next=/dashboard";
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

    // Hide WebView2
    if (m_webViewController) {
        m_webViewController->SetVisible(false);
        m_webViewController->Navigate(L"about:blank");
    }

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

        if (pt.y >= 0 && pt.y < TITLEBAR_HEIGHT) {
            if (pt.x >= winW - 46) return HTCLOSE;
            if (pt.x >= winW - 92) return HTMAXBUTTON;
            if (pt.x >= winW - 138) return HTMINBUTTON;

            if ((pt.x >= 34 && pt.x < 150) || (pt.x >= 155 && pt.x < 260)) {
                return HTCLIENT;
            }

            return HTCAPTION;
        }

        return HTCLIENT;
    }

    case WM_NCMOUSEMOVE: {
        POINT pt = { GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam) };
        ScreenToClient(hWnd, &pt);
        RECT rc;
        GetClientRect(hWnd, &rc);
        int winW = rc.right;

        int newHover = 0;
        if (pt.y >= 0 && pt.y < TITLEBAR_HEIGHT) {
            if (pt.x >= winW - 46) newHover = 3;       // Close
            else if (pt.x >= winW - 92) newHover = 2;  // Maximize (Snap Layout on Win11!)
            else if (pt.x >= winW - 138) newHover = 1; // Minimize
        }

        if (newHover != app.m_hoverCaptionBtn) {
            app.m_hoverCaptionBtn = newHover;
            RECT rcTop = { winW - 140, 0, winW, TITLEBAR_HEIGHT };
            InvalidateRect(hWnd, &rcTop, FALSE);
        }

        TRACKMOUSEEVENT tme = { sizeof(TRACKMOUSEEVENT), TME_NONCLIENT | TME_LEAVE, hWnd, 0 };
        TrackMouseEvent(&tme);
        break;
    }

    case WM_NCMOUSELEAVE: {
        if (app.m_hoverCaptionBtn != 0) {
            app.m_hoverCaptionBtn = 0;
            RECT rc;
            GetClientRect(hWnd, &rc);
            RECT rcTop = { rc.right - 140, 0, rc.right, TITLEBAR_HEIGHT };
            InvalidateRect(hWnd, &rcTop, FALSE);
        }
        break;
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
        int winW = rc.right;

        RECT rcTitle = { 0, 0, winW, TITLEBAR_HEIGHT };
        FillRect(hdc, &rcTitle, app.m_hBrNavbar);

        // 1. Icon
        HICON hIcon = LoadIconW(app.m_hInstance, MAKEINTRESOURCEW(IDI_PRISMATEAMS));
        if (hIcon) {
            DrawIconEx(hdc, 10, 9, hIcon, 18, 18, 0, nullptr, DI_NORMAL);
        }

        // 2. Middle Title
        const std::wstring& serverUrl = SettingsManager::Instance().Get().serverUrl;
        std::wstring titleText = L"Prismateams Desktop \x2014 " + (serverUrl.empty() ? L"http://localhost:5000" : serverUrl);

        SetBkMode(hdc, TRANSPARENT);
        SetTextColor(hdc, app.m_isDarkMode ? RGB(160, 174, 192) : RGB(100, 116, 139));
        HFONT hOldFont = (HFONT)SelectObject(hdc, app.m_hFontNav);

        RECT rcCenter = { 270, 0, winW - 145, TITLEBAR_HEIGHT };
        DrawTextW(hdc, titleText.c_str(), -1, &rcCenter, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);

        // 3. Caption Buttons
        SelectObject(hdc, app.m_hFontCaption);

        RECT rcMin = { winW - 138, 0, winW - 92, TITLEBAR_HEIGHT };
        if (app.m_hoverCaptionBtn == 1) {
            FillRect(hdc, &rcMin, app.m_hBrBtnHover);
        }
        SetTextColor(hdc, app.m_isDarkMode ? RGB(226, 232, 240) : RGB(30, 41, 59));
        DrawTextW(hdc, L"\x2014", -1, &rcMin, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        RECT rcMax = { winW - 92, 0, winW - 46, TITLEBAR_HEIGHT };
        if (app.m_hoverCaptionBtn == 2) {
            FillRect(hdc, &rcMax, app.m_hBrBtnHover);
        }
        DrawTextW(hdc, IsZoomed(hWnd) ? L"\x25F2" : L"\x25A1", -1, &rcMax, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        RECT rcClose = { winW - 46, 0, winW, TITLEBAR_HEIGHT };
        if (app.m_hoverCaptionBtn == 3) {
            FillRect(hdc, &rcClose, app.m_hBrCloseHover);
            SetTextColor(hdc, RGB(255, 255, 255));
        }
        DrawTextW(hdc, L"\x2715", -1, &rcClose, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

        // Separator
        HPEN hOldPen = (HPEN)SelectObject(hdc, app.m_hPenNavBorder);
        MoveToEx(hdc, 0, TITLEBAR_HEIGHT - 1, nullptr);
        LineTo(hdc, winW, TITLEBAR_HEIGHT - 1);
        SelectObject(hdc, hOldPen);

        SelectObject(hdc, hOldFont);
        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_DRAWITEM: {
        LPDRAWITEMSTRUCT pdis = (LPDRAWITEMSTRUCT)lParam;
        if (pdis->CtlType == ODT_BUTTON) {
            app.DrawNavbarButton(pdis);
            return TRUE;
        }
        break;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        switch (wmId) {
        case ID_NAV_PRISMATEAMS:
            app.ShowPrismateamsDropdownMenu();
            break;
        case ID_NAV_SETTINGS:
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
        case IDM_POPUP_EXPLORER:
            WebDavManager::Instance().OpenInExplorer();
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
