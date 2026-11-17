#include "credential_vault.h"
#include <vector>

namespace Prismateams {

const wchar_t* const CredentialVault::TARGET_AUTH_TOKEN  = L"Prismateams/ApiSession";
const wchar_t* const CredentialVault::TARGET_WEBDAV_PASS = L"Prismateams/WebDAV";

bool CredentialVault::SaveCredentials(const std::wstring& target, const std::wstring& username, const std::wstring& password) {
    CREDENTIALW cred = { 0 };
    cred.Type = CRED_TYPE_GENERIC;
    cred.TargetName = const_cast<LPWSTR>(target.c_str());
    cred.UserName = const_cast<LPWSTR>(username.c_str());
    cred.CredentialBlobSize = static_cast<DWORD>(password.length() * sizeof(wchar_t));
    cred.CredentialBlob = reinterpret_cast<LPBYTE>(const_cast<LPWSTR>(password.c_str()));
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE;

    return (CredWriteW(&cred, 0) == TRUE);
}

bool CredentialVault::LoadCredentials(const std::wstring& target, std::wstring& outUsername, std::wstring& outPassword) {
    PCREDENTIALW pCred = nullptr;
    if (!CredReadW(target.c_str(), CRED_TYPE_GENERIC, 0, &pCred) || pCred == nullptr) {
        return false;
    }

    if (pCred->UserName != nullptr) {
        outUsername = pCred->UserName;
    } else {
        outUsername.clear();
    }

    if (pCred->CredentialBlob != nullptr && pCred->CredentialBlobSize > 0) {
        outPassword.assign(
            reinterpret_cast<const wchar_t*>(pCred->CredentialBlob),
            pCred->CredentialBlobSize / sizeof(wchar_t)
        );
    } else {
        outPassword.clear();
    }

    CredFree(pCred);
    return true;
}

bool CredentialVault::DeleteCredentials(const std::wstring& target) {
    return (CredDeleteW(target.c_str(), CRED_TYPE_GENERIC, 0) == TRUE);
}

} // namespace Prismateams
