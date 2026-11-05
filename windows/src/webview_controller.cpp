#include "webview_controller.h"
#include "settings.h"
#include "webdav_manager.h"
#include "auth_manager.h"

#include <shellapi.h>
#include <sstream>
#include <wrl/client.h>
#include <wrl/event.h>

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
}

void WebViewController::InjectNativeBridgeScript() {
    if (!m_webview) return;

    // JavaScript bridge with drag region & window control handling
    const wchar_t* bridgeJs =
        L"(function() {"
        L"  window.prismateamsNative = {"
        L"    isDesktopApp: true,"
        L"    version: '1.0.0',"
        L"    startDrag: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'start_drag'})); },"
        L"    minimize: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'minimize'})); },"
        L"    maximize: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'toggle_maximize'})); },"
        L"    close: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'close'})); },"
        L"    openSettings: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_settings'})); },"
        L"    mountDrive: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'mount_drive'})); },"
        L"    openExplorer: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_explorer'})); },"
        L"    isMounted: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'check_mount'})); },"
        L"    logout: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'logout'})); }"
        L"  };"
        L"  document.dispatchEvent(new CustomEvent('prismateams-native-ready', { detail: window.prismateamsNative }));"
        L"  function onMouseDown(e) {"
        L"    if (e.button !== 0) return;"
        L"    var el = e.target;"
        L"    if (!el) return;"
        L"    var interactive = el.closest('button, a, input, select, textarea, [role=\"button\"], [contenteditable=\"true\"], .top-navbar-icon-btn, .btn, .dropdown-menu, .modal');"
        L"    if (interactive) return;"
        L"    var nav = el.closest('.top-navbar, .navbar, nav, header, [data-drag-region], [data-tauri-drag-region]');"
        L"    var isTopArea = e.clientY <= 56;"
        L"    if (nav || isTopArea) {"
        L"      window.chrome.webview.postMessage(JSON.stringify({action: 'start_drag'}));"
        L"    }"
        L"  }"
        L"  function onDblClick(e) {"
        L"    if (e.button !== 0) return;"
        L"    var el = e.target;"
        L"    if (!el) return;"
        L"    var interactive = el.closest('button, a, input, select, textarea, [role=\"button\"], .top-navbar-icon-btn, .btn');"
        L"    if (interactive) return;"
        L"    var nav = el.closest('.top-navbar, .navbar, nav, header, [data-drag-region], [data-tauri-drag-region]');"
        L"    var isTopArea = e.clientY <= 56;"
        L"    if (nav || isTopArea) {"
        L"      window.chrome.webview.postMessage(JSON.stringify({action: 'toggle_maximize'}));"
        L"    }"
        L"  }"
        L"  window.addEventListener('mousedown', onMouseDown, true);"
        L"  window.addEventListener('dblclick', onDblClick, true);"
        L"})();";

    m_webview->AddScriptToExecuteOnDocumentCreated(bridgeJs, nullptr);
}

void WebViewController::HandleWebMessage(const std::wstring& message) {
    if (message.find(L"\"start_drag\"") != std::string::npos) {
        ReleaseCapture();
        SendMessageW(m_hWndParent, WM_NCLBUTTONDOWN, HTCAPTION, 0);
    } else if (message.find(L"\"minimize\"") != std::string::npos) {
        ShowWindow(m_hWndParent, SW_MINIMIZE);
    } else if (message.find(L"\"toggle_maximize\"") != std::string::npos || message.find(L"\"maximize\"") != std::string::npos) {
        if (IsZoomed(m_hWndParent)) {
            ShowWindow(m_hWndParent, SW_RESTORE);
        } else {
            ShowWindow(m_hWndParent, SW_MAXIMIZE);
        }
    } else if (message.find(L"\"close\"") != std::string::npos) {
        SendMessageW(m_hWndParent, WM_CLOSE, 0, 0);
    } else if (message.find(L"\"open_settings\"") != std::string::npos) {
        PostMessageW(m_hWndParent, WM_COMMAND, MAKEWPARAM(1002, 0), 0); // ID_NAV_SETTINGS
    } else if (message.find(L"\"logged_in\"") != std::string::npos) {
        PostMessageW(m_hWndParent, WM_COMMAND, MAKEWPARAM(2050, 0), 0); // ID_CMD_USER_LOGGED_IN
    } else if (message.find(L"\"mount_drive\"") != std::string::npos) {
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
            if (WebDavManager::Instance().IsMounted()) {
                WebDavManager::Instance().OpenInExplorer();
            }
        }
    } else if (message.find(L"\"open_explorer\"") != std::string::npos) {
        WebDavManager::Instance().OpenInExplorer();
    } else if (message.find(L"\"logout\"") != std::string::npos) {
        AuthManager::Instance().Logout();
        WebDavManager::Instance().UnmountCurrentDrive(true);
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

    // RFC 6265: for localhost or IP addresses, domain MUST be empty for host-only cookies in Chromium!
    if (cleanDomain == L"localhost" || cleanDomain == L"127.0.0.1") {
        cleanDomain = L"";
    }

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

void WebViewController::PostJsonMessage(const std::wstring& jsonMessage) {
    if (m_webview) {
        m_webview->PostWebMessageAsJson(jsonMessage.c_str());
    }
}

} // namespace Prismateams
