#pragma once

#include <windows.h>
#include <string>
#include <memory>

#include "webview_controller.h"
#include "tray_icon.h"
#include "native_login_view.h"

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
    bool IsDarkMode() const { return m_isDarkMode; }

private:
    App() = default;
    ~App();

    static LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);

    bool RegisterAppClass();
    bool CreateMainWindow(int nCmdShow);
    void CreateTitlebarControls(HWND hWnd);
    void LayoutViews(int width, int height);
    void ShowPrismateamsDropdownMenu();
    void OpenNativeSettings();

    void CheckSystemTheme();
    void DrawNavbarButton(LPDRAWITEMSTRUCT pdis);

    HINSTANCE m_hInstance = nullptr;
    HWND m_hWndMain = nullptr;

    // Titlebar buttons
    HWND m_btnPrismaMenu = nullptr;
    HWND m_btnSettings = nullptr;
    int m_hoverCaptionBtn = 0; // 0=none, 1=min, 2=max, 3=close

    // Sub-views
    std::unique_ptr<NativeLoginView> m_nativeLoginView;
    std::unique_ptr<WebViewController> m_webViewController;
    std::unique_ptr<TrayIcon> m_trayIcon;

    bool m_isDarkMode = true;
    bool m_isAuthenticated = false;
    bool m_isStartingMinimized = false;
    std::wstring m_initialFileArgument = L"";

    // Theme GDI objects
    HBRUSH m_hBrNavbar = nullptr;
    HBRUSH m_hBrBtnHover = nullptr;
    HBRUSH m_hBrCloseHover = nullptr;
    HPEN m_hPenNavBorder = nullptr;
    HFONT m_hFontNav = nullptr;
    HFONT m_hFontCaption = nullptr;
};

} // namespace Prismateams
