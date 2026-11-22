#include "webview_controller.h"
#include "desktop_ui.h"
#include "passkey_authenticator.h"
#include "settings.h"
#include "webdav_manager.h"
#include "auth_manager.h"
#include "app.h"

#include <commdlg.h>
#include <shellapi.h>
#include <sstream>
#include <thread>
#include <wrl/client.h>
#include <wrl/event.h>

#pragma comment(lib, "comdlg32.lib")

using namespace Microsoft::WRL;

namespace Prismateams {

WebViewController::WebViewController(HWND hWndParent)
    : m_hWndParent(hWndParent) {
}

WebViewController::~WebViewController() {
    if (m_controller) {
        m_controller->Close();
        m_controller = nullptr;
    }
    m_webview = nullptr;
    m_environment = nullptr;
}

void WebViewController::Initialize(std::function<void(bool success)> onComplete) {
    std::wstring userDataDir = SettingsManager::Instance().GetAppDataDirectory() + L"\\WebView2";

    HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(
        nullptr, // Evergreen runtime
        userDataDir.c_str(),
        nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [this, onComplete](HRESULT result, ICoreWebView2Environment* env) -> HRESULT {
                if (FAILED(result) || !env) {
                    if (onComplete) onComplete(false);
                    return result;
                }
                m_environment = env;

                m_environment->CreateCoreWebView2Controller(
                    m_hWndParent,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [this, onComplete](HRESULT res, ICoreWebView2Controller* controller) -> HRESULT {
                            if (FAILED(res) || !controller) {
                                if (onComplete) onComplete(false);
                                return res;
                            }

                            m_controller = controller;
                            m_controller->get_CoreWebView2(&m_webview);

                            RECT bounds;
                            GetClientRect(m_hWndParent, &bounds);
                            m_controller->put_Bounds(bounds);
                            m_controller->put_IsVisible(m_isVisible ? TRUE : FALSE);

                            SetupEventHandlers();
                            InjectNativeBridgeScript();

                            m_isInitialized = true;
                            if (!m_pendingNavigateUrl.empty()) {
                                m_webview->Navigate(m_pendingNavigateUrl.c_str());
                                m_pendingNavigateUrl.clear();
                            }
                            if (onComplete) onComplete(true);
                            return S_OK;
                        }
                    ).Get()
                );
                return S_OK;
            }
        ).Get()
    );

    if (FAILED(hr)) {
        if (onComplete) onComplete(false);
    }
}

void WebViewController::SetupEventHandlers() {
    if (!m_webview) return;

    // Enable Passkey / WebAuthn & General Settings
    ComPtr<ICoreWebView2Settings> settings;
    if (SUCCEEDED(m_webview->get_Settings(&settings)) && settings) {
        settings->put_IsScriptEnabled(TRUE);
        settings->put_AreDefaultScriptDialogsEnabled(TRUE);
        settings->put_IsWebMessageEnabled(TRUE);
        settings->put_AreDevToolsEnabled(TRUE);
        settings->put_IsStatusBarEnabled(FALSE);

        ComPtr<ICoreWebView2Settings9> settings9;
        if (SUCCEEDED(settings.As(&settings9)) && settings9) {
            settings9->put_IsNonClientRegionSupportEnabled(TRUE);
        }
    }

    // Message handler from web page
    m_webview->add_WebMessageReceived(
        Callback<ICoreWebView2WebMessageReceivedEventHandler>(
            [this](ICoreWebView2* sender, ICoreWebView2WebMessageReceivedEventArgs* args) -> HRESULT {
                LPWSTR messageRaw = nullptr;
                if (SUCCEEDED(args->TryGetWebMessageAsString(&messageRaw)) && messageRaw) {
                    HandleWebMessage(messageRaw);
                    CoTaskMemFree(messageRaw);
                }
                return S_OK;
            }
        ).Get(),
        nullptr
    );

    // Intercept external links (target="_blank" or external domains)
    m_webview->add_NewWindowRequested(
        Callback<ICoreWebView2NewWindowRequestedEventHandler>(
            [this](ICoreWebView2* sender, ICoreWebView2NewWindowRequestedEventArgs* args) -> HRESULT {
                LPWSTR uriRaw = nullptr;
                if (SUCCEEDED(args->get_Uri(&uriRaw)) && uriRaw) {
                    std::wstring uri = uriRaw;
                    CoTaskMemFree(uriRaw);

                    const std::wstring& serverUrl = AuthManager::Instance().GetServerUrl();
                    // If link is external, open in user's default browser
                    if (uri.find(serverUrl) != 0 && uri.find(L"http") == 0) {
                        args->put_Handled(TRUE);
                        ShellExecuteW(nullptr, L"open", uri.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
                    } else {
                        // Open in same webview
                        args->put_Handled(TRUE);
                        m_webview->Navigate(uri.c_str());
                    }
                }
                return S_OK;
            }
        ).Get(),
        nullptr
    );

    // Intercept web /login redirects (e.g. after clicking Abmelden in portal UI) and return to Desktop Login Screen
    m_webview->add_NavigationStarting(
        Callback<ICoreWebView2NavigationStartingEventHandler>(
            [this](ICoreWebView2* sender, ICoreWebView2NavigationStartingEventArgs* args) -> HRESULT {
                LPWSTR uriRaw = nullptr;
                if (SUCCEEDED(args->get_Uri(&uriRaw)) && uriRaw) {
                    std::wstring uri = uriRaw;
                    CoTaskMemFree(uriRaw);

                    const std::wstring& srv = AuthManager::Instance().GetServerUrl();
                    if (!srv.empty() && uri.find(srv) == 0) {
                        std::wstring rel = uri.substr(srv.length());
                        if (rel == L"/login" || rel.rfind(L"/login?", 0) == 0 ||
                            rel == L"/auth/login" || rel.rfind(L"/auth/login?", 0) == 0) {
                            args->put_Cancel(TRUE);
                            PostMessageW(m_hWndParent, WM_COMMAND, MAKEWPARAM(2006, 0), 0); // ID_TRAY_LOGOUT
                        }
                    }
                }
                return S_OK;
            }
        ).Get(),
        nullptr
    );

    // Allow self-signed / custom server certificates for the user's configured Prismateams server
    ComPtr<ICoreWebView2_14> webview14;
    if (SUCCEEDED(m_webview.As(&webview14)) && webview14) {
        webview14->add_ServerCertificateErrorDetected(
            Callback<ICoreWebView2ServerCertificateErrorDetectedEventHandler>(
                [this](ICoreWebView2* sender, ICoreWebView2ServerCertificateErrorDetectedEventArgs* args) -> HRESULT {
                    LPWSTR reqUriRaw = nullptr;
                    if (SUCCEEDED(args->get_RequestUri(&reqUriRaw)) && reqUriRaw) {
                        std::wstring reqUri = reqUriRaw;
                        CoTaskMemFree(reqUriRaw);
                        const std::wstring& srv = AuthManager::Instance().GetServerUrl();
                        if (!srv.empty() && reqUri.find(srv) == 0) {
                            args->put_Action(COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_ALWAYS_ALLOW);
                        }
                    }
                    return S_OK;
                }
            ).Get(),
            nullptr
        );
    }

    // Navigation failure / Offline fallback
    m_webview->add_NavigationCompleted(
        Callback<ICoreWebView2NavigationCompletedEventHandler>(
            [this](ICoreWebView2* sender, ICoreWebView2NavigationCompletedEventArgs* args) -> HRESULT {
                BOOL isSuccess = TRUE;
                args->get_IsSuccess(&isSuccess);
                if (!isSuccess) {
                    COREWEBVIEW2_WEB_ERROR_STATUS status;
                    args->get_WebErrorStatus(&status);
                    if (status == COREWEBVIEW2_WEB_ERROR_STATUS_OPERATION_CANCELED) {
                        return S_OK;
                    }
                    std::wstring offlineHtml = DesktopUI::BuildOfflineHtml(
                        AuthManager::Instance().GetServerUrl(),
                        SettingsManager::Instance().Get().themeMode,
                        App::Instance().IsDarkMode(),
                        static_cast<int>(status)
                    );
                    m_webview->NavigateToString(offlineHtml.c_str());
                }
                return S_OK;
            }
        ).Get(),
        nullptr
    );
}

void WebViewController::InjectNativeBridgeScript() {
    if (!m_webview) return;
    std::wstring bridgeJs = DesktopUI::GetDesktopBridgeScript();
    m_webview->AddScriptToExecuteOnDocumentCreated(bridgeJs.c_str(), nullptr);
}

void WebViewController::ShowLoginScreen() {
    if (!m_webview) return;
    const auto& s = SettingsManager::Instance().Get();
    std::wstring html = DesktopUI::BuildLoginScreenHtml(
        s.serverUrl,
        s.lastUserEmail,
        s.themeMode,
        App::Instance().IsDarkMode(),
        PasskeyAuthenticator::IsAvailable()
    );
    m_webview->NavigateToString(html.c_str());
}

static std::wstring ExtractWJsonStr(const std::wstring& json, const std::wstring& key) {
    std::wstring search = L"\"" + key + L"\"";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return L"";
    pos = json.find(L':', pos + search.length());
    if (pos == std::string::npos) return L"";
    pos = json.find(L'"', pos);
    if (pos == std::string::npos) return L"";
    size_t start = pos + 1;
    size_t end = start;
    while (end < json.length()) {
        if (json[end] == L'"' && json[end - 1] != L'\\') break;
        end++;
    }
    return (end <= json.length()) ? json.substr(start, end - start) : L"";
}

static bool ExtractWJsonBool(const std::wstring& json, const std::wstring& key, bool defVal) {
    std::wstring search = L"\"" + key + L"\"";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return defVal;
    pos = json.find(L':', pos + search.length());
    if (pos == std::string::npos) return defVal;
    size_t vs = json.find_first_not_of(L" \t\r\n", pos + 1);
    if (vs == std::string::npos) return defVal;
    if (json.compare(vs, 4, L"true") == 0) return true;
    if (json.compare(vs, 5, L"false") == 0) return false;
    return defVal;
}

static std::wstring EscapeWJson(const std::wstring& s) {
    std::wstring out;
    out.reserve(s.size() + 8);
    for (wchar_t c : s) {
        if (c == L'"') out += L"\\\"";
        else if (c == L'\\') out += L"\\\\";
        else if (c == L'\n') out += L"\\n";
        else if (c == L'\r') out += L"\\r";
        else out += c;
    }
    return out;
}

void WebViewController::PushStateSync() {
    if (!m_webview) return;
    const auto& s = SettingsManager::Instance().Get();
    bool mounted = WebDavManager::Instance().IsMounted();
    wchar_t letter = mounted ? WebDavManager::Instance().GetMountedDriveLetter() : s.driveLetter;

    std::wostringstream msg;
    msg << L"{\"type\":\"state_sync\","
        << L"\"mounted\":" << (mounted ? L"true" : L"false") << L","
        << L"\"driveLetter\":\"" << std::wstring(1, letter) << L"\","
        << L"\"serverUrl\":\"" << EscapeWJson(s.serverUrl) << L"\","
        << L"\"userEmail\":\"" << EscapeWJson(AuthManager::Instance().GetUserEmail()) << L"\","
        << L"\"userFullName\":\"" << EscapeWJson(AuthManager::Instance().GetUserFullName()) << L"\","
        << L"\"autoMountDrive\":" << (s.autoMountDrive ? L"true" : L"false") << L","
        << L"\"autoStartWithWindows\":" << (s.autoStartWithWindows ? L"true" : L"false") << L","
        << L"\"minimizeToTray\":" << (s.minimizeToTray ? L"true" : L"false") << L","
        << L"\"themeMode\":\"" << EscapeWJson(s.themeMode) << L"\"}";
    PostJsonMessage(msg.str());
}

void WebViewController::HandleWebMessage(const std::wstring& message) {
    std::wstring action = ExtractWJsonStr(message, L"action");

    if (action == L"start_drag") {
        ReleaseCapture();
        SendMessageW(m_hWndParent, WM_SYSCOMMAND, 0xF012 /* SC_MOVE | HTCAPTION */, 0);
    } else if (action == L"minimize") {
        ShowWindow(m_hWndParent, SW_MINIMIZE);
    } else if (action == L"toggle_maximize" || action == L"maximize") {
        ShowWindow(m_hWndParent, IsZoomed(m_hWndParent) ? SW_RESTORE : SW_MAXIMIZE);
    } else if (action == L"close") {
        SendMessageW(m_hWndParent, WM_CLOSE, 0, 0);
    } else if (action == L"nav_back") {
        GoBack();
    } else if (action == L"nav_forward") {
        GoForward();
    } else if (action == L"nav_reload") {
        Reload();
    } else if (action == L"nav_home") {
        Navigate(AuthManager::Instance().GetServerUrl() + L"/dashboard");
    } else if (action == L"get_state") {
        PushStateSync();
    } else if (action == L"sync_branding") {
        std::wstring portalName = ExtractWJsonStr(message, L"portalName");
        std::wstring logoDataUrl = ExtractWJsonStr(message, L"logoDataUrl");
        App::Instance().UpdatePortalBranding(portalName, logoDataUrl);
    } else if (action == L"set_theme") {
        std::wstring mode = ExtractWJsonStr(message, L"themeMode");
        if (!mode.empty()) {
            SettingsManager::Instance().Get().themeMode = mode;
            SettingsManager::Instance().Save();
            App::Instance().ApplyThemeMode(mode);
        }
    } else if (action == L"test_server") {
        std::wstring url = ExtractWJsonStr(message, L"serverUrl");
        while (!url.empty() && (url.back() == L'/' || url.back() == L' ')) url.pop_back();
        AuthManager::Instance().SetServerUrl(url);
        HWND hParent = m_hWndParent;
        std::thread([hParent]() {
            std::wstring title;
            bool ok = AuthManager::Instance().CheckServerReachable(title);
            auto* payload = new std::wstring(ok
                ? L"{\"type\":\"server_test_result\",\"success\":true}"
                : L"{\"type\":\"server_test_result\",\"success\":false,\"message\":\"Server nicht erreichbar.\"}");
            if (IsWindow(hParent)) {
                PostMessageW(hParent, WM_APP_POST_JSON, 0, reinterpret_cast<LPARAM>(payload));
            } else {
                delete payload;
            }
        }).detach();
    } else if (action == L"login_submit") {
        std::wstring url = ExtractWJsonStr(message, L"serverUrl");
        std::wstring email = ExtractWJsonStr(message, L"email");
        std::wstring pass = ExtractWJsonStr(message, L"password");
        std::wstring totp = ExtractWJsonStr(message, L"totp");
        while (!url.empty() && (url.back() == L'/' || url.back() == L' ')) url.pop_back();
        SettingsManager::Instance().Get().serverUrl = url;
        SettingsManager::Instance().Save();
        AuthManager::Instance().SetServerUrl(url);

        HWND hParent = m_hWndParent;
        std::thread([hParent, email, pass, totp]() {
            LoginResult res = AuthManager::Instance().Login(email, pass, totp);
            if (res.requires2FA) {
                auto* payload = new std::wstring(L"{\"type\":\"login_result\",\"success\":false,\"requires2FA\":true,\"message\":\"Zwei-Faktor-Code erforderlich.\"}");
                if (IsWindow(hParent)) PostMessageW(hParent, WM_APP_POST_JSON, 0, reinterpret_cast<LPARAM>(payload));
                else delete payload;
            } else if (res.success) {
                auto* payload = new std::wstring(L"{\"type\":\"login_result\",\"success\":true}");
                if (IsWindow(hParent)) {
                    PostMessageW(hParent, WM_APP_POST_JSON, 0, reinterpret_cast<LPARAM>(payload));
                    PostMessageW(hParent, WM_APP_LOGIN_SUCCESS, 0, 0);
                } else {
                    delete payload;
                }
            } else {
                auto* payload = new std::wstring(L"{\"type\":\"login_result\",\"success\":false,\"message\":\"" + EscapeWJson(res.errorMessage) + L"\"}");
                if (IsWindow(hParent)) PostMessageW(hParent, WM_APP_POST_JSON, 0, reinterpret_cast<LPARAM>(payload));
                else delete payload;
            }
        }).detach();
    } else if (action == L"passkey_login") {
        std::wstring url = ExtractWJsonStr(message, L"serverUrl");
        while (!url.empty() && (url.back() == L'/' || url.back() == L' ')) url.pop_back();
        SettingsManager::Instance().Get().serverUrl = url;
        SettingsManager::Instance().Save();
        AuthManager::Instance().SetServerUrl(url);

        LoginResult res = AuthManager::Instance().PasskeyLogin(m_hWndParent);
        if (res.success) {
            PostJsonMessage(L"{\"type\":\"login_result\",\"success\":true}");
            App::Instance().OnLoginSuccess();
        } else {
            PostJsonMessage(L"{\"type\":\"login_result\",\"success\":false,\"message\":\"" + EscapeWJson(res.errorMessage) + L"\"}");
        }
    } else if (action == L"save_settings") {
        auto& s = SettingsManager::Instance().Get();
        std::wstring url = ExtractWJsonStr(message, L"serverUrl");
        while (!url.empty() && (url.back() == L'/' || url.back() == L' ')) url.pop_back();
        if (!url.empty()) {
            s.serverUrl = url;
            AuthManager::Instance().SetServerUrl(url);
        }
        std::wstring dl = ExtractWJsonStr(message, L"driveLetter");
        if (!dl.empty() && dl[0] >= L'A' && dl[0] <= L'Z') s.driveLetter = dl[0];
        s.autoMountDrive = ExtractWJsonBool(message, L"autoMountDrive", s.autoMountDrive);
        s.autoStartWithWindows = ExtractWJsonBool(message, L"autoStartWithWindows", s.autoStartWithWindows);
        s.minimizeToTray = ExtractWJsonBool(message, L"minimizeToTray", s.minimizeToTray);
        std::wstring tm = ExtractWJsonStr(message, L"themeMode");
        if (!tm.empty()) {
            s.themeMode = tm;
            App::Instance().ApplyThemeMode(tm);
        }
        SettingsManager::Instance().Save();
        PushStateSync();
    } else if (action == L"open_settings") {
        PostJsonMessage(L"{\"type\":\"open_settings_modal\"}");
    } else if (action == L"mount_drive") {
        auto creds = AuthManager::Instance().FetchWebDavCredentials();
        if (creds.success) {
            wchar_t assigned = L'P';
            std::wstring err;
            bool ok = WebDavManager::Instance().MountDrive(
                AuthManager::Instance().GetServerUrl(),
                creds.username,
                creds.password,
                SettingsManager::Instance().Get().driveLetter,
                assigned,
                err
            );
            PushStateSync();
            if (ok) {
                App::Instance().ShowTrayNotification(L"Prismateams", L"Netzlaufwerk " + std::wstring(1, assigned) + L": erfolgreich verbunden.");
                WebDavManager::Instance().OpenInExplorer();
            } else {
                App::Instance().ShowTrayNotification(L"Netzlaufwerk", err.empty() ? L"Verbindung fehlgeschlagen." : err);
                MessageBoxW(m_hWndParent, err.c_str(), L"Netzlaufwerk-Fehler", MB_ICONERROR | MB_OK);
            }
        } else {
            App::Instance().ShowTrayNotification(L"WebDAV-Fehler", creds.errorMessage);
            MessageBoxW(m_hWndParent, creds.errorMessage.c_str(), L"WebDAV-Zugang", MB_ICONERROR | MB_OK);
        }
    } else if (action == L"unmount_drive") {
        WebDavManager::Instance().UnmountCurrentDrive(true);
        PushStateSync();
        App::Instance().ShowTrayNotification(L"Prismateams", L"Netzlaufwerk getrennt.");
    } else if (action == L"open_explorer") {
        if (!WebDavManager::Instance().IsMounted()) {
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
                PushStateSync();
            }
        }
        if (WebDavManager::Instance().IsMounted()) {
            WebDavManager::Instance().OpenInExplorer();
        } else {
            MessageBoxW(m_hWndParent, L"Netzlaufwerk konnte nicht automatisch eingebunden werden.", L"Prismateams", MB_ICONWARNING | MB_OK);
        }
    } else if (action == L"pick_live_edit_file") {
        wchar_t fileBuf[MAX_PATH] = { 0 };
        std::wstring initialDir = WebDavManager::Instance().IsMounted() ? WebDavManager::Instance().GetMountedDrivePath() : L"";
        OPENFILENAMEW ofn = { sizeof(OPENFILENAMEW) };
        ofn.hwndOwner = m_hWndParent;
        ofn.lpstrFilter = L"Office & Excalidraw (*.docx;*.xlsx;*.pptx;*.odt;*.ods;*.excalidraw)\0*.docx;*.doc;*.xlsx;*.xls;*.pptx;*.ppt;*.odt;*.ods;*.odp;*.excalidraw\0Alle Dateien (*.*)\0*.*\0";
        ofn.lpstrFile = fileBuf;
        ofn.nMaxFile = MAX_PATH;
        ofn.lpstrInitialDir = initialDir.empty() ? nullptr : initialDir.c_str();
        ofn.lpstrTitle = L"Datei direkt in Prismateams live bearbeiten";
        ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST;
        if (GetOpenFileNameW(&ofn)) {
            App::Instance().HandleFileOpen(fileBuf);
        }
    } else if (action == L"open_in_office") {
        std::wstring relPath = ExtractWJsonStr(message, L"path");
        if (!WebDavManager::Instance().IsMounted()) {
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
                PushStateSync();
            }
        }
        if (WebDavManager::Instance().IsMounted() && !relPath.empty()) {
            for (wchar_t& ch : relPath) {
                if (ch == L'/') ch = L'\\';
            }
            if (relPath.front() == L'\\') relPath = relPath.substr(1);
            std::wstring fullLocal = WebDavManager::Instance().GetMountedDrivePath() + relPath;
            ShellExecuteW(nullptr, L"open", fullLocal.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        }
    } else if (action == L"logout") {
        AuthManager::Instance().Logout();
        WebDavManager::Instance().UnmountCurrentDrive(true);
        ClearAllCookies();
        PostMessageW(m_hWndParent, WM_COMMAND, MAKEWPARAM(2006, 0), 0); // ID_TRAY_LOGOUT
    }
}

void WebViewController::Navigate(const std::wstring& url) {
    if (m_webview) {
        m_webview->Navigate(url.c_str());
    } else {
        m_pendingNavigateUrl = url;
    }
}

void WebViewController::SetVisible(bool visible) {
    m_isVisible = visible;
    if (m_controller) {
        m_controller->put_IsVisible(visible ? TRUE : FALSE);
    }
}

bool WebViewController::IsVisible() const {
    return m_isVisible;
}

void WebViewController::Resize(int width, int height) {
    if (m_controller) {
        RECT bounds = { 0, 0, width, height };
        m_controller->put_Bounds(bounds);
    }
}

void WebViewController::Reload() {
    if (m_webview) {
        m_webview->Reload();
    }
}

void WebViewController::GoBack() {
    if (m_webview) {
        m_webview->GoBack();
    }
}

void WebViewController::GoForward() {
    if (m_webview) {
        m_webview->GoForward();
    }
}

void WebViewController::SyncSessionCookie(const std::wstring& domain, const std::wstring& cookieHeader) {
    if (!m_webview || cookieHeader.empty()) return;

    std::wstring cleanDomain = domain;
    size_t schemePos = cleanDomain.find(L"://");
    if (schemePos != std::string::npos) {
        cleanDomain = cleanDomain.substr(schemePos + 3);
    }
    size_t colonPos = cleanDomain.find(L':');
    if (colonPos != std::string::npos) {
        cleanDomain = cleanDomain.substr(0, colonPos);
    }
    size_t slashPos = cleanDomain.find(L'/');
    if (slashPos != std::string::npos) {
        cleanDomain = cleanDomain.substr(0, slashPos);
    }

    // Host-only cookie (empty domain) matches Flask's Set-Cookie and prevents duplicate domain+host cookies
    cleanDomain = L"";

    // Use ICoreWebView2_2 or CookieManager if available
    ComPtr<ICoreWebView2_2> webview2;
    if (SUCCEEDED(m_webview.As(&webview2)) && webview2) {
        ComPtr<ICoreWebView2CookieManager> cookieManager;
        if (SUCCEEDED(webview2->get_CookieManager(&cookieManager)) && cookieManager) {
            // Parse session_token / session cookie
            size_t eqPos = cookieHeader.find(L'=');
            if (eqPos != std::string::npos) {
                std::wstring name = cookieHeader.substr(0, eqPos);
                size_t semiPos = cookieHeader.find(L';', eqPos);
                std::wstring val = (semiPos != std::string::npos) ?
                    cookieHeader.substr(eqPos + 1, semiPos - eqPos - 1) :
                    cookieHeader.substr(eqPos + 1);

                ComPtr<ICoreWebView2Cookie> cookie;
                if (SUCCEEDED(cookieManager->CreateCookie(name.c_str(), val.c_str(), cleanDomain.c_str(), L"/", &cookie)) && cookie) {
                    cookie->put_IsHttpOnly(TRUE);
                    cookieManager->AddOrUpdateCookie(cookie.Get());
                }
            }
        }
    }
}

void WebViewController::ClearAllCookies() {
    if (!m_webview) return;
    ComPtr<ICoreWebView2_2> webview2;
    if (SUCCEEDED(m_webview.As(&webview2)) && webview2) {
        ComPtr<ICoreWebView2CookieManager> cookieManager;
        if (SUCCEEDED(webview2->get_CookieManager(&cookieManager)) && cookieManager) {
            cookieManager->DeleteAllCookies();
        }
    }
}

void WebViewController::PostJsonMessage(const std::wstring& jsonMessage) {
    if (m_webview) {
        m_webview->PostWebMessageAsJson(jsonMessage.c_str());
    }
}

} // namespace Prismateams
