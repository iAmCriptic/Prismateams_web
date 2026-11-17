#include "settings.h"
#include <shlobj.h>
#include <fstream>
#include <sstream>
#include <filesystem>

namespace Prismateams {

namespace fs = std::filesystem;

SettingsManager& SettingsManager::Instance() {
    static SettingsManager instance;
    return instance;
}

std::wstring SettingsManager::GetAppDataDirectory() const {
    PWSTR localAppData = nullptr;
    std::wstring dirPath = L"";
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &localAppData))) {
        dirPath = std::wstring(localAppData) + L"\\Prismateams";
        CoTaskMemFree(localAppData);
    } else {
        dirPath = L".\\PrismateamsData";
    }

    try {
        fs::create_directories(dirPath);
    } catch (...) {}

    return dirPath;
}

std::wstring SettingsManager::GetConfigFilePath() const {
    return GetAppDataDirectory() + L"\\config.ini";
}

bool SettingsManager::Load() {
    std::wstring path = GetConfigFilePath();
    if (!fs::exists(path)) {
        return false;
    }

    wchar_t buffer[1024];

    // Server URL
    GetPrivateProfileStringW(L"Server", L"Url", L"https://localhost:5000", buffer, 1024, path.c_str());
    m_settings.serverUrl = buffer;

    // Drive letter
    GetPrivateProfileStringW(L"WebDAV", L"DriveLetter", L"P", buffer, 1024, path.c_str());
    if (buffer[0] >= L'A' && buffer[0] <= L'Z') {
        m_settings.driveLetter = buffer[0];
    } else {
        m_settings.driveLetter = L'P';
    }

    // Auto mount
    m_settings.autoMountDrive = (GetPrivateProfileIntW(L"WebDAV", L"AutoMount", 1, path.c_str()) != 0);

    // Minimize to tray
    m_settings.minimizeToTray = (GetPrivateProfileIntW(L"UI", L"MinimizeToTray", 1, path.c_str()) != 0);

    // Last user
    GetPrivateProfileStringW(L"Auth", L"LastEmail", L"", buffer, 1024, path.c_str());
    m_settings.lastUserEmail = buffer;

    m_settings.autoStartWithWindows = IsAutoStartEnabled();

    return true;
}

bool SettingsManager::Save() {
    std::wstring path = GetConfigFilePath();

    WritePrivateProfileStringW(L"Server", L"Url", m_settings.serverUrl.c_str(), path.c_str());

    wchar_t driveStr[2] = { m_settings.driveLetter, 0 };
    WritePrivateProfileStringW(L"WebDAV", L"DriveLetter", driveStr, path.c_str());
    WritePrivateProfileStringW(L"WebDAV", L"AutoMount", m_settings.autoMountDrive ? L"1" : L"0", path.c_str());
    WritePrivateProfileStringW(L"UI", L"MinimizeToTray", m_settings.minimizeToTray ? L"1" : L"0", path.c_str());
    WritePrivateProfileStringW(L"Auth", L"LastEmail", m_settings.lastUserEmail.c_str(), path.c_str());

    SetAutoStart(m_settings.autoStartWithWindows);

    return true;
}

bool SettingsManager::SetAutoStart(bool enable) {
    HKEY hKey;
    const wchar_t* runKey = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    if (RegOpenKeyExW(HKEY_CURRENT_USER, runKey, 0, KEY_SET_VALUE, &hKey) != ERROR_SUCCESS) {
        return false;
    }

    bool success = false;
    if (enable) {
        wchar_t exePath[MAX_PATH];
        GetModuleFileNameW(nullptr, exePath, MAX_PATH);
        std::wstring cmd = L"\"" + std::wstring(exePath) + L"\" --minimized";
        if (RegSetValueExW(hKey, L"Prismateams", 0, REG_SZ,
            reinterpret_cast<const BYTE*>(cmd.c_str()),
            static_cast<DWORD>((cmd.length() + 1) * sizeof(wchar_t))) == ERROR_SUCCESS) {
            success = true;
        }
    } else {
        RegDeleteValueW(hKey, L"Prismateams");
        success = true;
    }

    RegCloseKey(hKey);
    return success;
}

bool SettingsManager::IsAutoStartEnabled() const {
    HKEY hKey;
    const wchar_t* runKey = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";
    if (RegOpenKeyExW(HKEY_CURRENT_USER, runKey, 0, KEY_QUERY_VALUE, &hKey) != ERROR_SUCCESS) {
        return false;
    }

    DWORD type = 0;
    DWORD size = 0;
    LONG result = RegQueryValueExW(hKey, L"Prismateams", nullptr, &type, nullptr, &size);
    RegCloseKey(hKey);

    return (result == ERROR_SUCCESS);
}

} // namespace Prismateams
