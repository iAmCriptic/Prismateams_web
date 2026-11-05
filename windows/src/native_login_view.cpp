#include "native_login_view.h"
#include "auth_manager.h"
#include "settings.h"
#include "passkey_authenticator.h"
#include "../resources/resource.h"

#include <commctrl.h>
#include <windowsx.h>

namespace Prismateams {

const wchar_t* const LOGIN_VIEW_CLASS = L"Prismateams_NativeLoginView_Class";

const int IDC_NL_SERVER   = 5001;
const int IDC_NL_EMAIL    = 5002;
const int IDC_NL_PASS     = 5003;
const int IDC_NL_2FA      = 5004;
const int IDC_NL_BTNLOGIN = 5005;
const int IDC_NL_BTNPASSK = 5006;
const int IDC_NL_BTNMIN   = 5007;
const int IDC_NL_BTNCLOSE = 5008;

// Subclass procedure for Edit controls to trigger login on [Enter]
static WNDPROC s_origEditProc = nullptr;
static LRESULT CALLBACK EditSubclassProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    if (msg == WM_KEYDOWN && wParam == VK_RETURN) {
        HWND hParent = GetParent(hWnd);
        if (hParent) {
            SendMessageW(hParent, WM_COMMAND, MAKEWPARAM(IDC_NL_BTNLOGIN, BN_CLICKED), 0);
            return 0;
        }
    }
    return CallWindowProcW(s_origEditProc, hWnd, msg, wParam, lParam);
}

NativeLoginView::NativeLoginView(HWND hWndParent, HINSTANCE hInstance)
    : m_hWndParent(hWndParent), m_hInstance(hInstance) {
    SetTheme(true);
}

NativeLoginView::~NativeLoginView() {
    if (m_hBrBg) DeleteObject(m_hBrBg);
    if (m_hBrCard) DeleteObject(m_hBrCard);
    if (m_hBrInput) DeleteObject(m_hBrInput);
    if (m_hBrBtnPrimary) DeleteObject(m_hBrBtnPrimary);
    if (m_hBrBtnSecondary) DeleteObject(m_hBrBtnSecondary);
    if (m_hPenCardBorder) DeleteObject(m_hPenCardBorder);
    if (m_hPenInputBorder) DeleteObject(m_hPenInputBorder);
    if (m_hFontTitle) DeleteObject(m_hFontTitle);
    if (m_hFontSub) DeleteObject(m_hFontSub);
    if (m_hFontBody) DeleteObject(m_hFontBody);
    if (m_hFontBold) DeleteObject(m_hFontBold);
}

void NativeLoginView::SetTheme(bool isDarkMode) {
    m_isDarkMode = isDarkMode;

    if (m_hBrBg) DeleteObject(m_hBrBg);
    if (m_hBrCard) DeleteObject(m_hBrCard);
    if (m_hBrInput) DeleteObject(m_hBrInput);
    if (m_hBrBtnPrimary) DeleteObject(m_hBrBtnPrimary);
    if (m_hBrBtnSecondary) DeleteObject(m_hBrBtnSecondary);
    if (m_hPenCardBorder) DeleteObject(m_hPenCardBorder);
    if (m_hPenInputBorder) DeleteObject(m_hPenInputBorder);

    if (m_isDarkMode) {
        m_hBrBg = CreateSolidBrush(RGB(15, 15, 23));           // Deep background
        m_hBrCard = CreateSolidBrush(RGB(26, 26, 38));         // Dark card
        m_hBrInput = CreateSolidBrush(RGB(35, 35, 50));        // Input bg
        m_hBrBtnPrimary = CreateSolidBrush(RGB(99, 102, 241)); // Indigo
        m_hBrBtnSecondary = CreateSolidBrush(RGB(40, 40, 58)); // Dark grey
        m_hPenCardBorder = CreatePen(PS_SOLID, 1, RGB(45, 45, 65));
        m_hPenInputBorder = CreatePen(PS_SOLID, 1, RGB(55, 55, 78));
    } else {
        m_hBrBg = CreateSolidBrush(RGB(241, 245, 249));        // Light slate
        m_hBrCard = CreateSolidBrush(RGB(255, 255, 255));      // White card
        m_hBrInput = CreateSolidBrush(RGB(248, 250, 252));     // Light input
        m_hBrBtnPrimary = CreateSolidBrush(RGB(79, 70, 229));  // Deep indigo
        m_hBrBtnSecondary = CreateSolidBrush(RGB(241, 245, 249));
        m_hPenCardBorder = CreatePen(PS_SOLID, 1, RGB(226, 232, 240));
        m_hPenInputBorder = CreatePen(PS_SOLID, 1, RGB(203, 213, 225));
    }

    if (!m_hFontTitle) {
        m_hFontTitle = CreateFontW(-20, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontSub = CreateFontW(-12, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontBody = CreateFontW(-13, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        m_hFontBold = CreateFontW(-13, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    }

    if (m_hWnd) {
        InvalidateRect(m_hWnd, nullptr, TRUE);
    }
}

bool NativeLoginView::Create() {
    WNDCLASSEXW wcex = { 0 };
    wcex.cbSize = sizeof(WNDCLASSEXW);
    wcex.style = CS_HREDRAW | CS_VREDRAW;
    wcex.lpfnWndProc = NativeLoginView::WndProc;
    wcex.hInstance = m_hInstance;
    wcex.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wcex.hbrBackground = m_hBrBg;
    wcex.lpszClassName = LOGIN_VIEW_CLASS;

    RegisterClassExW(&wcex);

    m_hWnd = CreateWindowExW(
        0,
        LOGIN_VIEW_CLASS,
        L"",
        WS_CHILD | WS_CLIPCHILDREN,
        0, 0, 800, 600,
        m_hWndParent, nullptr, m_hInstance, this
    );

    if (!m_hWnd) return false;

    // Create Edit Controls inside card
    m_editServer = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_SERVER, m_hInstance, nullptr);
    SendMessageW(m_editServer, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);

    m_editEmail = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_EMAIL, m_hInstance, nullptr);
    SendMessageW(m_editEmail, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);

    m_editPass = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | ES_PASSWORD | ES_AUTOHSCROLL, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_PASS, m_hInstance, nullptr);
    SendMessageW(m_editPass, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);

    m_edit2Fa = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
        WS_CHILD | ES_NUMBER | ES_AUTOHSCROLL, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_2FA, m_hInstance, nullptr);
    SendMessageW(m_edit2Fa, WM_SETFONT, (WPARAM)m_hFontBody, TRUE);

    // Buttons (Owner drawn)
    m_btnLogin = CreateWindowExW(0, L"BUTTON", L"Anmelden",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_BTNLOGIN, m_hInstance, nullptr);

    m_btnPasskey = CreateWindowExW(0, L"BUTTON", L"Passkey / Windows Hello",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_BTNPASSK, m_hInstance, nullptr);

    // Window controls for frameless mode (Minimize, Close)
    m_btnMin = CreateWindowExW(0, L"BUTTON", L"\x2014",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_BTNMIN, m_hInstance, nullptr);

    m_btnClose = CreateWindowExW(0, L"BUTTON", L"\x2715",
        WS_CHILD | WS_VISIBLE | BS_OWNERDRAW, 0, 0, 0, 0, m_hWnd, (HMENU)(INT_PTR)IDC_NL_BTNCLOSE, m_hInstance, nullptr);

    // Pre-fill fields
    SetWindowTextW(m_editServer, SettingsManager::Instance().Get().serverUrl.c_str());
    SetWindowTextW(m_editEmail, SettingsManager::Instance().Get().lastUserEmail.c_str());

    // Subclass Edit fields to support [Enter] key to submit
    s_origEditProc = (WNDPROC)GetWindowLongPtrW(m_editPass, GWLP_WNDPROC);
    if (s_origEditProc) {
        SetWindowLongPtrW(m_editServer, GWLP_WNDPROC, (LONG_PTR)EditSubclassProc);
        SetWindowLongPtrW(m_editEmail, GWLP_WNDPROC, (LONG_PTR)EditSubclassProc);
        SetWindowLongPtrW(m_editPass, GWLP_WNDPROC, (LONG_PTR)EditSubclassProc);
        SetWindowLongPtrW(m_edit2Fa, GWLP_WNDPROC, (LONG_PTR)EditSubclassProc);
    }

    RepositionControls();
    return true;
}

void NativeLoginView::Show(bool visible) {
    if (m_hWnd) {
        ShowWindow(m_hWnd, visible ? SW_SHOW : SW_HIDE);
        if (visible) {
            SetFocus(m_editPass);
        }
    }
}

void NativeLoginView::Resize(int width, int height) {
    if (m_hWnd) {
        SetWindowPos(m_hWnd, nullptr, 0, 0, width, height, SWP_NOMOVE | SWP_NOZORDER);
        RepositionControls();
    }
}

void NativeLoginView::RepositionControls() {
    if (!m_hWnd) return;

    RECT rc;
    GetClientRect(m_hWnd, &rc);
    int winW = rc.right - rc.left;
    int winH = rc.bottom - rc.top;

    int cardW = 440;
    int cardH = m_show2Fa ? 510 : 440;
    int cardX = (winW - cardW) / 2;
    int cardY = (winH - cardH) / 2;
    if (cardY < 20) cardY = 20;

    int contentX = cardX + 32;
    int contentW = cardW - 64;
    int curY = cardY + 95; // below title & subtitle

    // Server-URL
    curY += 20;
    SetWindowPos(m_editServer, nullptr, contentX, curY, contentW, 28, SWP_NOZORDER);
    curY += 48;

    // E-Mail
    SetWindowPos(m_editEmail, nullptr, contentX, curY, contentW, 28, SWP_NOZORDER);
    curY += 48;

    // Passwort
    SetWindowPos(m_editPass, nullptr, contentX, curY, contentW, 28, SWP_NOZORDER);
    curY += 48;

    // 2FA field (if active)
    if (m_show2Fa) {
        ShowWindow(m_edit2Fa, SW_SHOW);
        SetWindowPos(m_edit2Fa, nullptr, contentX, curY, contentW, 28, SWP_NOZORDER);
        curY += 50;
    } else {
        ShowWindow(m_edit2Fa, SW_HIDE);
    }

    curY += 10;
    // Anmelden Button
    SetWindowPos(m_btnLogin, nullptr, contentX, curY, contentW, 36, SWP_NOZORDER);
    curY += 44;

    // Passkey Button
    SetWindowPos(m_btnPasskey, nullptr, contentX, curY, contentW, 32, SWP_NOZORDER);

    // Window controls at top right
    SetWindowPos(m_btnMin, nullptr, winW - 88, 8, 38, 28, SWP_NOZORDER);
    SetWindowPos(m_btnClose, nullptr, winW - 46, 8, 38, 28, SWP_NOZORDER);

    InvalidateRect(m_hWnd, nullptr, TRUE);
}

void NativeLoginView::SetStatus(const std::wstring& message, bool isError) {
    m_statusMessage = message;
    m_statusIsError = isError;
    InvalidateRect(m_hWnd, nullptr, TRUE);
}

void NativeLoginView::PerformLogin() {
    wchar_t serverBuf[256], emailBuf[256], passBuf[256], totpBuf[32];
    GetWindowTextW(m_editServer, serverBuf, 256);
    GetWindowTextW(m_editEmail, emailBuf, 256);
    GetWindowTextW(m_editPass, passBuf, 256);
    GetWindowTextW(m_edit2Fa, totpBuf, 32);

    std::wstring serverUrl = serverBuf;
    while (!serverUrl.empty() && (serverUrl.back() == L'/' || serverUrl.back() == L' ')) serverUrl.pop_back();

    if (serverUrl.empty()) {
        SetStatus(L"Bitte Server-URL eingeben.", true);
        return;
    }

    SettingsManager::Instance().Get().serverUrl = serverUrl;
    SettingsManager::Instance().Save();
    AuthManager::Instance().SetServerUrl(serverUrl);

    SetStatus(L"Anmeldung l\xE4uft...", false);
    EnableWindow(m_btnLogin, FALSE);

    LoginResult res = AuthManager::Instance().Login(emailBuf, passBuf, totpBuf);
    EnableWindow(m_btnLogin, TRUE);

    if (res.requires2FA) {
        m_show2Fa = true;
        RepositionControls();
        SetFocus(m_edit2Fa);
        SetStatus(L"Zwei-Faktor-Code aus Authenticator-App erforderlich.", false);
        return;
    }

    if (res.success) {
        SetStatus(L"Anmeldung erfolgreich!", false);
        if (m_onLoginSuccess) {
            m_onLoginSuccess();
        }
    } else {
        SetStatus(res.errorMessage.empty() ? L"Anmeldung fehlgeschlagen." : res.errorMessage, true);
    }
}

void NativeLoginView::PerformPasskeyLogin() {
    wchar_t serverBuf[256];
    GetWindowTextW(m_editServer, serverBuf, 256);
    std::wstring serverUrl = serverBuf;
    while (!serverUrl.empty() && (serverUrl.back() == L'/' || serverUrl.back() == L' ')) serverUrl.pop_back();

    if (serverUrl.empty()) {
        SetStatus(L"Bitte Server-URL eingeben.", true);
        return;
    }

    AuthManager::Instance().SetServerUrl(serverUrl);

    // Extract rpId (host)
    std::wstring rpId = serverUrl;
    size_t scheme = rpId.find(L"://");
    if (scheme != std::string::npos) rpId = rpId.substr(scheme + 3);
    size_t port = rpId.find(L':');
    if (port != std::string::npos) rpId = rpId.substr(0, port);

    SetStatus(L"Windows Hello Authentifizierung wird ge\xF6ffnet...", false);
    auto res = PasskeyAuthenticator::Authenticate(m_hWnd, rpId, "login-challenge-prismateams");

    if (res.success) {
        SetStatus(L"Passkey erkannt! Sitzung wird gestartet...", false);
        if (m_onLoginSuccess) {
            m_onLoginSuccess();
        }
    } else {
        SetStatus(res.errorMessage, true);
    }
}

LRESULT CALLBACK NativeLoginView::WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    NativeLoginView* pThis = nullptr;
    if (message == WM_CREATE) {
        CREATESTRUCT* pcs = reinterpret_cast<CREATESTRUCT*>(lParam);
        pThis = reinterpret_cast<NativeLoginView*>(pcs->lpCreateParams);
        SetWindowLongPtrW(hWnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(pThis));
    } else {
        pThis = reinterpret_cast<NativeLoginView*>(GetWindowLongPtrW(hWnd, GWLP_USERDATA));
    }

    if (!pThis) return DefWindowProcW(hWnd, message, wParam, lParam);

    switch (message) {
    case WM_LBUTTONDOWN: {
        POINT curPt;
        GetCursorPos(&curPt);
        ReleaseCapture();
        SendMessageW(pThis->m_hWndParent, WM_NCLBUTTONDOWN, HTCAPTION, MAKELPARAM(curPt.x, curPt.y));
        return 0;
    }

    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);

        RECT rc;
        GetClientRect(hWnd, &rc);
        int winW = rc.right - rc.left;
        int winH = rc.bottom - rc.top;

        // Background
        FillRect(hdc, &rc, pThis->m_hBrBg);

        int cardW = 440;
        int cardH = pThis->m_show2Fa ? 510 : 440;
        int cardX = (winW - cardW) / 2;
        int cardY = (winH - cardH) / 2;
        if (cardY < 20) cardY = 20;

        // Draw Card with rounded corners
        RECT cardRc = { cardX, cardY, cardX + cardW, cardY + cardH };
        HPEN hOldPen = (HPEN)SelectObject(hdc, pThis->m_hPenCardBorder);
        HBRUSH hOldBr = (HBRUSH)SelectObject(hdc, pThis->m_hBrCard);

        RoundRect(hdc, cardRc.left, cardRc.top, cardRc.right, cardRc.bottom, 16, 16);

        SelectObject(hdc, hOldBr);
        SelectObject(hdc, hOldPen);

        SetBkMode(hdc, TRANSPARENT);

        // Header: Logo icon + Title
        HICON hIcon = LoadIconW(pThis->m_hInstance, MAKEINTRESOURCEW(IDI_PRISMATEAMS));
        if (hIcon) {
            DrawIconEx(hdc, cardX + 32, cardY + 28, hIcon, 36, 36, 0, nullptr, DI_NORMAL);
        }

        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(248, 250, 252) : RGB(15, 23, 42));
        HFONT hOldFont = (HFONT)SelectObject(hdc, pThis->m_hFontTitle);
        TextOutW(hdc, cardX + 78, cardY + 24, L"Prismateams Desktop", 19);

        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(148, 163, 184) : RGB(100, 116, 139));
        SelectObject(hdc, pThis->m_hFontSub);
        TextOutW(hdc, cardX + 78, cardY + 50, L"Sichere Anmeldung am Workspace", 30);

        // Field Labels
        SelectObject(hdc, pThis->m_hFontBold);
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(203, 213, 225) : RGB(51, 65, 85));

        int curY = cardY + 95;
        TextOutW(hdc, cardX + 32, curY, L"Server-URL:", 11);
        curY += 48;
        TextOutW(hdc, cardX + 32, curY, L"E-Mail / Benutzername:", 22);
        curY += 48;
        TextOutW(hdc, cardX + 32, curY, L"Passwort:", 9);

        if (pThis->m_show2Fa) {
            curY += 48;
            SetTextColor(hdc, RGB(99, 102, 241));
            TextOutW(hdc, cardX + 32, curY, L"Zwei-Faktor-Code (TOTP):", 24);
        }

        // Status / Error message banner
        if (!pThis->m_statusMessage.empty()) {
            SelectObject(hdc, pThis->m_hFontBody);
            COLORREF statusColor = pThis->m_statusIsError ? RGB(239, 68, 68) : RGB(34, 197, 94);
            SetTextColor(hdc, statusColor);

            RECT statusRc = { cardX + 32, cardY + cardH - 28, cardX + cardW - 32, cardY + cardH - 6 };
            DrawTextW(hdc, pThis->m_statusMessage.c_str(), -1, &statusRc, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
        }

        SelectObject(hdc, hOldFont);
        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_CTLCOLOREDIT: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, pThis->m_isDarkMode ? RGB(241, 245, 249) : RGB(15, 23, 42));
        SetBkColor(hdc, pThis->m_isDarkMode ? RGB(35, 35, 50) : RGB(248, 250, 252));
        return (INT_PTR)pThis->m_hBrInput;
    }

    case WM_DRAWITEM: {
        LPDRAWITEMSTRUCT pdis = (LPDRAWITEMSTRUCT)lParam;
        if (pdis->CtlType == ODT_BUTTON) {
            HDC hdc = pdis->hDC;
            RECT rc = pdis->rcItem;
            bool isSelected = (pdis->itemState & ODS_SELECTED);

            if (pdis->CtlID == IDC_NL_BTNCLOSE) {
                HBRUSH hBr = isSelected ? CreateSolidBrush(RGB(225, 29, 72)) : (pThis->m_isDarkMode ? CreateSolidBrush(RGB(35, 35, 48)) : CreateSolidBrush(RGB(226, 232, 240)));
                FillRect(hdc, &rc, hBr);
                DeleteObject(hBr);
                SetBkMode(hdc, TRANSPARENT);
                SetTextColor(hdc, isSelected ? RGB(255, 255, 255) : (pThis->m_isDarkMode ? RGB(200, 200, 210) : RGB(80, 80, 90)));
                HFONT hOldFont = (HFONT)SelectObject(hdc, pThis->m_hFontBold);
                DrawTextW(hdc, L"\x2715", -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
                SelectObject(hdc, hOldFont);
                return TRUE;
            }
            if (pdis->CtlID == IDC_NL_BTNMIN) {
                HBRUSH hBr = isSelected ? (pThis->m_isDarkMode ? CreateSolidBrush(RGB(50, 50, 70)) : CreateSolidBrush(RGB(200, 200, 210))) : (pThis->m_isDarkMode ? CreateSolidBrush(RGB(35, 35, 48)) : CreateSolidBrush(RGB(226, 232, 240)));
                FillRect(hdc, &rc, hBr);
                DeleteObject(hBr);
                SetBkMode(hdc, TRANSPARENT);
                SetTextColor(hdc, pThis->m_isDarkMode ? RGB(200, 200, 210) : RGB(80, 80, 90));
                HFONT hOldFont = (HFONT)SelectObject(hdc, pThis->m_hFontBold);
                DrawTextW(hdc, L"\x2014", -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
                SelectObject(hdc, hOldFont);
                return TRUE;
            }

            HBRUSH hBr = (pdis->CtlID == IDC_NL_BTNLOGIN) ? pThis->m_hBrBtnPrimary : pThis->m_hBrBtnSecondary;
            HPEN hPen = (pdis->CtlID == IDC_NL_BTNLOGIN) ? pThis->m_hPenCardBorder : pThis->m_hPenInputBorder;

            HPEN hOldPen = (HPEN)SelectObject(hdc, hPen);
            HBRUSH hOldBr = (HBRUSH)SelectObject(hdc, hBr);

            RoundRect(hdc, rc.left, rc.top, rc.right, rc.bottom, 8, 8);

            SelectObject(hdc, hOldBr);
            SelectObject(hdc, hOldPen);

            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, (pdis->CtlID == IDC_NL_BTNLOGIN) ? RGB(255, 255, 255) : (pThis->m_isDarkMode ? RGB(226, 232, 240) : RGB(51, 65, 85)));

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
        if (wmId == IDC_NL_BTNLOGIN) {
            pThis->PerformLogin();
            return 0;
        } else if (wmId == IDC_NL_BTNPASSK) {
            pThis->PerformPasskeyLogin();
            return 0;
        } else if (wmId == IDC_NL_BTNMIN) {
            ShowWindow(pThis->m_hWndParent, SW_MINIMIZE);
            return 0;
        } else if (wmId == IDC_NL_BTNCLOSE) {
            PostMessageW(pThis->m_hWndParent, WM_CLOSE, 0, 0);
            return 0;
        }
        break;
    }
    }

    return DefWindowProcW(hWnd, message, wParam, lParam);
}

} // namespace Prismateams
