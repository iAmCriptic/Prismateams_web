#pragma once

#include <windows.h>
#include <string>

namespace Prismateams {

struct PasskeyAuthResult {
    bool success = false;
    std::wstring errorMessage = L"";
    std::string credentialId = "";
    std::string authenticatorData = "";
    std::string clientDataJson = "";
    std::string signature = "";
    std::string userHandle = "";
};

class PasskeyAuthenticator {
public:
    static bool IsAvailable();
    static PasskeyAuthResult Authenticate(HWND hWndParent, const std::wstring& rpId, const std::string& challenge);
};

} // namespace Prismateams
