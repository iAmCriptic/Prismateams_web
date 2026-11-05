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
                            m_controller->put_IsVisible(TRUE);

                            SetupEventHandlers();
                            InjectNativeBridgeScript();

                            m_isInitialized = true;
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

    // JavaScript bridge available on all pages
    const wchar_t* bridgeJs =
        L"window.prismateamsNative = {"
        L"  isDesktopApp: true,"
        L"  version: '1.0.0',"
        L"  mountDrive: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'mount_drive'})); },"
        L"  openExplorer: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_explorer'})); },"
        L"  isMounted: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'check_mount'})); },"
        L"  logout: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'logout'})); }"
        L"};"
        L"document.dispatchEvent(new CustomEvent('prismateams-native-ready', { detail: window.prismateamsNative }));";

    m_webview->AddScriptToExecuteOnDocumentCreated(bridgeJs, nullptr);
}

void WebViewController::HandleWebMessage(const std::wstring& message) {
    if (message.find(L"\"mount_drive\"") != std::string::npos) {
        // Fetch credentials and mount drive
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
    }
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
                if (SUCCEEDED(cookieManager->CreateCookie(name.c_str(), val.c_str(), domain.c_str(), L"/", &cookie)) && cookie) {
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
