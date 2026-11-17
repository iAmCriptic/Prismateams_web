#pragma once

#include <string>
#include <windows.h>

namespace Prismateams {

class WebDavManager {
public:
    static WebDavManager& Instance();

    bool EnsureWebClientServiceRunning();

    bool MountDrive(
        const std::wstring& serverUrl,
        const std::wstring& username,
        const std::wstring& password,
        wchar_t preferredLetter,
        wchar_t& outAssignedLetter,
        std::wstring& outErrorMessage
    );

    bool UnmountDrive(wchar_t driveLetter, bool force = true);
    bool UnmountCurrentDrive(bool force = true);

    bool IsMounted() const { return m_isMounted; }
    wchar_t GetMountedDriveLetter() const { return m_mountedLetter; }
    std::wstring GetMountedDrivePath() const;

    bool OpenInExplorer();

    static bool IsDriveLetterInUse(wchar_t letter);
    static wchar_t FindAvailableDriveLetter(wchar_t preferred);

private:
    WebDavManager() = default;

    std::wstring FormatWebDavUncPath(const std::wstring& serverUrl);

    bool m_isMounted = false;
    wchar_t m_mountedLetter = L'P';
    std::wstring m_uncPath = L"";
};

} // namespace Prismateams
