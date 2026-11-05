#include "webdav_manager.h"
#include <winnetwk.h>
#include <winsvc.h>
#include <winhttp.h>
#include <shellapi.h>
#include <sstream>

#pragma comment(lib, "mpr.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "shell32.lib")

namespace Prismateams {

WebDavManager& WebDavManager::Instance() {
    static WebDavManager instance;
    return instance;
}

bool WebDavManager::EnsureWebClientServiceRunning() {
    SC_HANDLE hSCM = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT);
    if (!hSCM) return false;

    SC_HANDLE hService = OpenServiceW(hSCM, L"WebClient", SERVICE_QUERY_STATUS | SERVICE_START);
    if (!hService) {
        CloseServiceHandle(hSCM);
        return false;
    }

    SERVICE_STATUS_PROCESS ssp;
    DWORD bytesNeeded = 0;
    bool isRunning = false;

    if (QueryServiceStatusEx(hService, SC_STATUS_PROCESS_INFO, reinterpret_cast<LPBYTE>(&ssp), sizeof(ssp), &bytesNeeded)) {
        if (ssp.dwCurrentState == SERVICE_RUNNING) {
            isRunning = true;
        } else if (ssp.dwCurrentState == SERVICE_STOPPED || ssp.dwCurrentState == SERVICE_STOP_PENDING) {
            if (StartServiceW(hService, 0, nullptr)) {
                // Wait briefly for startup
                for (int i = 0; i < 20; ++i) {
                    Sleep(250);
                    if (QueryServiceStatusEx(hService, SC_STATUS_PROCESS_INFO, reinterpret_cast<LPBYTE>(&ssp), sizeof(ssp), &bytesNeeded)) {
                        if (ssp.dwCurrentState == SERVICE_RUNNING) {
                            isRunning = true;
                            break;
                        }
                    }
                }
            }
        }
    }

    CloseServiceHandle(hService);
    CloseServiceHandle(hSCM);
    return isRunning;
}

bool WebDavManager::IsDriveLetterInUse(wchar_t letter) {
    DWORD drives = GetLogicalDrives();
    int bitIndex = towupper(letter) - L'A';
    if (bitIndex < 0 || bitIndex >= 26) return true;
    return (drives & (1 << bitIndex)) != 0;
}

wchar_t WebDavManager::FindAvailableDriveLetter(wchar_t preferred) {
    preferred = towupper(preferred);
    if (preferred >= L'A' && preferred <= L'Z' && !IsDriveLetterInUse(preferred)) {
        return preferred;
    }

    // Try fallback sequence: P, Q, R, S, T, U, V, W, X, Y, Z, O, N, M...
    const wchar_t fallbacks[] = L"PQRSTUVWXYZONMLKJHGFEDCBA";
    for (size_t i = 0; i < wcslen(fallbacks); ++i) {
        wchar_t candidate = fallbacks[i];
        if (!IsDriveLetterInUse(candidate)) {
            return candidate;
        }
    }

    return L'\0';
}

std::wstring WebDavManager::FormatWebDavUncPath(const std::wstring& serverUrl) {
    URL_COMPONENTS urlComp = { sizeof(URL_COMPONENTS) };
    wchar_t hostName[256] = { 0 };
    wchar_t urlPath[1024] = { 0 };

    urlComp.lpszHostName = hostName;
    urlComp.dwHostNameLength = 256;
    urlComp.lpszUrlPath = urlPath;
    urlComp.dwUrlPathLength = 1024;

    if (!WinHttpCrackUrl(serverUrl.c_str(), static_cast<DWORD>(serverUrl.length()), 0, &urlComp)) {
        return L"";
    }

    bool isHttps = (urlComp.nScheme == INTERNET_SCHEME_HTTPS);
    int port = urlComp.nPort;

    std::wstring unc = L"\\\\";
    unc += hostName;

    if (isHttps) {
        unc += L"@SSL";
        if (port != 443) {
            unc += L"@" + std::to_wstring(port);
        }
    } else {
        if (port != 80) {
            unc += L"@" + std::to_wstring(port);
        }
    }

    unc += L"\\webdav";
    return unc;
}

bool WebDavManager::MountDrive(
    const std::wstring& serverUrl,
    const std::wstring& username,
    const std::wstring& password,
    wchar_t preferredLetter,
    wchar_t& outAssignedLetter,
    std::wstring& outErrorMessage
) {
    EnsureWebClientServiceRunning();

    outAssignedLetter = FindAvailableDriveLetter(preferredLetter);
    if (outAssignedLetter == L'\0') {
        outErrorMessage = L"Kein freier Laufwerksbuchstabe auf dem System verfügbar.";
        return false;
    }

    std::wstring localName = std::wstring(1, outAssignedLetter) + L":";
    std::wstring remoteUnc = FormatWebDavUncPath(serverUrl);
    if (remoteUnc.empty()) {
        outErrorMessage = L"Ungültige Server-URL.";
        return false;
    }

    // Try unmounting if old connection lingers on this letter
    UnmountDrive(outAssignedLetter, true);

    NETRESOURCEW nr = { 0 };
    nr.dwType = RESOURCETYPE_DISK;
    nr.lpLocalName = const_cast<LPWSTR>(localName.c_str());
    nr.lpRemoteName = const_cast<LPWSTR>(remoteUnc.c_str());
    nr.lpProvider = nullptr;

    DWORD res = WNetAddConnection2W(
        &nr,
        password.empty() ? nullptr : password.c_str(),
        username.empty() ? nullptr : username.c_str(),
        CONNECT_TEMPORARY
    );

    // If UNC format failed, attempt direct HTTP URL format (supported by modern Windows WebClient)
    if (res != NO_ERROR) {
        std::wstring directUrl = serverUrl;
        while (!directUrl.empty() && directUrl.back() == L'/') directUrl.pop_back();
        directUrl += L"/webdav";

        nr.lpRemoteName = const_cast<LPWSTR>(directUrl.c_str());
        res = WNetAddConnection2W(
            &nr,
            password.empty() ? nullptr : password.c_str(),
            username.empty() ? nullptr : username.c_str(),
            CONNECT_TEMPORARY
        );
    }

    if (res == NO_ERROR) {
        m_isMounted = true;
        m_mountedLetter = outAssignedLetter;
        m_uncPath = remoteUnc;
        return true;
    }

    // Map error codes
    switch (res) {
        case ERROR_ACCESS_DENIED:
        case ERROR_LOGON_FAILURE:
            outErrorMessage = L"Zugriff verweigert. WebDAV-Zugangsdaten ungültig.";
            break;
        case ERROR_BAD_NET_NAME:
            outErrorMessage = L"WebDAV-Server nicht erreichbar oder WebClient-Dienst nicht gestartet.";
            break;
        case ERROR_ALREADY_ASSIGNED:
            outErrorMessage = L"Laufwerksbuchstabe wird bereits verwendet.";
            break;
        default:
            outErrorMessage = L"Netzlaufwerk-Fehler Code: " + std::to_wstring(res);
            break;
    }

    return false;
}

bool WebDavManager::UnmountDrive(wchar_t driveLetter, bool force) {
    std::wstring localName = std::wstring(1, driveLetter) + L":";
    DWORD res = WNetCancelConnection2W(localName.c_str(), 0, force ? TRUE : FALSE);
    return (res == NO_ERROR || res == ERROR_NOT_CONNECTED);
}

bool WebDavManager::UnmountCurrentDrive(bool force) {
    if (!m_isMounted) return true;
    bool ok = UnmountDrive(m_mountedLetter, force);
    if (ok) {
        m_isMounted = false;
    }
    return ok;
}

std::wstring WebDavManager::GetMountedDrivePath() const {
    if (!m_isMounted) return L"";
    return std::wstring(1, m_mountedLetter) + L":\\";
}

bool WebDavManager::OpenInExplorer() {
    if (!m_isMounted) return false;
    std::wstring path = GetMountedDrivePath();
    HINSTANCE hInst = ShellExecuteW(nullptr, L"open", path.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
    return (reinterpret_cast<INT_PTR>(hInst) > 32);
}

} // namespace Prismateams
