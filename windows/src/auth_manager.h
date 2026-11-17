#pragma once

#include <string>
#include <vector>
#include <functional>
#include <windows.h>

namespace Prismateams {

struct LoginResult {
    bool success = false;
    bool requires2FA = false;
    std::wstring errorMessage = L"";
    std::wstring token = L"";
    std::wstring sessionCookie = L"";
    std::wstring userFullName = L"";
    std::wstring userEmail = L"";
    bool isAdmin = false;
};

struct WebDavCredentialsResult {
    bool success = false;
    std::wstring username = L"";
    std::wstring password = L"";
    std::wstring errorMessage = L"";
};

class AuthManager {
public:
    static AuthManager& Instance();

    void SetServerUrl(const std::wstring& url);
    const std::wstring& GetServerUrl() const { return m_serverUrl; }

    bool CheckServerReachable(std::wstring& outServerTitle);

    LoginResult Login(const std::wstring& email, const std::wstring& password, const std::wstring& totpCode = L"");
    bool VerifyStoredSession();
    WebDavCredentialsResult FetchWebDavCredentials();
    bool Logout();

    bool IsAuthenticated() const { return m_isAuthenticated; }
    const std::wstring& GetSessionCookie() const { return m_sessionCookie; }
    const std::wstring& GetAuthToken() const { return m_authToken; }
    const std::wstring& GetUserFullName() const { return m_userFullName; }
    const std::wstring& GetUserEmail() const { return m_userEmail; }

private:
    AuthManager() = default;

    bool SendHttpRequest(
        const std::wstring& verb,
        const std::wstring& path,
        const std::string& jsonBody,
        const std::wstring& additionalHeaders,
        std::string& outResponseBody,
        std::wstring& outSetCookieHeader,
        DWORD& outStatusCode
    );

    std::wstring m_serverUrl = L"https://localhost:5000";
    std::wstring m_authToken = L"";
    std::wstring m_sessionCookie = L"";
    std::wstring m_userFullName = L"";
    std::wstring m_userEmail = L"";
    bool m_isAuthenticated = false;
    bool m_isAdmin = false;
};

} // namespace Prismateams
