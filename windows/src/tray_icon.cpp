#include "tray_icon.h"
#include "../resources/resource.h"
#include "webdav_manager.h"
#include <shellapi.h>

namespace Prismateams {

TrayIcon::TrayIcon(HWND hWndParent, HINSTANCE hInstance)
    : m_hWndParent(hWndParent), m_hInstance(hInstance) {
    memset(&m_nid, 0, sizeof(m_nid));
}

TrayIcon::~TrayIcon() {
    Remove();
}

bool TrayIcon::Create() {
    if (m_isCreated) return true;

    m_nid.cbSize = sizeof(NOTIFYICONDATAW);
    m_nid.hWnd = m_hWndParent;
    m_nid.uID = 1;
    m_nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
    m_nid.uCallbackMessage = WM_TRAYICON;
    m_nid.hIcon = LoadIconW(m_hInstance, MAKEINTRESOURCEW(IDI_PRISMATEAMS));
    if (!m_nid.hIcon) {
        m_nid.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    }
    wcscpy_s(m_nid.szTip, L"Prismateams Desktop");

    m_isCreated = (Shell_NotifyIconW(NIM_ADD, &m_nid) == TRUE);
    return m_isCreated;
}

void TrayIcon::Remove() {
    if (m_isCreated) {
        Shell_NotifyIconW(NIM_DELETE, &m_nid);
        m_isCreated = false;
    }
}

void TrayIcon::ShowNotification(const std::wstring& title, const std::wstring& message) {
    if (!m_isCreated) Create();

    m_nid.uFlags |= NIF_INFO;
    m_nid.dwInfoFlags = NIIF_INFO;
    wcsncpy_s(m_nid.szInfoTitle, title.c_str(), _TRUNCATE);
    wcsncpy_s(m_nid.szInfo, message.c_str(), _TRUNCATE);

    Shell_NotifyIconW(NIM_MODIFY, &m_nid);
    m_nid.uFlags &= ~NIF_INFO;
}

void TrayIcon::UpdateTooltip(const std::wstring& tooltip) {
    if (!m_isCreated) return;
    wcsncpy_s(m_nid.szTip, tooltip.c_str(), _TRUNCATE);
    m_nid.uFlags = NIF_TIP;
    Shell_NotifyIconW(NIM_MODIFY, &m_nid);
}

void TrayIcon::ShowContextMenu(HWND hWnd) {
    HMENU hMenu = CreatePopupMenu();
    if (!hMenu) return;

    AppendMenuW(hMenu, MF_STRING, ID_TRAY_OPEN, L"Prismateams \xF6ffnen");
    AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);

    bool isMounted = WebDavManager::Instance().IsMounted();
    wchar_t driveLetter = WebDavManager::Instance().GetMountedDriveLetter();

    std::wstring openExplorerText = L"Netzlaufwerk (" + std::wstring(1, driveLetter) + L":) im Explorer \xF6ffnen";
    AppendMenuW(hMenu, (isMounted ? MF_STRING : (MF_STRING | MF_GRAYED)), ID_TRAY_OPEN_EXPLORER, openExplorerText.c_str());

    AppendMenuW(hMenu, (isMounted ? (MF_STRING | MF_GRAYED) : MF_STRING), ID_TRAY_MOUNT, L"Netzlaufwerk verbinden");
    AppendMenuW(hMenu, (isMounted ? MF_STRING : (MF_STRING | MF_GRAYED)), ID_TRAY_UNMOUNT, L"Netzlaufwerk trennen");

    AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(hMenu, MF_STRING, ID_TRAY_SETTINGS, L"Einstellungen...");
    AppendMenuW(hMenu, MF_STRING, ID_TRAY_LOGOUT, L"Abmelden");
    AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(hMenu, MF_STRING, ID_TRAY_EXIT, L"Beenden");

    POINT pt;
    GetCursorPos(&pt);
    SetForegroundWindow(hWnd);
    TrackPopupMenu(hMenu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y, 0, hWnd, nullptr);
    PostMessageW(hWnd, WM_NULL, 0, 0);

    DestroyMenu(hMenu);
}

} // namespace Prismateams
