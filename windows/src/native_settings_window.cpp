#include "native_settings_window.h"
#include "settings.h"
#include "auth_manager.h"
#include "webdav_manager.h"
#include "../resources/resource.h"

#include <commctrl.h>
#include <dwmapi.h>
#include <uxtheme.h>

#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "uxtheme.lib")

namespace Prismateams {

const wchar_t* const SETTINGS_WINDOW_CLASS = L"Prismateams_NativeSettingsWindow_Class";

const int IDC_SW_SERVER       = 6001;
const int IDC_SW_BTNTESTSRV   = 6002;
const int IDC_SW_LBLSRVSTAT   = 6003;
const int IDC_SW_COMBODRIVE   = 6004;
const int IDC_SW_CHKAUTOMOUNT = 6005;
const int IDC_SW_BTNMOUNT     = 6006;
const int IDC_SW_BTNEXPLORER  = 6007;
const int IDC_SW_LBLUSER      = 6008;
const int IDC_SW_BTNLOGOUT    = 6009;
const int IDC_SW_CHKAUTOSTART = 6010;
const int IDC_SW_CHKMINTRAY   = 6011;
const int IDC_SW_BTNSAVE      = 6012;
const int IDC_SW_BTNCANCEL    = 6013;

void NativeSettingsWindow::Show(HWND hWndParent, HINSTANCE hInstance, bool isDarkMode) {
    NativeSettingsWindow* win = new NativeSettingsWindow(hWndParent, hInstance, isDarkMode);
    if (win->Create()) {
        EnableWindow(hWndParent, FALSE);
        ShowWindow(win->m_hWnd, SW_SHOW);
        UpdateWindow(win->m_hWnd);

        MSG msg;
        while (IsWindow(win->m_hWnd) && GetMessageW(&msg, nullptr, 0, 0)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        EnableWindow(hWndParent, TRUE);
        SetForegroundWindow(hWndParent);
    }
    delete win;
}

NativeSettingsWindow::NativeSettingsWindow(HWND hWndParent, HINSTANCE hInstance, bool isDarkMode)
    : m_hWndParent(hWndParent), m_hInstance(hInstance), m_isDarkMode(isDarkMode) {
    SetTheme(isDarkMode);
}

NativeSettingsWindow::~NativeSettingsWindow() {
    if (m_hBrBg) DeleteObject(m_hBrBg);
    if (m_hBrCard) DeleteObject(m_hBrCard);
    if (m_hBrInput) DeleteObject(m_hBrInput);
    if (m_hBrBtnPrimary) DeleteObject(m_hBrBtnPrimary);
    if (m_hBrBtnSecondary) DeleteObject(m_hBrBtnSecondary);
    if (m_hPenBorder) DeleteObject(m_hPenBorder);
    if (m_hFontTitle) DeleteObject(m_hFontTitle);
    if (m_hFontHeading) DeleteObject(m_hFontHeading);
    if (m_hFontBody) DeleteObject(m_hFontBody);
    if (m_hFontBold) DeleteObject(m_hFontBold);
}

void NativeSettingsWindow::SetTheme(bool isDarkMode) {
    m_isDarkMode = isDarkMode;

    if (m_hBrBg) DeleteObject(m_hBrBg);
    if (m_hBrCard) DeleteObject(m_hBrCard);
    if (m_hBrInput) DeleteObject(m_hBrInput);
    if (m_hBrBtnPrimary) DeleteObject(m_hBrBtnPrimary);
    if (m_hBrBtnSecondary) DeleteObject(m_hBrBtnSecondary);
    if (m_hPenBorder) DeleteObject(m_hPenBorder);

    if (m_isDarkMode) {
        m_hBrBg = CreateSolidBrush(RGB(10, 14, 20));           // #0a0e14
        m_hBrCard = CreateSolidBrush(RGB(22, 27, 34));         // #161b22
        m_hBrInput = CreateSolidBrush(RGB(13, 17, 23));        // #0d1117
        m_hBrBtnPrimary = CreateSolidBrush(RGB(37, 99, 235));  // #2563eb
        m_hBrBtnSecondary = CreateSolidBrush(RGB(33, 38, 45)); // #21262d
        m_hPenBorder = CreatePen(PS_SOLID, 1, RGB(48, 54, 61)); // #30363d
    } else {
        m_hBrBg = CreateSolidBrush(RGB(241, 245, 249));
        m_hBrCard = CreateSolidBrush(RGB(255, 255, 255));
        m_hBrInput = CreateSolidBrush(RGB(248, 250, 252));
        m_hBrBtnPrimary = CreateSolidBrush(RGB(37, 99, 235));
        m_hBrBtnSecondary = CreateSolidBrush(RGB(241, 245, 249));
        m_hPenBorder = CreatePen(PS_SOLID, 1, RGB(226, 232, 240));
    }

    if (!m_hFontTitle) {
        m_hFontTitle = CreateFontW(-20, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontHeading = CreateFontW(-14, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontBody = CreateFontW(-13, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontBold = CreateFontW(-13, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    }
}

bool NativeSettingsWindow::Create() {
    WNDCLASSEXW wcex = { 0 };
    wcex.cbSize = sizeof(WNDCLASSEXW);
    wcex.style = CS_HREDRAW | CS_VREDRAW;
    wcex.lpfnWndProc = NativeSettingsWindow::WndProc;
    wcex.hInstance = m_hInstance;
    wcex.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wcex.hbrBackground = m_hBrBg;
    wcex.lpszClassName = SETTINGS_WINDOW_CLASS;

    RegisterClassExW(&wcex);

    int winW = 580;
    int winH = 710;

    RECT rcParent;
    GetWindowRect(m_hWndParent, &rcParent);
    int posX = rcParent.left + ((rcParent.right - rcParent.left) - winW) / 2;
    int posY = rcParent.top + ((rcParent.bottom - rcParent.top) - winH) / 2;

    m_hWnd = CreateWindowExW(
        0,
        SETTINGS_WINDOW_CLASS,
        L"Prismateams \x2014 Desktop-Einstellungen",
        WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_CLIPCHILDREN,
        posX, posY, winW, winH,
        m_hWndParent, nullptr, m_hInstance, this
    );

    if (!m_hWnd) return false;

    // Enable Windows 11 Immersive Dark Mode for title bar
    BOOL useDark = m_isDarkMode ? TRUE : FALSE;
    DwmSetWindowAttribute(m_hWnd, 20 /* DWMWA_USE_IMMERSIVE_DARK_MODE */, &useDark, sizeof(useDark));

    // --- Sektion 1: Netzwerklaufwerk ---
    m_comboDriveLetter = CreateWindowExW(0, L"COMBOBOX", L"",
        WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL | WS_TABSTOP,
        245, 88, 80, 150, m_hWnd, (HMENU)(INT_PTR)IDC_SW_COMBODRIVE, m_hInstance, nullptr);
    SendMessageW(m_comboDriveLetter, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);
    SetWindowTheme(m_comboDriveLetter, L"Explorer", nullptr);

    const wchar_t* letters = L"PQRSTUVWXYZABCDEFGHIJKLMNO";
    wchar_t curLetter = SettingsManager::Instance().Get().driveLetter;
    for (size_t i = 0; i < wcslen(letters); ++i) {
        wchar_t item[8] = { letters[i], L':', 0 };
        int idx = (int)SendMessageW(m_comboDriveLetter, CB_ADDSTRING, 0, (LPARAM)item);
        if (letters[i] == curLetter) {
            SendMessageW(m_comboDriveLetter, CB_SETCURSEL, idx, 0);
        }
    }

    m_checkAutoMount = CreateWindowExW(0, L"BUTTON", L"Netzlaufwerk bei App-Start automatisch verbinden",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX | WS_TABSTOP,
        46, 126, 420, 22, m_hWnd, (HMENU)(INT_PTR)IDC_SW_CHKAUTOMOUNT, m_hInstance, nullptr);
    SendMessageW(m_checkAutoMount, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);
    SetWindowTheme(m_checkAutoMount, L"Explorer", nullptr);
    CheckDlgButton(m_hWnd, IDC_SW_CHKAUTOMOUNT, SettingsManager::Instance().Get().autoMountDrive ? BST_CHECKED : BST_UNCHECKED);

    m_btnMountToggle = CreateWindowExW(0, L"BUTTON", L"Netzlaufwerk verbinden",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW | WS_TABSTOP,
        46, 158, 200, 34, m_hWnd, (HMENU)(INT_PTR)IDC_SW_BTNMOUNT, m_hInstance, nullptr);

    m_btnOpenExplorer = CreateWindowExW(0, L"BUTTON", L"Im Explorer \xF6ffnen",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW | WS_TABSTOP,
        258, 158, 170, 34, m_hWnd, (HMENU)(INT_PTR)IDC_SW_BTNEXPLORER, m_hInstance, nullptr);

    // --- Sektion 2: Server & Login ---
    m_editServer = CreateWindowExW(0, L"EDIT", SettingsManager::Instance().Get().serverUrl.c_str(),
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
        56, 266, 350, 22, m_hWnd, (HMENU)(INT_PTR)IDC_SW_SERVER, m_hInstance, nullptr);
    SetWindowTheme(m_editServer, L"", L"");
    SendMessageW(m_editServer, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);

    m_btnTestServer = CreateWindowExW(0, L"BUTTON", L"Pr\xFCfen",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW | WS_TABSTOP,
        426, 260, 100, 32, m_hWnd, (HMENU)(INT_PTR)IDC_SW_BTNTESTSRV, m_hInstance, nullptr);

    m_btnLogout = CreateWindowExW(0, L"BUTTON", L"Abmelden",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW | WS_TABSTOP,
        426, 316, 100, 32, m_hWnd, (HMENU)(INT_PTR)IDC_SW_BTNLOGOUT, m_hInstance, nullptr);

    // --- Sektion 3: System & Autostart ---
    m_checkAutoStart = CreateWindowExW(0, L"BUTTON", L"Mit Windows automatisch im Hintergrund starten",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX | WS_TABSTOP,
        46, 420, 420, 22, m_hWnd, (HMENU)(INT_PTR)IDC_SW_CHKAUTOSTART, m_hInstance, nullptr);
    SendMessageW(m_checkAutoStart, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);
    SetWindowTheme(m_checkAutoStart, L"Explorer", nullptr);
    CheckDlgButton(m_hWnd, IDC_SW_CHKAUTOSTART, SettingsManager::Instance().Get().autoStartWithWindows ? BST_CHECKED : BST_UNCHECKED);

    m_checkMinTray = CreateWindowExW(0, L"BUTTON", L"Beim Schlie\xDFen in den Infobereich (Tray) minimieren",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX | WS_TABSTOP,
        46, 452, 420, 22, m_hWnd, (HMENU)(INT_PTR)IDC_SW_CHKMINTRAY, m_hInstance, nullptr);
    SendMessageW(m_checkMinTray, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);
    SetWindowTheme(m_checkMinTray, L"Explorer", nullptr);
    CheckDlgButton(m_hWnd, IDC_SW_CHKMINTRAY, SettingsManager::Instance().Get().minimizeToTray ? BST_CHECKED : BST_UNCHECKED);

    // --- Bottom Action Buttons ---
    m_btnSave = CreateWindowExW(0, L"BUTTON", L"Speichern && Schlie\xDFen",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW | WS_TABSTOP,
        290, 608, 165, 38, m_hWnd, (HMENU)(INT_PTR)IDC_SW_BTNSAVE, m_hInstance, nullptr);

    m_btnCancel = CreateWindowExW(0, L"BUTTON", L"Abbrechen",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW | WS_TABSTOP,
        465, 608, 85, 38, m_hWnd, (HMENU)(INT_PTR)IDC_SW_BTNCANCEL, m_hInstance, nullptr);

    UpdateDriveStatus();
    return true;
}

void NativeSettingsWindow::UpdateDriveStatus() {
    bool isMounted = WebDavManager::Instance().IsMounted();
    SetWindowTextW(m_btnMountToggle, isMounted ? L"Laufwerk trennen" : L"Netzlaufwerk verbinden");
    EnableWindow(m_btnOpenExplorer, isMounted ? TRUE : FALSE);
    InvalidateRect(m_hWnd, nullptr, TRUE);
}

void NativeSettingsWindow::ToggleMount() {
    if (WebDavManager::Instance().IsMounted()) {
        WebDavManager::Instance().UnmountCurrentDrive(true);
    } else {
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
        }
    }
    UpdateDriveStatus();
}

void NativeSettingsWindow::TestServerConnection() {
    wchar_t serverBuf[256];
    GetWindowTextW(m_editServer, serverBuf, 256);
    std::wstring sUrl = serverBuf;
    while (!sUrl.empty() && (sUrl.back() == L'/' || sUrl.back() == L' ')) sUrl.pop_back();

    AuthManager::Instance().SetServerUrl(sUrl);
    std::wstring title;
    bool ok = AuthManager::Instance().CheckServerReachable(title);

    MessageBoxW(
        m_hWnd,
        ok ? L"Verbindung zum Prismateams-Server erfolgreich hergestellt!" : L"Server nicht erreichbar. Bitte Server-URL und Netzwerkverbindung pr\xFCfen.",
        L"Prismateams Servertest",
        ok ? (MB_ICONINFORMATION | MB_OK) : (MB_ICONERROR | MB_OK)
    );
}

void NativeSettingsWindow::SaveAndClose() {
    auto& s = SettingsManager::Instance().Get();

    wchar_t serverBuf[256];
    GetWindowTextW(m_editServer, serverBuf, 256);
    std::wstring newUrl = serverBuf;
    while (!newUrl.empty() && (newUrl.back() == L'/' || newUrl.back() == L' ')) newUrl.pop_back();

    s.serverUrl = newUrl;
    AuthManager::Instance().SetServerUrl(newUrl);

    int sel = (int)SendMessageW(m_comboDriveLetter, CB_GETCURSEL, 0, 0);
    if (sel != CB_ERR) {
        wchar_t buf[8];
        SendMessageW(m_comboDriveLetter, CB_GETLBTEXT, sel, (LPARAM)buf);
        s.driveLetter = buf[0];
    }

    s.autoMountDrive = (IsDlgButtonChecked(m_hWnd, IDC_SW_CHKAUTOMOUNT) == BST_CHECKED);
    s.autoStartWithWindows = (IsDlgButtonChecked(m_hWnd, IDC_SW_CHKAUTOSTART) == BST_CHECKED);
    s.minimizeToTray = (IsDlgButtonChecked(m_hWnd, IDC_SW_CHKMINTRAY) == BST_CHECKED);

    SettingsManager::Instance().Save();
    DestroyWindow(m_hWnd);
}

void NativeSettingsWindow::Logout() {
    if (MessageBoxW(m_hWnd, L"M\xF6chten Sie sich wirklich von Prismateams abmelden?\nDas Netzlaufwerk wird dabei getrennt.", L"Abmelden", MB_ICONQUESTION | MB_YESNO) == IDYES) {
        AuthManager::Instance().Logout();
        WebDavManager::Instance().UnmountCurrentDrive(true);
        PostMessageW(m_hWndParent, WM_COMMAND, MAKEWPARAM(2006, 0), 0); // ID_TRAY_LOGOUT
        DestroyWindow(m_hWnd);
    }
}

LRESULT CALLBACK NativeSettingsWindow::WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    NativeSettingsWindow* pThis = nullptr;
    if (message == WM_CREATE) {
        CREATESTRUCT* pcs = reinterpret_cast<CREATESTRUCT*>(lParam);
        pThis = reinterpret_cast<NativeSettingsWindow*>(pcs->lpCreateParams);
        SetWindowLongPtrW(hWnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(pThis));
    } else {
        pThis = reinterpret_cast<NativeSettingsWindow*>(GetWindowLongPtrW(hWnd, GWLP_USERDATA));
    }

    if (!pThis) return DefWindowProcW(hWnd, message, wParam, lParam);

    switch (message) {
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);

        RECT rc;
        GetClientRect(hWnd, &rc);
        FillRect(hdc, &rc, pThis->m_hBrBg);

        SetBkMode(hdc, TRANSPARENT);

        // Header Title
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(248, 250, 252) : RGB(15, 23, 42));
        HFONT hOldFont = (HFONT)SelectObject(hdc, pThis->m_hFontTitle);
        TextOutW(hdc, 30, 20, L"Desktop-Einstellungen", 21);

        // --- Card 1: Netzlaufwerk ---
        RECT card1 = { 30, 56, 550, 208 };
        HPEN hOldPen = (HPEN)SelectObject(hdc, pThis->m_hPenBorder);
        HBRUSH hOldBr = (HBRUSH)SelectObject(hdc, pThis->m_hBrCard);
        RoundRect(hdc, card1.left, card1.top, card1.right, card1.bottom, 12, 12);

        SelectObject(hdc, pThis->m_hFontHeading);
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(226, 232, 240) : RGB(30, 41, 59));
        TextOutW(hdc, 46, 68, L"Windows Explorer & Netzlaufwerk", 31);

        SelectObject(hdc, pThis->m_hFontBody);
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(148, 163, 184) : RGB(100, 116, 139));
        TextOutW(hdc, 46, 92, L"Bevorzugter Laufwerksbuchstabe:", 31);

        // Drive status pill inside card 1
        bool isMounted = WebDavManager::Instance().IsMounted();
        wchar_t letter = WebDavManager::Instance().GetMountedDriveLetter();
        COLORREF dotCol = isMounted ? RGB(34, 197, 94) : RGB(148, 163, 184);

        HBRUSH hDot = CreateSolidBrush(dotCol);
        HPEN hDotPen = CreatePen(PS_SOLID, 1, dotCol);
        SelectObject(hdc, hDot);
        SelectObject(hdc, hDotPen);
        Ellipse(hdc, 345, 94, 353, 102);
        DeleteObject(hDot);
        DeleteObject(hDotPen);

        SelectObject(hdc, pThis->m_hFontBold);
        SetTextColor(hdc, isMounted ? RGB(34, 197, 94) : (pThis->m_isDarkMode ? RGB(148, 163, 184) : RGB(100, 116, 139)));
        std::wstring statStr = isMounted ? (L"Laufwerk " + std::wstring(1, letter) + L": aktiv") : L"Getrennt";
        TextOutW(hdc, 360, 90, statStr.c_str(), static_cast<int>(statStr.length()));

        // --- Card 2: Server & Authentifizierung ---
        RECT card2 = { 30, 222, 550, 368 };
        SelectObject(hdc, pThis->m_hPenBorder);
        SelectObject(hdc, pThis->m_hBrCard);
        RoundRect(hdc, card2.left, card2.top, card2.right, card2.bottom, 12, 12);

        SelectObject(hdc, pThis->m_hFontHeading);
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(226, 232, 240) : RGB(30, 41, 59));
        TextOutW(hdc, 46, 234, L"Server & Authentifizierung", 26);

        // Input container box for Server URL
        SelectObject(hdc, pThis->m_hPenBorder);
        SelectObject(hdc, pThis->m_hBrInput);
        RoundRect(hdc, 46, 260, 414, 292, 8, 8);

        // User info inside Card 2
        SelectObject(hdc, pThis->m_hFontBody);
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(148, 163, 184) : RGB(100, 116, 139));
        std::wstring userText = L"Angemeldet als: " + (AuthManager::Instance().GetUserEmail().empty() ? L"Nicht angemeldet" : AuthManager::Instance().GetUserEmail());
        TextOutW(hdc, 46, 322, userText.c_str(), static_cast<int>(userText.length()));

        // --- Card 3: System & Verhalten ---
        RECT card3 = { 30, 382, 550, 492 };
        SelectObject(hdc, pThis->m_hPenBorder);
        SelectObject(hdc, pThis->m_hBrCard);
        RoundRect(hdc, card3.left, card3.top, card3.right, card3.bottom, 12, 12);

        SelectObject(hdc, pThis->m_hFontHeading);
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(226, 232, 240) : RGB(30, 41, 59));
        TextOutW(hdc, 46, 394, L"System & Verhalten", 18);

        SelectObject(hdc, hOldBr);
        SelectObject(hdc, hOldPen);
        SelectObject(hdc, hOldFont);

        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_CTLCOLORSTATIC: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(226, 232, 240) : RGB(30, 41, 59));
        SetBkColor(hdc, pThis->m_isDarkMode ? RGB(22, 27, 34) : RGB(255, 255, 255));
        return (INT_PTR)pThis->m_hBrCard;
    }

    case WM_CTLCOLOREDIT: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(241, 245, 249) : RGB(15, 23, 42));
        SetBkColor(hdc, pThis->m_isDarkMode ? RGB(13, 17, 23) : RGB(248, 250, 252));
        return (INT_PTR)pThis->m_hBrInput;
    }

    case WM_DRAWITEM: {
        LPDRAWITEMSTRUCT pdis = (LPDRAWITEMSTRUCT)lParam;
        if (pdis->CtlType == ODT_BUTTON) {
            HDC hdc = pdis->hDC;
            RECT rc = pdis->rcItem;
            bool isSelected = (pdis->itemState & ODS_SELECTED);
            bool isPrimary = (pdis->CtlID == IDC_SW_BTNSAVE);
            bool isDanger = (pdis->CtlID == IDC_SW_BTNLOGOUT);

            COLORREF bgColor;
            if (isDanger) {
                bgColor = isSelected ? RGB(185, 28, 28) : RGB(220, 38, 38);
            } else if (isPrimary) {
                bgColor = isSelected ? RGB(29, 78, 216) : RGB(37, 99, 235);
            } else {
                bgColor = isSelected ? (pThis->m_isDarkMode ? RGB(22, 27, 34) : RGB(226, 232, 240))
                                     : (pThis->m_isDarkMode ? RGB(33, 38, 45) : RGB(241, 245, 249));
            }

            HBRUSH hBr = CreateSolidBrush(bgColor);
            HPEN hPen = (isPrimary || isDanger) ? CreatePen(PS_SOLID, 1, bgColor) : pThis->m_hPenBorder;

            HPEN hOldPen = (HPEN)SelectObject(hdc, hPen);
            HBRUSH hOldBr = (HBRUSH)SelectObject(hdc, hBr);

            RoundRect(hdc, rc.left, rc.top, rc.right, rc.bottom, 8, 8);

            SelectObject(hdc, hOldBr);
            SelectObject(hdc, hOldPen);
            DeleteObject(hBr);
            if (isPrimary || isDanger) DeleteObject(hPen);

            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, (isPrimary || isDanger) ? RGB(255, 255, 255)
                                                     : (pThis->m_isDarkMode ? RGB(241, 245, 249) : RGB(30, 41, 59)));

            HFONT hOldFont = (HFONT)SelectObject(hdc, pThis->m_hFontBold);

            wchar_t text[64];
            GetWindowTextW(pdis->hwndItem, text, 64);
            DrawTextW(hdc, text, -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

            SelectObject(hdc, hOldFont);
            return TRUE;
        }
        break;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        switch (wmId) {
        case IDC_SW_BTNTESTSRV:
            pThis->TestServerConnection();
            break;
        case IDC_SW_BTNMOUNT:
            pThis->ToggleMount();
            break;
        case IDC_SW_BTNEXPLORER:
            WebDavManager::Instance().OpenInExplorer();
            break;
        case IDC_SW_BTNLOGOUT:
            pThis->Logout();
            break;
        case IDC_SW_BTNSAVE:
            pThis->SaveAndClose();
            break;
        case IDC_SW_BTNCANCEL:
            DestroyWindow(hWnd);
            break;
        }
        return 0;
    }

    case WM_CLOSE:
        DestroyWindow(hWnd);
        return 0;
    }

    return DefWindowProcW(hWnd, message, wParam, lParam);
}

} // namespace Prismateams
