#pragma once

#include <string>
#include <windows.h>
#include <wincred.h>

namespace Prismateams {

class CredentialVault {
public:
    static bool SaveCredentials(const std::wstring& target, const std::wstring& username, const std::wstring& password);
    static bool LoadCredentials(const std::wstring& target, std::wstring& outUsername, std::wstring& outPassword);
    static bool DeleteCredentials(const std::wstring& target);

    // Well-known targets
    static const wchar_t* const TARGET_AUTH_TOKEN;
    static const wchar_t* const TARGET_WEBDAV_PASS;
};

} // namespace Prismateams
