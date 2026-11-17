#pragma once

#include <windows.h>
#include <string>
#include <functional>

namespace Prismateams {

class NativeSettingsWindow {
public:
    static void Show(HWND hWndParent, HINSTANCE hInstance, bool isDarkMode);

private:
    NativeSettingsWindow(HWND hWndParent, HINSTANCE hInstance, bool isDarkMode);
    ~NativeSettingsWindow();

    bool Create();
    void SetTheme(bool isDarkMode);
    void UpdateDriveStatus();
    void TestServerConnection();
    void ToggleMount();
    void SaveAndClose();
    void Logout();

    static LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);

    HWND m_hWndParent;
    HINSTANCE m_hInstance;
    HWND m_hWnd = nullptr;
    bool m_isDarkMode = true;

    // Controls
    HWND m_editServer = nullptr;
    HWND m_btnTestServer = nullptr;
    HWND m_lblServerStatus = nullptr;

    HWND m_lblDriveStatus = nullptr;
    HWND m_comboDriveLetter = nullptr;
    HWND m_checkAutoMount = nullptr;
    HWND m_btnMountToggle = nullptr;
    HWND m_btnOpenExplorer = nullptr;

    HWND m_lblUserInfo = nullptr;
    HWND m_btnLogout = nullptr;

    HWND m_checkAutoStart = nullptr;
    HWND m_checkMinTray = nullptr;
    HWND m_btnSave = nullptr;
    HWND m_btnCancel = nullptr;

    // GDI Brushes & Pens
    HBRUSH m_hBrBg = nullptr;
    HBRUSH m_hBrCard = nullptr;
    HBRUSH m_hBrInput = nullptr;
    HBRUSH m_hBrBtnPrimary = nullptr;
    HBRUSH m_hBrBtnSecondary = nullptr;
    HPEN m_hPenBorder = nullptr;
    HFONT m_hFontTitle = nullptr;
    HFONT m_hFontHeading = nullptr;
    HFONT m_hFontBody = nullptr;
    HFONT m_hFontBold = nullptr;
};

} // namespace Prismateams
