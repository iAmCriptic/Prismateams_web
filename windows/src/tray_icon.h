#pragma once

#include <windows.h>
#include <string>

#define WM_TRAYICON (WM_APP + 100)

namespace Prismateams {

class TrayIcon {
public:
    TrayIcon(HWND hWndParent, HINSTANCE hInstance);
    ~TrayIcon();

    bool Create();
    void Remove();

    void ShowNotification(const std::wstring& title, const std::wstring& message);
    void UpdateTooltip(const std::wstring& tooltip);

    void ShowContextMenu(HWND hWnd);

private:
    HWND m_hWndParent;
    HINSTANCE m_hInstance;
    NOTIFYICONDATAW m_nid;
    bool m_isCreated = false;
};

} // namespace Prismateams
