#pragma once

#include <string>
#include <windows.h>

namespace Prismateams {

struct AppSettings {
    std::wstring serverUrl = L"https://localhost:5000";
    wchar_t driveLetter = L'P';
    bool autoMountDrive = true;
    bool autoStartWithWindows = false;
    bool minimizeToTray = true;
    std::wstring lastUserEmail = L"";
};

class SettingsManager {
public:
    static SettingsManager& Instance();

    bool Load();
    bool Save();

    AppSettings& Get() { return m_settings; }
    const AppSettings& Get() const { return m_settings; }

    std::wstring GetConfigFilePath() const;
    std::wstring GetAppDataDirectory() const;

    bool SetAutoStart(bool enable);
    bool IsAutoStartEnabled() const;

private:
    SettingsManager() = default;
    AppSettings m_settings;
};

} // namespace Prismateams
