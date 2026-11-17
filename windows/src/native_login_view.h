#pragma once

#include <windows.h>
#include <string>
#include <functional>

namespace Prismateams {

class NativeLoginView {
public:
    NativeLoginView(HWND hWndParent, HINSTANCE hInstance);
    ~NativeLoginView();

    bool Create();
    void Show(bool visible);
    void Resize(int width, int height);
    void SetTheme(bool isDarkMode);

    void SetOnLoginSuccess(std::function<void()> callback) {
        m_onLoginSuccess = callback;
    }

    HWND GetHwnd() const { return m_hWnd; }
    void FocusNextControl(HWND current, bool reverse);
    void SetFocusedControl(HWND hwnd);

private:
    static LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);

    void RepositionControls();
    void PerformLogin();
    void PerformPasskeyLogin();
    void SetStatus(const std::wstring& message, bool isError);

    HWND m_hWndParent;
    HINSTANCE m_hInstance;
    HWND m_hWnd = nullptr;
    HWND m_focusedControl = nullptr;

    // Controls
    HWND m_editServer = nullptr;
    HWND m_editEmail = nullptr;
    HWND m_editPass = nullptr;
    HWND m_edit2Fa = nullptr;
    HWND m_btnLogin = nullptr;
    HWND m_btnPasskey = nullptr;
    HWND m_btnMin = nullptr;
    HWND m_btnClose = nullptr;
    HWND m_lblStatus = nullptr;

    bool m_isDarkMode = true;
    bool m_show2Fa = false;
    bool m_isLoading = false;
    std::wstring m_statusMessage = L"";
    bool m_statusIsError = false;

    // Modern GDI Brushes & Fonts
    HBRUSH m_hBrBg = nullptr;
    HBRUSH m_hBrCard = nullptr;
    HBRUSH m_hBrInput = nullptr;
    HBRUSH m_hBrBtnPrimary = nullptr;
    HBRUSH m_hBrBtnSecondary = nullptr;
    HPEN m_hPenCardBorder = nullptr;
    HPEN m_hPenInputBorder = nullptr;
    HPEN m_hPenInputFocus = nullptr;
    HFONT m_hFontTitle = nullptr;
    HFONT m_hFontSub = nullptr;
    HFONT m_hFontBody = nullptr;
    HFONT m_hFontBold = nullptr;

    std::function<void()> m_onLoginSuccess;
};

} // namespace Prismateams
