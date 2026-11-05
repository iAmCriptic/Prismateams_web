#pragma once

#include <windows.h>
#include <string>
#include <memory>

#include "webview_controller.h"
#include "tray_icon.h"

namespace Prismateams {

class App {
public:
    static App& Instance();

    int Run(HINSTANCE hInstance, const std::wstring& cmdLine, int nCmdShow);

    HWND GetMainWindow() const { return m_hWndMain; }
    void NavigateTo(const std::wstring& url);
    void HandleFileOpen(const std::wstring& filePath);

private:
    App() = default;

    static LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);
    static INT_PTR CALLBACK LoginDlgProc(HWND hDlg, UINT message, WPARAM wParam, LPARAM lParam);
    static INT_PTR CALLBACK SettingsDlgProc(HWND hDlg, UINT message, WPARAM wParam, LPARAM lParam);

    bool RegisterAppClass();
    bool CreateMainWindow(int nCmdShow);
    void CreateToolbar(HWND hWnd);
    void UpdateToolbarStatus();

    void ShowLoginDialog();
    void ShowSettingsDialog();
    void PerformAutoMount();

    HINSTANCE m_hInstance = nullptr;
    HWND m_hWndMain = nullptr;
    HWND m_hWndToolbar = nullptr;

    HWND m_btnBack = nullptr;
    HWND m_btnForward = nullptr;
    HWND m_btnReload = nullptr;
    HWND m_btnMount = nullptr;
    HWND m_btnExplorer = nullptr;
    HWND m_btnSettings = nullptr;
    HWND m_lblStatus = nullptr;

    std::unique_ptr<WebViewController> m_webViewController;
    std::unique_ptr<TrayIcon> m_trayIcon;

    std::wstring m_initialFileArgument = L"";
    bool m_isStartingMinimized = false;
};

} // namespace Prismateams
