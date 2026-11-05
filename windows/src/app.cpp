#include "app.h"
#include "settings.h"
#include "auth_manager.h"
#include "webdav_manager.h"
#include "file_router.h"
#include "../resources/resource.h"

#include <commctrl.h>
#include <windowsx.h>
#include <shellapi.h>

#pragma comment(lib, "comctl32.lib")

namespace Prismateams {

const wchar_t* const MAIN_WINDOW_CLASS = L"Prismateams_MainWindow_Class";
const int TOOLBAR_HEIGHT = 42;

// Control IDs
const int ID_BTN_BACK     = 1001;
const int ID_BTN_FORWARD  = 1002;
const int ID_BTN_RELOAD   = 1003;
const int ID_BTN_MOUNT    = 1004;
const int ID_BTN_EXPLORER = 1005;
const int ID_BTN_SETTINGS = 1006;
const int ID_LBL_STATUS   = 1007;

App& App::Instance() {
    static App instance;
    return instance;
}

int App::Run(HINSTANCE hInstance, const std::wstring& cmdLine, int nCmdShow) {
    m_hInstance = hInstance;

    // Load settings
    SettingsManager::Instance().Load();
    AuthManager::Instance().SetServerUrl(SettingsManager::Instance().Get().serverUrl);

    // Parse command line arguments
    if (!cmdLine.empty()) {
        if (cmdLine.find(L"--minimized") != std::string::npos) {
            m_isStartingMinimized = true;
        } else {
            // Strip quotes if present
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

    // Initialize System Tray
    m_trayIcon = std::make_unique<TrayIcon>(m_hWndMain, m_hInstance);
    m_trayIcon->Create();

    // Initialize WebView2
    m_webViewController = std::make_unique<WebViewController>(m_hWndMain);
    m_webViewController->Initialize([this](bool success) {
        if (!success) {
            MessageBoxW(
                m_hWndMain,
                L"Die Microsoft Edge WebView2-Laufzeitumgebung konnte nicht initialisiert werden.\nBitte stellen Sie sicher, dass Microsoft Edge installiert ist.",
                L"Prismateams - Fehler",
                MB_ICONERROR | MB_OK
            );
            return;
        }

        // Verify existing session
        if (AuthManager::Instance().VerifyStoredSession()) {
            PerformAutoMount();

            if (!m_initialFileArgument.empty()) {
                HandleFileOpen(m_initialFileArgument);
            } else {
                NavigateTo(AuthManager::Instance().GetServerUrl());
            }
        } else {
            // Show Native Login
            ShowLoginDialog();
        }

        UpdateToolbarStatus();
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
    wcex.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
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
        CW_USEDEFAULT, CW_USEDEFAULT, 1280, 800,
        nullptr, nullptr, m_hInstance, this
    );

    if (!m_hWndMain) return false;

    CreateToolbar(m_hWndMain);

    if (nCmdShow != SW_HIDE) {
        ShowWindow(m_hWndMain, nCmdShow);
        UpdateWindow(m_hWndMain);
    }

    return true;
}

void App::CreateToolbar(HWND hWnd) {
    HFONT hFont = (HFONT)GetStockObject(DEFAULT_GUI_FONT);

    m_btnBack = CreateWindowExW(0, L"BUTTON", L"◀", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        10, 7, 32, 28, hWnd, (HMENU)(INT_PTR)ID_BTN_BACK, m_hInstance, nullptr);
    SendMessageW(m_btnBack, WM_SETFONT, (WPARAM)hFont, TRUE);

    m_btnForward = CreateWindowExW(0, L"BUTTON", L"▶", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        46, 7, 32, 28, hWnd, (HMENU)(INT_PTR)ID_BTN_FORWARD, m_hInstance, nullptr);
    SendMessageW(m_btnForward, WM_SETFONT, (WPARAM)hFont, TRUE);

    m_btnReload = CreateWindowExW(0, L"BUTTON", L"↻", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        82, 7, 32, 28, hWnd, (HMENU)(INT_PTR)ID_BTN_RELOAD, m_hInstance, nullptr);
    SendMessageW(m_btnReload, WM_SETFONT, (WPARAM)hFont, TRUE);

    m_btnMount = CreateWindowExW(0, L"BUTTON", L"Netzlaufwerk (P:) verbinden", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        124, 7, 210, 28, hWnd, (HMENU)(INT_PTR)ID_BTN_MOUNT, m_hInstance, nullptr);
    SendMessageW(m_btnMount, WM_SETFONT, (WPARAM)hFont, TRUE);

    m_btnExplorer = CreateWindowExW(0, L"BUTTON", L"Im Explorer öffnen", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        340, 7, 140, 28, hWnd, (HMENU)(INT_PTR)ID_BTN_EXPLORER, m_hInstance, nullptr);
    SendMessageW(m_btnExplorer, WM_SETFONT, (WPARAM)hFont, TRUE);
    EnableWindow(m_btnExplorer, FALSE);

    m_btnSettings = CreateWindowExW(0, L"BUTTON", L"⚙ Einstellungen", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        486, 7, 120, 28, hWnd, (HMENU)(INT_PTR)ID_BTN_SETTINGS, m_hInstance, nullptr);
    SendMessageW(m_btnSettings, WM_SETFONT, (WPARAM)hFont, TRUE);

    m_lblStatus = CreateWindowExW(0, L"STATIC", L"Prismateams wird geladen...", WS_CHILD | WS_VISIBLE | SS_LEFT | SS_CENTERIMAGE,
        616, 7, 450, 28, hWnd, (HMENU)(INT_PTR)ID_LBL_STATUS, m_hInstance, nullptr);
    SendMessageW(m_lblStatus, WM_SETFONT, (WPARAM)hFont, TRUE);
}

void App::UpdateToolbarStatus() {
    bool isMounted = WebDavManager::Instance().IsMounted();
    wchar_t letter = WebDavManager::Instance().GetMountedDriveLetter();

    std::wstring mountBtnText = isMounted ?
        (L"Laufwerk " + std::wstring(1, letter) + L": trennen") :
        (L"Netzlaufwerk (" + std::wstring(1, letter) + L":) verbinden");

    SetWindowTextW(m_btnMount, mountBtnText.c_str());
    EnableWindow(m_btnExplorer, isMounted ? TRUE : FALSE);

    std::wstring statusText;
    if (AuthManager::Instance().IsAuthenticated()) {
        statusText = L"Angemeldet als: " + AuthManager::Instance().GetUserEmail();
        if (isMounted) {
            statusText += L" | Netzlaufwerk " + std::wstring(1, letter) + L": aktiv";
        }
    } else {
        statusText = L"Nicht angemeldet";
    }

    SetWindowTextW(m_lblStatus, statusText.c_str());
}

void App::PerformAutoMount() {
    if (!SettingsManager::Instance().Get().autoMountDrive) return;
    if (WebDavManager::Instance().IsMounted()) return;

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
}

void App::NavigateTo(const std::wstring& url) {
    if (m_webViewController) {
        m_webViewController->Navigate(url);
    }
}

void App::HandleFileOpen(const std::wstring& filePath) {
    FileRouteResult route = FileRouter::Instance().RouteLocalPath(filePath);
    if (route.success && !route.navigationUrl.empty()) {
        NavigateTo(route.navigationUrl);
        if (m_trayIcon) {
            std::wstring notice = L"Öffne " + (route.filename.empty() ? L"Datei" : route.filename) + L" in Prismateams...";
            m_trayIcon->ShowNotification(L"Live Bearbeiten", notice);
        }
    }
}

void App::ShowLoginDialog() {
    DialogBoxParamW(
        m_hInstance,
        MAKEINTRESOURCEW(IDD_LOGIN_DIALOG),
        m_hWndMain,
        App::LoginDlgProc,
        reinterpret_cast<LPARAM>(this)
    );
}

void App::ShowSettingsDialog() {
    DialogBoxParamW(
        m_hInstance,
        MAKEINTRESOURCEW(IDD_SETTINGS_DIALOG),
        m_hWndMain,
        App::SettingsDlgProc,
        reinterpret_cast<LPARAM>(this)
    );
}

LRESULT CALLBACK App::WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    App& app = App::Instance();

    switch (message) {
    case WM_SIZE: {
        int width = LOWORD(lParam);
        int height = HIWORD(lParam);
        if (app.m_webViewController) {
            // Position webview below toolbar
            app.m_webViewController->Resize(width, height - TOOLBAR_HEIGHT);
            SetWindowPos(app.m_webViewController->GetParentHwnd(), nullptr, 0, TOOLBAR_HEIGHT, width, height - TOOLBAR_HEIGHT, SWP_NOZORDER);
        }
        return 0;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        switch (wmId) {
        case ID_BTN_BACK:
            if (app.m_webViewController) app.m_webViewController->GoBack();
            break;
        case ID_BTN_FORWARD:
            if (app.m_webViewController) app.m_webViewController->GoForward();
            break;
        case ID_BTN_RELOAD:
            if (app.m_webViewController) app.m_webViewController->Reload();
            break;
        case ID_BTN_MOUNT:
        case ID_TRAY_MOUNT:
            if (WebDavManager::Instance().IsMounted()) {
                WebDavManager::Instance().UnmountCurrentDrive(true);
            } else {
                app.PerformAutoMount();
            }
            app.UpdateToolbarStatus();
            break;
        case ID_BTN_EXPLORER:
        case ID_TRAY_OPEN_EXPLORER:
            WebDavManager::Instance().OpenInExplorer();
            break;
        case ID_BTN_SETTINGS:
        case ID_TRAY_SETTINGS:
            app.ShowSettingsDialog();
            break;
        case ID_TRAY_OPEN:
            ShowWindow(hWnd, SW_RESTORE);
            SetForegroundWindow(hWnd);
            break;
        case ID_TRAY_UNMOUNT:
            WebDavManager::Instance().UnmountCurrentDrive(true);
            app.UpdateToolbarStatus();
            break;
        case ID_TRAY_LOGOUT:
            AuthManager::Instance().Logout();
            WebDavManager::Instance().UnmountCurrentDrive(true);
            app.UpdateToolbarStatus();
            app.ShowLoginDialog();
            break;
        case ID_TRAY_EXIT:
        case IDM_EXIT:
            DestroyWindow(hWnd);
            break;
        default:
            return DefWindowProcW(hWnd, message, wParam, lParam);
        }
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
        // Inter-process communication: file opened from explorer while already running
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
                app.m_trayIcon->ShowNotification(L"Prismateams", L"Die Anwendung läuft im Hintergrund weiter.");
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

INT_PTR CALLBACK App::LoginDlgProc(HWND hDlg, UINT message, WPARAM wParam, LPARAM lParam) {
    App* pApp = &App::Instance();

    switch (message) {
    case WM_INITDIALOG: {
        // Pre-fill server URL and last email
        SetDlgItemTextW(hDlg, IDC_EDIT_SERVER_URL, SettingsManager::Instance().Get().serverUrl.c_str());
        SetDlgItemTextW(hDlg, IDC_EDIT_EMAIL, SettingsManager::Instance().Get().lastUserEmail.c_str());
        ShowWindow(GetDlgItem(hDlg, IDC_GROUP_2FA), SW_HIDE);
        ShowWindow(GetDlgItem(hDlg, IDC_EDIT_2FA_CODE), SW_HIDE);
        return TRUE;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        if (wmId == IDC_BTN_LOGIN) {
            wchar_t serverBuf[256], emailBuf[256], passBuf[256], totpBuf[32];
            GetDlgItemTextW(hDlg, IDC_EDIT_SERVER_URL, serverBuf, 256);
            GetDlgItemTextW(hDlg, IDC_EDIT_EMAIL, emailBuf, 256);
            GetDlgItemTextW(hDlg, IDC_EDIT_PASSWORD, passBuf, 256);
            GetDlgItemTextW(hDlg, IDC_EDIT_2FA_CODE, totpBuf, 32);

            std::wstring serverUrl = serverBuf;
            SettingsManager::Instance().Get().serverUrl = serverUrl;
            SettingsManager::Instance().Save();
            AuthManager::Instance().SetServerUrl(serverUrl);

            SetDlgItemTextW(hDlg, IDC_STATIC_STATUS, L"Anmeldung läuft...");
            EnableWindow(GetDlgItem(hDlg, IDC_BTN_LOGIN), FALSE);

            LoginResult res = AuthManager::Instance().Login(emailBuf, passBuf, totpBuf);
            EnableWindow(GetDlgItem(hDlg, IDC_BTN_LOGIN), TRUE);

            if (res.requires2FA) {
                ShowWindow(GetDlgItem(hDlg, IDC_GROUP_2FA), SW_SHOW);
                ShowWindow(GetDlgItem(hDlg, IDC_EDIT_2FA_CODE), SW_SHOW);
                SetFocus(GetDlgItem(hDlg, IDC_EDIT_2FA_CODE));
                SetDlgItemTextW(hDlg, IDC_STATIC_STATUS, L"Bitte 2FA-Code aus Authenticator-App eingeben.");
                return TRUE;
            }

            if (res.success) {
                SetDlgItemTextW(hDlg, IDC_STATIC_STATUS, L"Erfolgreich!");
                pApp->PerformAutoMount();
                pApp->NavigateTo(serverUrl);
                pApp->UpdateToolbarStatus();
                EndDialog(hDlg, IDOK);
                return TRUE;
            } else {
                SetDlgItemTextW(hDlg, IDC_STATIC_STATUS, res.errorMessage.c_str());
            }
            return TRUE;
        } else if (wmId == IDC_BTN_PASSKEY) {
            // Passkey login: navigates webview to passkey login page
            wchar_t serverBuf[256];
            GetDlgItemTextW(hDlg, IDC_EDIT_SERVER_URL, serverBuf, 256);
            std::wstring serverUrl = serverBuf;
            SettingsManager::Instance().Get().serverUrl = serverUrl;
            SettingsManager::Instance().Save();
            AuthManager::Instance().SetServerUrl(serverUrl);

            pApp->NavigateTo(serverUrl + L"/login");
            EndDialog(hDlg, IDOK);
            return TRUE;
        } else if (wmId == IDCANCEL) {
            EndDialog(hDlg, IDCANCEL);
            return TRUE;
        }
        break;
    }
    }
    return FALSE;
}

INT_PTR CALLBACK App::SettingsDlgProc(HWND hDlg, UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
    case WM_INITDIALOG: {
        auto& s = SettingsManager::Instance().Get();
        HWND hCombo = GetDlgItem(hDlg, IDC_COMBO_DRIVE_LETTER);

        // Populate letters P, Q, R, S, T, U, V, W, X, Y, Z
        const wchar_t* letters = L"PQRSTUVWXYZABCDEFGHIJKLMNO";
        for (size_t i = 0; i < wcslen(letters); ++i) {
            wchar_t item[8] = { letters[i], L':', 0 };
            int idx = (int)SendMessageW(hCombo, CB_ADDSTRING, 0, (LPARAM)item);
            if (letters[i] == s.driveLetter) {
                SendMessageW(hCombo, CB_SETCURSEL, idx, 0);
            }
        }

        CheckDlgButton(hDlg, IDC_CHECK_AUTO_MOUNT, s.autoMountDrive ? BST_CHECKED : BST_UNCHECKED);
        CheckDlgButton(hDlg, IDC_CHECK_AUTO_START, s.autoStartWithWindows ? BST_CHECKED : BST_UNCHECKED);
        return TRUE;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        if (wmId == IDOK) {
            auto& s = SettingsManager::Instance().Get();
            HWND hCombo = GetDlgItem(hDlg, IDC_COMBO_DRIVE_LETTER);
            int sel = (int)SendMessageW(hCombo, CB_GETCURSEL, 0, 0);
            if (sel != CB_ERR) {
                wchar_t buf[8];
                SendMessageW(hCombo, CB_GETLBTEXT, sel, (LPARAM)buf);
                s.driveLetter = buf[0];
            }

            s.autoMountDrive = (IsDlgButtonChecked(hDlg, IDC_CHECK_AUTO_MOUNT) == BST_CHECKED);
            s.autoStartWithWindows = (IsDlgButtonChecked(hDlg, IDC_CHECK_AUTO_START) == BST_CHECKED);
            SettingsManager::Instance().Save();

            EndDialog(hDlg, IDOK);
            return TRUE;
        } else if (wmId == IDCANCEL) {
            EndDialog(hDlg, IDCANCEL);
            return TRUE;
        }
        break;
    }
    }
    return FALSE;
}

} // namespace Prismateams
