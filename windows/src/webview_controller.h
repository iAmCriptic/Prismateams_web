#pragma once

#include <windows.h>
#include <wrl.h>
#include <string>
#include <functional>
#include <vector>

#include "../packages/Microsoft.Web.WebView2/build/native/include/WebView2.h"

namespace Prismateams {

class WebViewController {
public:
    WebViewController(HWND hWndParent);
    ~WebViewController();

    void Initialize(std::function<void(bool success)> onComplete);
    void Navigate(const std::wstring& url);
    void Resize(int width, int height);
    void Reload();
    void GoBack();
    void GoForward();

    void SetVisible(bool visible);
    bool IsVisible() const;

    void SyncSessionCookie(const std::wstring& domain, const std::wstring& cookieHeader);
    void ClearAllCookies();
    void PostJsonMessage(const std::wstring& jsonMessage);

    bool IsInitialized() const { return m_isInitialized; }
    HWND GetParentHwnd() const { return m_hWndParent; }

private:
    void SetupEventHandlers();
    void InjectNativeBridgeScript();
    void HandleWebMessage(const std::wstring& message);

    HWND m_hWndParent;
    bool m_isInitialized = false;
    bool m_isVisible = false;
    std::wstring m_pendingNavigateUrl;

    Microsoft::WRL::ComPtr<ICoreWebView2Environment> m_environment;
    Microsoft::WRL::ComPtr<ICoreWebView2Controller> m_controller;
    Microsoft::WRL::ComPtr<ICoreWebView2> m_webview;
};

} // namespace Prismateams
