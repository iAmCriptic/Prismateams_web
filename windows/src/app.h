#pragma once

#include <windows.h>
#include <string>
#include <memory>

#include "webview_controller.h"
#include "tray_icon.h"

namespace Prismateams {

const int ID_NAV_PRISMATEAMS = 1001;
const int ID_NAV_SETTINGS    = 1002;
const int ID_NAV_MINIMIZE    = 1003;
const int ID_NAV_MAXIMIZE    = 1004;
const int ID_NAV_CLOSE       = 1005;

// Dropdown commands
const int IDM_POPUP_DOMAIN   = 2101;
const int IDM_POPUP_BACK     = 2102;
const int IDM_POPUP_FORWARD  = 2103;
const int IDM_POPUP_RELOAD   = 2104;
const int IDM_POPUP_HOME     = 2105;
const int IDM_POPUP_EXPLORER = 2106;

// Async UI messages
const UINT WM_APP_SESSION_VERIFIED = WM_APP + 101;
const UINT WM_APP_POST_JSON        = WM_APP + 102;
const UINT WM_APP_LOGIN_SUCCESS    = WM_APP + 103;
const UINT WM_APP_WEBDAV_SYNC      = WM_APP + 104;

class App {
public:
    static App& Instance();

    int Run(HINSTANCE hInstance, const std::wstring& cmdLine, int nCmdShow);

    HWND GetMainWindow() const { return m_hWndMain; }
    void NavigateTo(const std::wstring& url);
    void HandleFileOpen(const std::wstring& filePath);
    void OnLoginSuccess();
    void OnLogout();
    void SetDarkMode(bool isDark);
    void ApplyThemeMode(const std::wstring& themeMode);
    bool IsDarkMode() const { return m_isDarkMode; }
    void ShowTrayNotification(const std::wstring& title, const std::wstring& message);
    void UpdatePortalBranding(const std::wstring& portalName, const std::wstring& logoDataUri);
    void ResetPortalBranding();

private:
    App() = default;
    ~App();

    static LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);

    bool RegisterAppClass();
    bool CreateMainWindow(int nCmdShow);
    void LayoutViews(int width, int height);
    void OpenNativeSettings();

    void CheckSystemTheme();

    HINSTANCE m_hInstance = nullptr;
    HWND m_hWndMain = nullptr;

    // Sub-views
    std::unique_ptr<WebViewController> m_webViewController;
    std::unique_ptr<TrayIcon> m_trayIcon;

    bool m_isDarkMode = true;
    bool m_isAuthenticated = false;
    bool m_isStartingMinimized = false;
    std::wstring m_initialFileArgument = L"";

    // Theme GDI objects
    HBRUSH m_hBrNavbar = nullptr;
    HFONT m_hFontNav = nullptr;
    HICON m_hPortalIcon = nullptr;
};

} // namespace Prismateams
