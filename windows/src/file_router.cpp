#include "file_router.h"
#include "auth_manager.h"
#include "webdav_manager.h"
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <winhttp.h>

namespace Prismateams {

static std::string ExtractJsonStr(const std::string& json, const std::string& key) {
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
        if (json[end] == '"' && json[end - 1] != '\\') break;
        end++;
    }
    if (end > json.length()) return "";
    return json.substr(start, end - start);
}

static bool ExtractJsonBool(const std::string& json, const std::string& key, bool defaultVal = false) {
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

static std::wstring Utf8ToUtf16Str(const std::string& utf8) {
    if (utf8.empty()) return L"";
    int size = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, nullptr, 0);
    if (size <= 0) return L"";
    std::wstring result(size - 1, 0);
    MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, &result[0], size);
    return result;
}

FileRouter& FileRouter::Instance() {
    static FileRouter instance;
    return instance;
}

std::wstring FileRouter::ExtractExtension(const std::wstring& path) const {
    size_t dotPos = path.find_last_of(L'.');
    if (dotPos == std::string::npos) return L"";
    std::wstring ext = path.substr(dotPos);
    std::transform(ext.begin(), ext.end(), ext.begin(), ::towlower);
    return ext;
}

bool FileRouter::IsSupportedOfficeExtension(const std::wstring& ext) const {
    static const wchar_t* officeExts[] = {
        L".docx", L".doc", L".odt", L".rtf", L".txt",
        L".xlsx", L".xls", L".ods", L".csv",
        L".pptx", L".ppt", L".odp"
    };
    for (const wchar_t* oExt : officeExts) {
        if (ext == oExt) return true;
    }
    return false;
}

bool FileRouter::IsExcalidrawExtension(const std::wstring& ext) const {
    return (ext == L".excalidraw");
}

std::wstring FileRouter::UrlEncode(const std::wstring& str) {
    int utf8Len = WideCharToMultiByte(CP_UTF8, 0, str.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (utf8Len <= 0) return L"";
    std::string utf8(utf8Len - 1, 0);
    WideCharToMultiByte(CP_UTF8, 0, str.c_str(), -1, &utf8[0], utf8Len, nullptr, nullptr);

    std::ostringstream escaped;
    escaped.fill('0');
    escaped << std::hex;

    for (unsigned char c : utf8) {
        if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~' || c == '/') {
            escaped << c;
        } else {
            escaped << '%' << std::setw(2) << int(c);
        }
    }

    std::string encoded = escaped.str();
    return Utf8ToUtf16Str(encoded);
}

FileRouteResult FileRouter::RouteLocalPath(const std::wstring& localPath) {
    FileRouteResult result;
    if (localPath.empty()) return result;

    std::wstring ext = ExtractExtension(localPath);
    wchar_t driveLetter = WebDavManager::Instance().GetMountedDriveLetter();
    std::wstring drivePrefix = std::wstring(1, driveLetter) + L":";

    std::wstring relativePath = localPath;

    // Check if path is on the mounted WebDAV drive
    bool onWebDav = false;
    if (relativePath.length() >= 2 && towupper(relativePath[0]) == towupper(driveLetter) && relativePath[1] == L':') {
        relativePath = relativePath.substr(2);
        onWebDav = true;
    } else if (relativePath.rfind(L"\\\\", 0) == 0 && relativePath.find(L"\\webdav") != std::string::npos) {
        size_t davPos = relativePath.find(L"\\webdav");
        relativePath = relativePath.substr(davPos + 7);
        onWebDav = true;
    }

    // Replace backslashes with slashes
    for (wchar_t& ch : relativePath) {
        if (ch == L'\\') ch = L'/';
    }

    const std::wstring& serverUrl = AuthManager::Instance().GetServerUrl();

    if (onWebDav) {
        // Query server to resolve path
        std::wstring resolvePath = L"/api/windows/resolve-path?path=" + UrlEncode(relativePath);

        // WinHTTP call
        URL_COMPONENTS urlComp = { sizeof(URL_COMPONENTS) };
        wchar_t hostName[256] = { 0 };
        wchar_t urlPath[1024] = { 0 };
        urlComp.lpszHostName = hostName;
        urlComp.dwHostNameLength = 256;
        urlComp.lpszUrlPath = urlPath;
        urlComp.dwUrlPathLength = 1024;

        std::wstring fullUrl = serverUrl + resolvePath;
        if (WinHttpCrackUrl(fullUrl.c_str(), static_cast<DWORD>(fullUrl.length()), 0, &urlComp)) {
            HINTERNET hSession = WinHttpOpen(L"Prismateams/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, nullptr, nullptr, 0);
            if (hSession) {
                HINTERNET hConnect = WinHttpConnect(hSession, hostName, urlComp.nPort, 0);
                if (hConnect) {
                    DWORD flags = (urlComp.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
                    std::wstring rPath = urlComp.lpszUrlPath ? urlComp.lpszUrlPath : L"/";
                    if (urlComp.lpszExtraInfo) rPath += urlComp.lpszExtraInfo;

                    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"GET", rPath.c_str(), nullptr, WINHTTP_NO_REFERER, nullptr, flags);
                    if (hRequest) {
                        if (flags & WINHTTP_FLAG_SECURE) {
                            DWORD secFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_CERT_DATE_INVALID |
                                             SECURITY_FLAG_IGNORE_CERT_CN_INVALID | SECURITY_FLAG_IGNORE_CERT_WRONG_USAGE;
                            WinHttpSetOption(hRequest, WINHTTP_OPTION_SECURITY_FLAGS, &secFlags, sizeof(secFlags));
                        }

                        std::wstring headers = L"Accept: application/json\r\n";
                        const std::wstring& token = AuthManager::Instance().GetAuthToken();
                        if (!token.empty()) {
                            headers += L"Authorization: Bearer " + token + L"\r\n";
                        }
                        const std::wstring& cookie = AuthManager::Instance().GetSessionCookie();
                        if (!cookie.empty()) {
                            headers += L"Cookie: " + cookie + L"\r\n";
                        }

                        if (WinHttpSendRequest(hRequest, headers.c_str(), static_cast<DWORD>(headers.length()), nullptr, 0, 0, 0) &&
                            WinHttpReceiveResponse(hRequest, nullptr)) {
                            std::string body;
                            DWORD bytesAvailable = 0;
                            while (WinHttpQueryDataAvailable(hRequest, &bytesAvailable) && bytesAvailable > 0) {
                                std::vector<char> buf(bytesAvailable);
                                DWORD bytesRead = 0;
                                if (WinHttpReadData(hRequest, buf.data(), bytesAvailable, &bytesRead) && bytesRead > 0) {
                                    body.append(buf.data(), bytesRead);
                                }
                            }

                            if (ExtractJsonBool(body, "success", false) && ExtractJsonBool(body, "found", false)) {
                                std::string actionStr = ExtractJsonStr(body, "action");
                                std::string editUrlStr = ExtractJsonStr(body, "edit_url");

                                result.success = true;
                                result.navigationUrl = serverUrl + Utf8ToUtf16Str(editUrlStr);
                                result.filename = Utf8ToUtf16Str(ExtractJsonStr(body, "filename"));

                                if (actionStr == "edit_onlyoffice") {
                                    result.action = FileActionType::OpenOnlyOffice;
                                } else if (actionStr == "edit_excalidraw") {
                                    result.action = FileActionType::OpenExcalidraw;
                                } else {
                                    result.action = FileActionType::ShowInFiles;
                                }

                                WinHttpCloseHandle(hRequest);
                                WinHttpCloseHandle(hConnect);
                                WinHttpCloseHandle(hSession);
                                return result;
                            }
                        }
                        WinHttpCloseHandle(hRequest);
                    }
                    WinHttpCloseHandle(hConnect);
                }
                WinHttpCloseHandle(hSession);
            }
        }
    }

    // Fallback if not on WebDAV or resolution failed:
    if (IsExcalidrawExtension(ext)) {
        result.success = true;
        result.action = FileActionType::OpenExcalidraw;
        result.navigationUrl = serverUrl + L"/excalidraw";
        return result;
    } else if (IsSupportedOfficeExtension(ext)) {
        result.success = true;
        result.action = FileActionType::ShowInFiles;
        result.navigationUrl = serverUrl + L"/files";
        return result;
    }

    result.success = true;
    result.action = FileActionType::DirectUrl;
    result.navigationUrl = serverUrl;
    return result;
}

FileRouteResult FileRouter::RouteCustomProtocol(const std::wstring& uri) {
    FileRouteResult result;
    // Format: prismateams://open?path=... or prismateams://file?id=...
    const std::wstring& serverUrl = AuthManager::Instance().GetServerUrl();

    if (uri.find(L"prismateams://") == 0) {
        std::wstring query = uri.substr(14);
        if (query.find(L"edit-onlyoffice/") == 0) {
            result.success = true;
            result.action = FileActionType::OpenOnlyOffice;
            result.navigationUrl = serverUrl + L"/files/" + query;
            return result;
        } else if (query.find(L"excalidraw/") == 0) {
            result.success = true;
            result.action = FileActionType::OpenExcalidraw;
            result.navigationUrl = serverUrl + L"/" + query;
            return result;
        }
    }

    result.success = true;
    result.action = FileActionType::DirectUrl;
    result.navigationUrl = serverUrl;
    return result;
}

} // namespace Prismateams
