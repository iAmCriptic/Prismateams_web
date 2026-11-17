#include <windows.h>
#include <commctrl.h>
#include <string>
#include "app.h"

#pragma comment(lib, "comctl32.lib")

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPWSTR lpCmdLine, int nCmdShow) {
    // Single instance mutex
    HANDLE hMutex = CreateMutexW(nullptr, TRUE, L"Local\\Prismateams_SingleInstance_Mutex");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        // App is already running
        HWND hExisting = FindWindowW(L"Prismateams_MainWindow_Class", nullptr);
        if (hExisting) {
            std::wstring cmd = lpCmdLine ? lpCmdLine : L"";
            if (!cmd.empty()) {
                // Strip quotes if wrapped
                if (cmd.front() == L'"' && cmd.back() == L'"' && cmd.length() >= 2) {
                    cmd = cmd.substr(1, cmd.length() - 2);
                }

                COPYDATASTRUCT cds;
                cds.dwData = 1;
                cds.cbData = static_cast<DWORD>((cmd.length() + 1) * sizeof(wchar_t));
                cds.lpData = const_cast<wchar_t*>(cmd.c_str());

                SendMessageW(hExisting, WM_COPYDATA, 0, reinterpret_cast<LPARAM>(&cds));
            }

            ShowWindow(hExisting, SW_RESTORE);
            SetForegroundWindow(hExisting);
        }

        if (hMutex) CloseHandle(hMutex);
        return 0;
    }

    // Initialize COM for WebView2 and Shell APIs
    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);

    // Initialize Common Controls
    INITCOMMONCONTROLSEX icex;
    icex.dwSize = sizeof(INITCOMMONCONTROLSEX);
    icex.dwICC = ICC_WIN95_CLASSES | ICC_STANDARD_CLASSES;
    InitCommonControlsEx(&icex);

    std::wstring cmdLine = lpCmdLine ? lpCmdLine : L"";
    int result = Prismateams::App::Instance().Run(hInstance, cmdLine, nCmdShow);

    if (SUCCEEDED(hr)) {
        CoUninitialize();
    }

    if (hMutex) {
        ReleaseMutex(hMutex);
        CloseHandle(hMutex);
    }

    return result;
}
