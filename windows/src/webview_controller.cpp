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

    // Navigation failure / Offline fallback
    m_webview->add_NavigationCompleted(
        Callback<ICoreWebView2NavigationCompletedEventHandler>(
            [this](ICoreWebView2* sender, ICoreWebView2NavigationCompletedEventArgs* args) -> HRESULT {
                BOOL isSuccess = TRUE;
                args->get_IsSuccess(&isSuccess);
                if (!isSuccess) {
                    COREWEBVIEW2_WEB_ERROR_STATUS status;
                    args->get_WebErrorStatus(&status);
                    std::wstring offlineHtml =
                        L"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                        L"<style>"
                        L"body { background: #0f172a; color: #f8fafc; font-family: 'Segoe UI', system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }"
                        L".card { background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 36px 40px; text-align: center; max-width: 440px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }"
                        L"h2 { margin: 14px 0 8px; font-size: 20px; font-weight: 600; }"
                        L"p { color: #94a3b8; font-size: 14px; margin-bottom: 24px; line-height: 1.5; }"
                        L".btn { display: inline-flex; align-items: center; justify-content: center; width: 100%; height: 38px; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; border: none; margin-bottom: 10px; text-decoration: none; }"
                        L".btn-primary { background: #3b82f6; color: #fff; }"
                        L".btn-secondary { background: #334155; color: #e2e8f0; }"
                        L".btn-danger { background: transparent; color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }"
                        L"</style></head><body>"
                        L"<div class='card'>"
                        L"<svg width='48' height='48' viewBox='0 0 24 24' fill='none' stroke='#f59e0b' stroke-width='2'><path d='M1 1l22 22M16.72 11.06A10.94 10.94 0 0 1 19 12.55M5 12.55a10.94 10.94 0 0 1 5.17-2.39M10.71 5.05A16 16 0 0 1 22.58 9M1.42 9a15.91 15.91 0 0 1 4.7-2.88M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01'/></svg>"
                        L"<h2>Verbindung nicht m\xF6glich</h2>"
                        L"<p>Der Server ist nicht erreichbar oder es besteht keine Internetverbindung.<br><small style='color:#64748b;'>" + AuthManager::Instance().GetServerUrl() + L"</small></p>"
                        L"<button class='btn btn-primary' onclick='location.reload()'>Erneut versuchen</button>"
                        L"<button class='btn btn-secondary' onclick='window.prismateamsNative.openSettings()'>Einstellungen</button>"
                        L"<button class='btn btn-danger' onclick='window.prismateamsNative.logout()'>Server wechseln / Abmelden</button>"
                        L"</div></body></html>";
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
        L"  function ensureDragRegionStyle() {"
        L"    if (document.getElementById('ptDragRegionStyle')) return;"
        L"    var st = document.createElement('style');"
        L"    st.id = 'ptDragRegionStyle';"
        L"    st.textContent = '.top-navbar, #desktopTopNav { -webkit-app-region: drag !important; app-region: drag !important; }' +"
        L"                     '.top-navbar-actions, button, a, input, select, textarea, .top-navbar-icon-btn, .dropdown-menu, .account-popup, .module-launcher-panel { -webkit-app-region: no-drag !important; app-region: no-drag !important; }';"
        L"    (document.head || document.documentElement).appendChild(st);"
        L"  }"
        L"  function onMouseDown(e) {"
        L"    if (e.button !== 0) return;"
        L"    var el = e.target;"
        L"    if (!el) return;"
        L"    if (el.closest('.pt-desktop-win-controls, button, a, input, select, textarea, .top-navbar-icon-btn, .dropdown-menu, .account-popup, .module-launcher, .modal')) return;"
        L"    var nav = el.closest('.top-navbar, #desktopTopNav, .navbar, nav, header');"
        L"    var isTopArea = e.clientY <= 52;"
        L"    if (nav || isTopArea) {"
        L"      window.chrome.webview.postMessage(JSON.stringify({action: 'start_drag'}));"
        L"    }"
        L"  }"
        L"  function onDblClick(e) {"
        L"    if (e.button !== 0) return;"
        L"    var el = e.target;"
        L"    if (!el) return;"
        L"    if (el.closest('.pt-desktop-win-controls, button, a, input, select, textarea, .top-navbar-icon-btn, .dropdown-menu, .account-popup, .module-launcher, .modal')) return;"
        L"    var nav = el.closest('.top-navbar, #desktopTopNav, .navbar, nav, header');"
        L"    var isTopArea = e.clientY <= 52;"
        L"    if (nav || isTopArea) {"
        L"      window.chrome.webview.postMessage(JSON.stringify({action: 'toggle_maximize'}));"
        L"    }"
        L"  }"
        L"  function ensureWindowControls() {"
        L"    var host = document.querySelector('.top-navbar-actions') || document.querySelector('#desktopTopNav');"
        L"    if (!host || document.getElementById('ptDesktopWinControls')) return;"
        L"    var container = document.createElement('div');"
        L"    container.id = 'ptDesktopWinControls';"
        L"    container.className = 'pt-desktop-win-controls';"
        L"    container.style.display = 'inline-flex';"
        L"    container.style.alignItems = 'center';"
        L"    container.style.marginLeft = '12px';"
        L"    container.style.gap = '2px';"
        L"    container.style.height = '100%';"
        L"    container.style.userSelect = 'none';"
        L"    var btnBase = 'display:inline-flex;align-items:center;justify-content:center;width:38px;height:32px;border:none;background:transparent;color:inherit;font-size:12px;cursor:pointer;opacity:0.85;border-radius:4px;padding:0;';"
        L"    var btnMin = document.createElement('button');"
        L"    btnMin.type = 'button';"
        L"    btnMin.title = 'Minimieren';"
        L"    btnMin.style.cssText = btnBase;"
        L"    btnMin.innerHTML = '<svg width=\"10\" height=\"2\" viewBox=\"0 0 10 2\"><rect width=\"10\" height=\"2\" fill=\"currentColor\"/></svg>';"
        L"    btnMin.onmouseenter = function() { btnMin.style.backgroundColor = 'rgba(255,255,255,0.12)'; btnMin.style.opacity = '1'; };"
        L"    btnMin.onmouseleave = function() { btnMin.style.backgroundColor = 'transparent'; btnMin.style.opacity = '0.85'; };"
        L"    btnMin.onclick = function(e) { e.preventDefault(); e.stopPropagation(); window.prismateamsNative.minimize(); };"
        L"    var btnMax = document.createElement('button');"
        L"    btnMax.type = 'button';"
        L"    btnMax.title = 'Maximieren / Wiederherstellen';"
        L"    btnMax.style.cssText = btnBase;"
        L"    btnMax.innerHTML = '<svg width=\"10\" height=\"10\" viewBox=\"0 0 10 10\"><rect x=\"1\" y=\"1\" width=\"8\" height=\"8\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\"/></svg>';"
        L"    btnMax.onmouseenter = function() { btnMax.style.backgroundColor = 'rgba(255,255,255,0.12)'; btnMax.style.opacity = '1'; };"
        L"    btnMax.onmouseleave = function() { btnMax.style.backgroundColor = 'transparent'; btnMax.style.opacity = '0.85'; };"
        L"    btnMax.onclick = function(e) { e.preventDefault(); e.stopPropagation(); window.prismateamsNative.maximize(); };"
        L"    var btnClose = document.createElement('button');"
        L"    btnClose.type = 'button';"
        L"    btnClose.title = 'Schlie\\u00dfen';"
        L"    btnClose.style.cssText = btnBase;"
        L"    btnClose.innerHTML = '<svg width=\"10\" height=\"10\" viewBox=\"0 0 10 10\"><path d=\"M1 1 L9 9 M9 1 L1 9\" stroke=\"currentColor\" stroke-width=\"1.4\"/></svg>';"
        L"    btnClose.onmouseenter = function() { btnClose.style.backgroundColor = '#e11d48'; btnClose.style.color = '#fff'; btnClose.style.opacity = '1'; };"
        L"    btnClose.onmouseleave = function() { btnClose.style.backgroundColor = 'transparent'; btnClose.style.color = 'inherit'; btnClose.style.opacity = '0.85'; };"
        L"    btnClose.onclick = function(e) { e.preventDefault(); e.stopPropagation(); window.prismateamsNative.close(); };"
        L"    container.appendChild(btnMin);"
        L"    container.appendChild(btnMax);"
        L"    container.appendChild(btnClose);"
        L"    host.appendChild(container);"
        L"  }"
        L"  function ensureSettingsIntegration() {"
        L"    var oldPill = document.getElementById('ptDesktopSettingsCard');"
        L"    if (oldPill) oldPill.remove();"
        L"    var oldLinks = document.getElementById('ptDesktopAccountLinks');"
        L"    if (oldLinks) oldLinks.remove();"
        L"    var actionsList = document.querySelector('#accountPopup .account-popup-actions, .account-popup .account-popup-actions');"
        L"    if (actionsList && !document.getElementById('ptDesktopActionSettings')) {"
        L"      var itemSettings = document.createElement('button');"
        L"      itemSettings.type = 'button';"
        L"      itemSettings.id = 'ptDesktopActionSettings';"
        L"      itemSettings.className = 'account-popup-action';"
        L"      itemSettings.innerHTML = '<i class=\"bi bi-laptop\" aria-hidden=\"true\"></i><span>Desktop-Einstellungen</span>';"
        L"      itemSettings.onclick = function(e) { e.preventDefault(); e.stopPropagation(); window.prismateamsNative.openSettings(); };"
        L"      var itemExplorer = document.createElement('button');"
        L"      itemExplorer.type = 'button';"
        L"      itemExplorer.id = 'ptDesktopActionExplorer';"
        L"      itemExplorer.className = 'account-popup-action';"
        L"      itemExplorer.innerHTML = '<i class=\"bi bi-folder2-open\" aria-hidden=\"true\"></i><span>Netzlaufwerk (P:)</span>';"
        L"      itemExplorer.onclick = function(e) { e.preventDefault(); e.stopPropagation(); window.prismateamsNative.openExplorer(); };"
        L"      var logoutForm = actionsList.querySelector('form');"
        L"      if (logoutForm) {"
        L"        actionsList.insertBefore(itemSettings, logoutForm);"
        L"        actionsList.insertBefore(itemExplorer, logoutForm);"
        L"      } else {"
        L"        actionsList.appendChild(itemSettings);"
        L"        actionsList.appendChild(itemExplorer);"
        L"      }"
        L"    }"
        L"    if (window.location.pathname.indexOf('/settings') !== -1) {"
        L"      var accountGrid = document.querySelector('section[aria-labelledby=\"hub-account\"] .sp-hub-grid') ||"
        L"                        document.querySelector('.sp-hub-section .sp-hub-grid');"
        L"      if (accountGrid && !document.getElementById('ptDesktopTileApp')) {"
        L"        var tileApp = document.createElement('a');"
        L"        tileApp.id = 'ptDesktopTileApp';"
        L"        tileApp.href = '#';"
        L"        tileApp.className = 'sp-hub-tile';"
        L"        tileApp.innerHTML = '<span class=\"sp-hub-tile-icon\"><i class=\"bi bi-laptop\" aria-hidden=\"true\"></i></span>' +"
        L"                            '<span class=\"sp-hub-tile-body\">' +"
        L"                            '  <span class=\"sp-hub-tile-title\">Desktop-App</span>' +"
        L"                            '  <span class=\"sp-hub-tile-desc\">App-Optionen, Autostart &amp; Server</span>' +"
        L"                            '</span>' +"
        L"                            '<i class=\"bi bi-chevron-right sp-hub-tile-arrow\" aria-hidden=\"true\"></i>';"
        L"        tileApp.onclick = function(e) { e.preventDefault(); window.prismateamsNative.openSettings(); };"
        L"        var tileDrive = document.createElement('a');"
        L"        tileDrive.id = 'ptDesktopTileDrive';"
        L"        tileDrive.href = '#';"
        L"        tileDrive.className = 'sp-hub-tile';"
        L"        tileDrive.innerHTML = '<span class=\"sp-hub-tile-icon\"><i class=\"bi bi-folder2-open\" aria-hidden=\"true\"></i></span>' +"
        L"                              '<span class=\"sp-hub-tile-body\">' +"
        L"                              '  <span class=\"sp-hub-tile-title\">Netzlaufwerk</span>' +"
        L"                              '  <span class=\"sp-hub-tile-desc\">WebDAV (P:) verbinden &amp; Explorer</span>' +"
        L"                              '</span>' +"
        L"                              '<i class=\"bi bi-chevron-right sp-hub-tile-arrow\" aria-hidden=\"true\"></i>';"
        L"        tileDrive.onclick = function(e) { e.preventDefault(); window.prismateamsNative.openSettings(); };"
        L"        accountGrid.appendChild(tileApp);"
        L"        accountGrid.appendChild(tileDrive);"
        L"      }"
        L"    }"
        L"  }"
        L"  function initAll() {"
        L"    ensureDragRegionStyle();"
        L"    ensureWindowControls();"
        L"    ensureSettingsIntegration();"
        L"  }"
        L"  if (document.readyState === 'loading') {"
        L"    document.addEventListener('DOMContentLoaded', initAll);"
        L"  } else {"
        L"    initAll();"
        L"  }"
        L"  var obs = new MutationObserver(initAll);"
        L"  obs.observe(document.documentElement, { childList: true, subtree: true });"
        L"  window.addEventListener('mousedown', onMouseDown, true);"
        L"  window.addEventListener('dblclick', onDblClick, true);"
        L"})();";

    m_webview->AddScriptToExecuteOnDocumentCreated(bridgeJs, nullptr);
}

void WebViewController::HandleWebMessage(const std::wstring& message) {
    if (message.find(L"\"start_drag\"") != std::string::npos) {
        ReleaseCapture();
        SendMessageW(m_hWndParent, WM_SYSCOMMAND, 0xF012 /* SC_MOVE | HTCAPTION */, 0);
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
