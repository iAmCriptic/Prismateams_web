#pragma once

#include <string>
#include <windows.h>

namespace Prismateams {

enum class FileActionType {
    None,
    OpenOnlyOffice,
    OpenExcalidraw,
    ShowInFiles,
    DirectUrl
};

struct FileRouteResult {
    bool success = false;
    FileActionType action = FileActionType::None;
    std::wstring navigationUrl = L"";
    std::wstring filename = L"";
    std::wstring errorMessage = L"";
};

class FileRouter {
public:
    static FileRouter& Instance();

    bool IsSupportedOfficeExtension(const std::wstring& ext) const;
    bool IsExcalidrawExtension(const std::wstring& ext) const;

    FileRouteResult RouteLocalPath(const std::wstring& localPath);
    FileRouteResult RouteCustomProtocol(const std::wstring& uri);

private:
    FileRouter() = default;

    std::wstring UrlEncode(const std::wstring& str);
    std::wstring ExtractExtension(const std::wstring& path) const;
};

} // namespace Prismateams
