#include "auth_manager.h"
#include "credential_vault.h"
#include "settings.h"
#include "passkey_authenticator.h"

#include <winhttp.h>
#include <sstream>
#include <algorithm>
#include <regex>

#pragma comment(lib, "winhttp.lib")

namespace Prismateams {

// Helper: UTF-8 <-> UTF-16
static std::wstring Utf8ToUtf16(const std::string& utf8) {
    if (utf8.empty()) return L"";
    int size = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, nullptr, 0);
    if (size <= 0) return L"";
    std::wstring result(size - 1, 0);
    MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, &result[0], size);
    return result;
}

static std::string Utf16ToUtf8(const std::wstring& utf16) {
    if (utf16.empty()) return "";
    int size = WideCharToMultiByte(CP_UTF8, 0, utf16.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (size <= 0) return "";
    std::string result(size - 1, 0);
    WideCharToMultiByte(CP_UTF8, 0, utf16.c_str(), -1, &result[0], size, nullptr, nullptr);
    return result;
}

static std::string EscapeJsonString(const std::wstring& str) {
    std::string utf8 = Utf16ToUtf8(str);
    std::string escaped;
    escaped.reserve(utf8.size() + 10);
    for (char c : utf8) {
        if (c == '"') escaped += "\\\"";
        else if (c == '\\') escaped += "\\\\";
        else if (c == '\b') escaped += "\\b";
        else if (c == '\f') escaped += "\\f";
        else if (c == '\n') escaped += "\\n";
        else if (c == '\r') escaped += "\\r";
        else if (c == '\t') escaped += "\\t";
        else escaped += c;
    }
    return escaped;
}

static std::string ExtractJsonStringField(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\"";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return "";

    pos = json.find(':', pos + search.length());
    if (pos == std::string::npos) return "";

    pos = json.find('"', pos);
    if (pos == std::string::npos) return "";

    size_t start = pos + 1;
    size_t end = start;
    while (end < json.length()) {
        if (json[end] == '"' && json[end - 1] != '\\') {
            break;
        }
        end++;
    }

    if (end > json.length()) return "";
    return json.substr(start, end - start);
}

static bool ExtractJsonBoolField(const std::string& json, const std::string& key, bool defaultVal = false) {
    std::string search = "\"" + key + "\"";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return defaultVal;

    pos = json.find(':', pos + search.length());
    if (pos == std::string::npos) return defaultVal;

    size_t valStart = json.find_first_not_of(" \t\r\n", pos + 1);
    if (valStart == std::string::npos) return defaultVal;

    if (json.compare(valStart, 4, "true") == 0) return true;
    if (json.compare(valStart, 5, "false") == 0) return false;

    return defaultVal;
}

static std::string Base64UrlEncode(const std::string& data) {
    static const char* b64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string out;
    int val = 0, valb = -6;
    for (unsigned char c : data) {
        val = (val << 8) + c;
        valb += 8;
        while (valb >= 0) {
            out.push_back(b64[(val >> valb) & 0x3F]);
            valb -= 6;
        }
    }
    if (valb > -6) out.push_back(b64[((val << 8) >> (valb + 8)) & 0x3F]);
    return out;
}

AuthManager& AuthManager::Instance() {
    static AuthManager instance;
    return instance;
}

void AuthManager::SetServerUrl(const std::wstring& url) {
    m_serverUrl = url;
    while (!m_serverUrl.empty() && (m_serverUrl.back() == L'/' || m_serverUrl.back() == L' ')) {
        m_serverUrl.pop_back();
    }
}

static bool SendHttpRequestCurlIPv4(
    const std::wstring& verb,
    const std::wstring& fullUrl,
    const std::wstring& serverUrl,
    const std::string& jsonBody,
    const std::wstring& authToken,
    const std::wstring& sessionCookie,
    const std::wstring& additionalHeaders,
    std::string& outResponseBody,
    std::wstring& outSetCookieHeader,
    DWORD& outStatusCode
) {
    SECURITY_ATTRIBUTES sa = { sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE };
    HANDLE hStdInRead = nullptr, hStdInWrite = nullptr;
    HANDLE hStdOutRead = nullptr, hStdOutWrite = nullptr;

    if (!CreatePipe(&hStdInRead, &hStdInWrite, &sa, 0)) return false;
    SetHandleInformation(hStdInWrite, HANDLE_FLAG_INHERIT, 0);

    if (!CreatePipe(&hStdOutRead, &hStdOutWrite, &sa, 0)) {
        CloseHandle(hStdInRead);
        CloseHandle(hStdInWrite);
        return false;
    }
    SetHandleInformation(hStdOutRead, HANDLE_FLAG_INHERIT, 0);

    std::wstring cmd = L"curl.exe -4 -s -k -i --connect-timeout 5 -m 12 -X " + verb;
    cmd += L" -H \"Content-Type: application/json\" -H \"Accept: application/json\"";
    cmd += L" -H \"X-Requested-With: com.prismateams.desktop\"";
    cmd += L" -H \"Origin: " + serverUrl + L"\"";
    cmd += L" -H \"Referer: " + serverUrl + L"/\"";
    if (!authToken.empty()) {
        cmd += L" -H \"Authorization: Bearer " + authToken + L"\"";
    } else if (!sessionCookie.empty()) {
        cmd += L" -H \"Cookie: " + sessionCookie + L"\"";
    }
    if (!jsonBody.empty()) {
        cmd += L" --data-binary @-";
    }
    cmd += L" \"" + fullUrl + L"\"";

    STARTUPINFOW si = { sizeof(STARTUPINFOW) };
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdInput = hStdInRead;
    si.hStdOutput = hStdOutWrite;
    si.hStdError = hStdOutWrite;

    PROCESS_INFORMATION pi = { 0 };
    std::vector<wchar_t> cmdBuf(cmd.begin(), cmd.end());
    cmdBuf.push_back(L'\0');

    BOOL ok = CreateProcessW(nullptr, cmdBuf.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi);
    CloseHandle(hStdInRead);
    CloseHandle(hStdOutWrite);

    if (!ok) {
        CloseHandle(hStdInWrite);
        CloseHandle(hStdOutRead);
        return false;
    }

    if (!jsonBody.empty()) {
        DWORD written = 0;
        WriteFile(hStdInWrite, jsonBody.data(), static_cast<DWORD>(jsonBody.size()), &written, nullptr);
    }
    CloseHandle(hStdInWrite);

    std::string raw;
    char buf[4096];
    DWORD readBytes = 0;
    while (ReadFile(hStdOutRead, buf, sizeof(buf), &readBytes, nullptr) && readBytes > 0) {
        raw.append(buf, readBytes);
    }
    CloseHandle(hStdOutRead);

    WaitForSingleObject(pi.hProcess, 15000);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    if (raw.empty()) return false;

    // Parse last HTTP header block (in case of 100 Continue or redirects)
    size_t sepPos = raw.find("\r\n\r\n");
    if (sepPos == std::string::npos) return false;
    std::string headerBlock = raw.substr(0, sepPos);
    outResponseBody = raw.substr(sepPos + 4);

    // Status code from first line: HTTP/1.1 200 OK
    size_t sp1 = headerBlock.find(' ');
    if (sp1 != std::string::npos) {
        outStatusCode = static_cast<DWORD>(atoi(headerBlock.c_str() + sp1 + 1));
    }

    // Extract Set-Cookie
    std::istringstream hStream(headerBlock);
    std::string line;
    while (std::getline(hStream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.size() > 11 && _strnicmp(line.c_str(), "Set-Cookie:", 11) == 0) {
            std::string val = line.substr(11);
            size_t first = val.find_first_not_of(" \t");
            if (first != std::string::npos) {
                outSetCookieHeader = Utf8ToUtf16(val.substr(first));
                break;
            }
        }
    }

    return outStatusCode > 0;
}

bool AuthManager::SendHttpRequest(
    const std::wstring& verb,
    const std::wstring& path,
    const std::string& jsonBody,
    const std::wstring& additionalHeaders,
    std::string& outResponseBody,
    std::wstring& outSetCookieHeader,
    DWORD& outStatusCode
) {
    outStatusCode = 0;
    outResponseBody.clear();
    outSetCookieHeader.clear();

    URL_COMPONENTS urlComp = { sizeof(URL_COMPONENTS) };
    wchar_t hostName[256] = { 0 };
    wchar_t urlPath[1024] = { 0 };

    urlComp.lpszHostName = hostName;
    urlComp.dwHostNameLength = 256;
    urlComp.lpszUrlPath = urlPath;
    urlComp.dwUrlPathLength = 1024;

    std::wstring fullUrl = m_serverUrl + path;
    if (!WinHttpCrackUrl(fullUrl.c_str(), static_cast<DWORD>(fullUrl.length()), 0, &urlComp)) {
        return false;
    }

    HINTERNET hSession = WinHttpOpen(
        L"Prismateams-NativeClient/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS,
        0
    );
    if (!hSession) return false;

    WinHttpSetTimeouts(hSession, 3000, 3000, 5000, 8000);

    HINTERNET hConnect = WinHttpConnect(hSession, hostName, urlComp.nPort, 0);
    if (!hConnect) {
        WinHttpCloseHandle(hSession);
        return false;
    }

    DWORD flags = (urlComp.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
    std::wstring requestPath = urlComp.lpszUrlPath ? urlComp.lpszUrlPath : L"/";
    if (urlComp.lpszExtraInfo) {
        requestPath += urlComp.lpszExtraInfo;
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect,
        verb.c_str(),
        requestPath.c_str(),
        nullptr,
        WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES,
        flags
    );

    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    // For local development / self-signed certs
    if (flags & WINHTTP_FLAG_SECURE) {
        DWORD secFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA |
                         SECURITY_FLAG_IGNORE_CERT_DATE_INVALID |
                         SECURITY_FLAG_IGNORE_CERT_CN_INVALID |
                         SECURITY_FLAG_IGNORE_CERT_WRONG_USAGE;
        WinHttpSetOption(hRequest, WINHTTP_OPTION_SECURITY_FLAGS, &secFlags, sizeof(secFlags));
    }

    std::wstring headers = L"Content-Type: application/json\r\nAccept: application/json\r\n";
    headers += L"X-Requested-With: com.prismateams.desktop\r\n";
    headers += L"Origin: " + m_serverUrl + L"\r\n";
    headers += L"Referer: " + m_serverUrl + L"/\r\n";
    if (!m_authToken.empty()) {
        headers += L"Authorization: Bearer " + m_authToken + L"\r\n";
    } else if (!m_sessionCookie.empty()) {
        headers += L"Cookie: " + m_sessionCookie + L"\r\n";
    }
    if (!additionalHeaders.empty()) {
        headers += additionalHeaders + L"\r\n";
    }

    BOOL sent = WinHttpSendRequest(
        hRequest,
        headers.c_str(),
        static_cast<DWORD>(headers.length()),
        const_cast<char*>(jsonBody.c_str()),
        static_cast<DWORD>(jsonBody.length()),
        static_cast<DWORD>(jsonBody.length()),
        0
    );

    if (!sent || !WinHttpReceiveResponse(hRequest, nullptr)) {
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        // Fallback to IPv4 curl.exe when WinHTTP hits an IPv6 blackhole (e.g. Dual-Stack DynDNS/myfritz)
        return SendHttpRequestCurlIPv4(
            verb, fullUrl, m_serverUrl, jsonBody,
            m_authToken, m_sessionCookie, additionalHeaders,
            outResponseBody, outSetCookieHeader, outStatusCode
        );
    }

    DWORD statusSize = sizeof(outStatusCode);
    WinHttpQueryHeaders(
        hRequest,
        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX,
        &outStatusCode,
        &statusSize,
        WINHTTP_NO_HEADER_INDEX
    );

    // Get Set-Cookie
    DWORD cookieSize = 0;
    WinHttpQueryHeaders(hRequest, WINHTTP_QUERY_SET_COOKIE, WINHTTP_HEADER_NAME_BY_INDEX, nullptr, &cookieSize, WINHTTP_NO_HEADER_INDEX);
    if (GetLastError() == ERROR_INSUFFICIENT_BUFFER && cookieSize > 0) {
        std::vector<wchar_t> cookieBuf(cookieSize / sizeof(wchar_t) + 1, 0);
        if (WinHttpQueryHeaders(hRequest, WINHTTP_QUERY_SET_COOKIE, WINHTTP_HEADER_NAME_BY_INDEX, cookieBuf.data(), &cookieSize, WINHTTP_NO_HEADER_INDEX)) {
            outSetCookieHeader = cookieBuf.data();
        }
    }

    // Read Response Body
    DWORD bytesAvailable = 0;
    while (WinHttpQueryDataAvailable(hRequest, &bytesAvailable) && bytesAvailable > 0) {
        std::vector<char> buffer(bytesAvailable);
        DWORD bytesRead = 0;
        if (WinHttpReadData(hRequest, buffer.data(), bytesAvailable, &bytesRead) && bytesRead > 0) {
            outResponseBody.append(buffer.data(), bytesRead);
        }
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return true;
}

bool AuthManager::CheckServerReachable(std::wstring& outServerTitle) {
    std::string response;
    std::wstring cookies;
    DWORD status = 0;
    if (!SendHttpRequest(L"GET", L"/login", "", L"", response, cookies, status) || status == 0) {
        return false;
    }
    outServerTitle = L"Prismateams Server Online";
    return (status >= 200 && status < 400 &&
            (response.find("Prismateams") != std::string::npos || response.find("prismateams") != std::string::npos));
}

LoginResult AuthManager::Login(const std::wstring& email, const std::wstring& password, const std::wstring& totpCode) {
    LoginResult res;

    std::ostringstream json;
    json << "{"
         << "\"email\":\"" << EscapeJsonString(email) << "\","
         << "\"password\":\"" << EscapeJsonString(password) << "\","
         << "\"totp_code\":\"" << EscapeJsonString(totpCode) << "\","
         << "\"remember\":true,"
         << "\"return_token\":true"
         << "}";

    std::string response;
    std::wstring setCookie;
    DWORD statusCode = 0;

    bool reqSuccess = SendHttpRequest(L"POST", L"/api/auth/login", json.str(), L"", response, setCookie, statusCode);
    if (!reqSuccess) {
        res.success = false;
        res.errorMessage = L"Verbindung zum Server fehlgeschlagen. Bitte Server-URL prüfen.";
        return res;
    }

    res.requires2FA = ExtractJsonBoolField(response, "requires_2fa", false);
    if (res.requires2FA) {
        res.success = false;
        res.errorMessage = L"Zwei-Faktor-Authentifizierung (TOTP) erforderlich.";
        return res;
    }

    bool successField = ExtractJsonBoolField(response, "success", false);
    if (!successField || statusCode != 200) {
        std::string err = ExtractJsonStringField(response, "error");
        if (err.empty()) err = ExtractJsonStringField(response, "message");
        if (err.empty() && statusCode == 429) {
            err = "Zu viele Anmeldeversuche. Bitte warten Sie einen Moment.";
        }
        if (err.empty()) {
            err = "Anmeldung fehlgeschlagen (HTTP " + std::to_string(statusCode) + "). Server-URL/Port pr\xC3\xBC\x66\x65n.";
        }
        res.success = false;
        res.errorMessage = Utf8ToUtf16(err);
        return res;
    }

    // Success!
    res.success = true;
    res.token = Utf8ToUtf16(ExtractJsonStringField(response, "token"));
    res.userFullName = Utf8ToUtf16(ExtractJsonStringField(response, "full_name"));
    res.userEmail = email;
    res.sessionCookie = setCookie;

    m_authToken = res.token;
    m_sessionCookie = res.sessionCookie;
    m_userFullName = res.userFullName;
    m_userEmail = res.userEmail;
    m_isAuthenticated = true;

    // Save token to credential vault
    CredentialVault::SaveCredentials(CredentialVault::TARGET_AUTH_TOKEN, email, res.token);

    // Save email in settings
    SettingsManager::Instance().Get().lastUserEmail = email;
    SettingsManager::Instance().Save();

    return res;
}

LoginResult AuthManager::PasskeyLogin(HWND hWndParent) {
    LoginResult res;

    // 1. Request WebAuthn challenge & options from server
    std::string optResponse;
    std::wstring optSetCookie;
    DWORD optStatus = 0;

    if (!SendHttpRequest(L"POST", L"/passkey/login/options", "{}", L"", optResponse, optSetCookie, optStatus)) {
        res.errorMessage = L"Verbindung zum Server fehlgeschlagen. Bitte Server-URL pr\xFCfen.";
        return res;
    }

    if (optStatus != 200 || !ExtractJsonBoolField(optResponse, "success", false)) {
        std::string err = ExtractJsonStringField(optResponse, "error");
        res.errorMessage = err.empty() ? L"Passkey-Login wird vom Server nicht unterst\xFCtzt (HTTPS erforderlich)." : Utf8ToUtf16(err);
        return res;
    }

    if (!optSetCookie.empty()) {
        m_sessionCookie = optSetCookie;
    }

    std::string challenge = ExtractJsonStringField(optResponse, "challenge");
    std::string rpIdUtf8 = ExtractJsonStringField(optResponse, "rpId");
    std::wstring rpId = Utf8ToUtf16(rpIdUtf8);
    if (rpId.empty()) {
        rpId = m_serverUrl;
        size_t scheme = rpId.find(L"://");
        if (scheme != std::string::npos) rpId = rpId.substr(scheme + 3);
        size_t slash = rpId.find(L'/');
        if (slash != std::string::npos) rpId = rpId.substr(0, slash);
        size_t port = rpId.find(L':');
        if (port != std::string::npos) rpId = rpId.substr(0, port);
    }

    if (challenge.empty()) {
        res.errorMessage = L"Ung\xFCltige Passkey-Optionen vom Server erhalten.";
        return res;
    }

    // 2. Invoke Windows Hello / WebAuthn
    PasskeyAuthResult pkRes = PasskeyAuthenticator::Authenticate(hWndParent, rpId, challenge);
    if (!pkRes.success) {
        res.errorMessage = pkRes.errorMessage;
        return res;
    }

    std::string credIdB64 = Base64UrlEncode(pkRes.credentialId);
    std::string clientDataB64 = Base64UrlEncode(pkRes.clientDataJson);
    std::string authDataB64 = Base64UrlEncode(pkRes.authenticatorData);
    std::string sigB64 = Base64UrlEncode(pkRes.signature);
    std::string userHandleB64 = pkRes.userHandle.empty() ? "" : Base64UrlEncode(pkRes.userHandle);

    std::ostringstream verifyJson;
    verifyJson << "{\"credential\":{"
               << "\"id\":\"" << credIdB64 << "\","
               << "\"rawId\":\"" << credIdB64 << "\","
               << "\"type\":\"public-key\","
               << "\"response\":{"
               << "\"clientDataJSON\":\"" << clientDataB64 << "\","
               << "\"authenticatorData\":\"" << authDataB64 << "\","
               << "\"signature\":\"" << sigB64 << "\"";
    if (!userHandleB64.empty()) {
        verifyJson << ",\"userHandle\":\"" << userHandleB64 << "\"";
    }
    verifyJson << "}}}";

    // 3. Verify assertion with server
    std::string verifyResp;
    std::wstring verifyCookie;
    DWORD verifyStatus = 0;

    if (!SendHttpRequest(L"POST", L"/passkey/login/verify", verifyJson.str(), L"", verifyResp, verifyCookie, verifyStatus)) {
        res.errorMessage = L"Passkey-Verifizierung konnte nicht an den Server gesendet werden.";
        return res;
    }

    if (verifyStatus != 200 || !ExtractJsonBoolField(verifyResp, "success", false)) {
        std::string err = ExtractJsonStringField(verifyResp, "error");
        res.errorMessage = err.empty() ? L"Passkey-Anmeldung fehlgeschlagen." : Utf8ToUtf16(err);
        return res;
    }

    if (!verifyCookie.empty()) {
        m_sessionCookie = verifyCookie;
    }

    res.success = true;
    res.sessionCookie = m_sessionCookie;
    m_isAuthenticated = true;
    return res;
}

bool AuthManager::VerifyStoredSession() {
    std::wstring savedEmail, savedToken;
    if (!CredentialVault::LoadCredentials(CredentialVault::TARGET_AUTH_TOKEN, savedEmail, savedToken) || savedToken.empty()) {
        return false;
    }

    m_authToken = savedToken;
    m_userEmail = savedEmail;

    std::string response;
    std::wstring setCookie;
    DWORD statusCode = 0;

    std::string body = "{\"token\":\"" + EscapeJsonString(savedToken) + "\"}";
    if (!SendHttpRequest(L"POST", L"/api/auth/verify-token", body, L"", response, setCookie, statusCode)) {
        return false;
    }

    if (statusCode == 200 && ExtractJsonBoolField(response, "success", false)) {
        m_isAuthenticated = true;
        m_userFullName = Utf8ToUtf16(ExtractJsonStringField(response, "full_name"));
        if (!setCookie.empty()) {
            m_sessionCookie = setCookie;
        }
        return true;
    }

    m_isAuthenticated = false;
    m_authToken.clear();
    return false;
}

WebDavCredentialsResult AuthManager::FetchWebDavCredentials() {
    WebDavCredentialsResult result;
    if (!m_isAuthenticated) {
        result.errorMessage = L"Nicht authentifiziert.";
        return result;
    }

    std::string response;
    std::wstring setCookie;
    DWORD statusCode = 0;

    bool reqSuccess = SendHttpRequest(L"POST", L"/api/windows/webdav-credentials", "{}", L"", response, setCookie, statusCode);
    if (!reqSuccess || statusCode == 404) {
        // Fallback to /files/api/windows/webdav-credentials if /api/windows returned 404 or failed
        SendHttpRequest(L"POST", L"/files/api/windows/webdav-credentials", "{}", L"", response, setCookie, statusCode);
    }

    if (statusCode == 200 && ExtractJsonBoolField(response, "success", false)) {
        result.success = true;
        result.username = Utf8ToUtf16(ExtractJsonStringField(response, "username"));
        result.password = Utf8ToUtf16(ExtractJsonStringField(response, "password"));

        // Save WebDAV credentials in Vault
        CredentialVault::SaveCredentials(CredentialVault::TARGET_WEBDAV_PASS, result.username, result.password);
        return result;
    }

    // Fallback: check stored credentials in Windows Credential Vault
    std::wstring cachedUser, cachedPass;
    if (CredentialVault::LoadCredentials(CredentialVault::TARGET_WEBDAV_PASS, cachedUser, cachedPass) && !cachedUser.empty() && !cachedPass.empty()) {
        result.success = true;
        result.username = cachedUser;
        result.password = cachedPass;
        return result;
    }

    result.errorMessage = Utf8ToUtf16(ExtractJsonStringField(response, "error"));
    if (result.errorMessage.empty()) result.errorMessage = L"WebDAV-Zugangsdaten konnten nicht abgerufen werden.";
    return result;
}

bool AuthManager::Logout() {
    std::string response;
    std::wstring setCookie;
    DWORD statusCode = 0;
    SendHttpRequest(L"POST", L"/api/auth/logout", "{}", L"", response, setCookie, statusCode);

    CredentialVault::DeleteCredentials(CredentialVault::TARGET_AUTH_TOKEN);
    CredentialVault::DeleteCredentials(CredentialVault::TARGET_WEBDAV_PASS);

    m_isAuthenticated = false;
    m_authToken.clear();
    m_sessionCookie.clear();
    m_userFullName.clear();

    return true;
}

} // namespace Prismateams
