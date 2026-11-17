#include "passkey_authenticator.h"
#include <webauthn.h>
#include <vector>

namespace Prismateams {

typedef DWORD (WINAPI *FnWebAuthnGetMinSupportedApiVersion)(void);
typedef HRESULT (WINAPI *FnWebAuthnAuthenticatorGetAssertion)(
    HWND hWnd,
    LPCWSTR pwszRpId,
    PCWEBAUTHN_CLIENT_DATA pWebAuthNClientData,
    PCWEBAUTHN_AUTHENTICATOR_GET_ASSERTION_OPTIONS pWebAuthNGetAssertionOptions,
    PWEBAUTHN_ASSERTION *ppWebAuthNAssertion
);
typedef void (WINAPI *FnWebAuthnFreeAssertion)(PWEBAUTHN_ASSERTION pWebAuthNAssertion);

bool PasskeyAuthenticator::IsAvailable() {
    HMODULE hLib = LoadLibraryW(L"webauthn.dll");
    if (!hLib) return false;

    auto fnGetVer = (FnWebAuthnGetMinSupportedApiVersion)GetProcAddress(hLib, "WebAuthnGetMinSupportedApiVersion");
    bool available = (fnGetVer != nullptr && fnGetVer() >= WEBAUTHN_API_VERSION_1);
    FreeLibrary(hLib);
    return available;
}

PasskeyAuthResult PasskeyAuthenticator::Authenticate(HWND hWndParent, const std::wstring& rpId, const std::string& challenge) {
    PasskeyAuthResult result;

    HMODULE hLib = LoadLibraryW(L"webauthn.dll");
    if (!hLib) {
        result.errorMessage = L"WebAuthn / Windows Hello ist auf diesem System nicht verf\xFCgbar.";
        return result;
    }

    auto fnGetVer = (FnWebAuthnGetMinSupportedApiVersion)GetProcAddress(hLib, "WebAuthnGetMinSupportedApiVersion");
    auto fnGetAssertion = (FnWebAuthnAuthenticatorGetAssertion)GetProcAddress(hLib, "WebAuthnAuthenticatorGetAssertion");
    auto fnFreeAssertion = (FnWebAuthnFreeAssertion)GetProcAddress(hLib, "WebAuthnFreeAssertion");

    if (!fnGetVer || !fnGetAssertion || !fnFreeAssertion) {
        FreeLibrary(hLib);
        result.errorMessage = L"WebAuthn-Funktionen konnten nicht geladen werden.";
        return result;
    }

    DWORD apiVer = fnGetVer();
    if (apiVer < WEBAUTHN_API_VERSION_1) {
        FreeLibrary(hLib);
        result.errorMessage = L"WebAuthn-Version wird von diesem Windows nicht unterst\xFCtzt.";
        return result;
    }

    // Client data
    std::string rpIdUtf8;
    int len = WideCharToMultiByte(CP_UTF8, 0, rpId.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (len > 1) {
        rpIdUtf8.resize(len - 1);
        WideCharToMultiByte(CP_UTF8, 0, rpId.c_str(), -1, &rpIdUtf8[0], len, nullptr, nullptr);
    }

    std::string clientDataStr = "{\"type\":\"webauthn.get\",\"challenge\":\"" + challenge + "\",\"origin\":\"https://" +
        rpIdUtf8 + "\",\"crossOrigin\":false}";

    WEBAUTHN_CLIENT_DATA clientData = { 0 };
    clientData.dwVersion = WEBAUTHN_CLIENT_DATA_CURRENT_VERSION;
    clientData.cbClientDataJSON = static_cast<DWORD>(clientDataStr.length());
    clientData.pbClientDataJSON = reinterpret_cast<PBYTE>(const_cast<char*>(clientDataStr.c_str()));
    clientData.pwszHashAlgId = WEBAUTHN_HASH_ALGORITHM_SHA_256;

    WEBAUTHN_AUTHENTICATOR_GET_ASSERTION_OPTIONS options = { 0 };
    options.dwVersion = WEBAUTHN_AUTHENTICATOR_GET_ASSERTION_OPTIONS_CURRENT_VERSION;
    options.dwTimeoutMilliseconds = 60000;
    options.dwUserVerificationRequirement = WEBAUTHN_USER_VERIFICATION_REQUIREMENT_REQUIRED;

    PWEBAUTHN_ASSERTION pAssertion = nullptr;

    HRESULT hr = fnGetAssertion(
        hWndParent,
        rpId.c_str(),
        &clientData,
        &options,
        &pAssertion
    );

    if (SUCCEEDED(hr) && pAssertion) {
        result.success = true;
        result.clientDataJson = clientDataStr;
        if (pAssertion->pbAuthenticatorData && pAssertion->cbAuthenticatorData > 0) {
            result.authenticatorData.assign(
                reinterpret_cast<char*>(pAssertion->pbAuthenticatorData),
                pAssertion->cbAuthenticatorData
            );
        }
        if (pAssertion->pbSignature && pAssertion->cbSignature > 0) {
            result.signature.assign(
                reinterpret_cast<char*>(pAssertion->pbSignature),
                pAssertion->cbSignature
            );
        }
        fnFreeAssertion(pAssertion);
    } else {
        if (hr == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
            result.errorMessage = L"Authentifizierung durch Benutzer abgebrochen.";
        } else {
            result.errorMessage = L"Passkey-Authentifizierung fehlgeschlagen (Code: 0x" + std::to_wstring(hr) + L").";
        }
    }

    FreeLibrary(hLib);
    return result;
}

} // namespace Prismateams
