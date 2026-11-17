cmake_minimum_required(VERSION 3.20)
project(Prismateams VERSION 1.0.0 LANGUAGES CXX RC)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_definitions(-DUNICODE -D_UNICODE -D_WINDOWS)

set(WEBVIEW2_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/packages/Microsoft.Web.WebView2/build/native/include")
set(WEBVIEW2_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/packages/Microsoft.Web.WebView2/build/native/x64")

include_directories(
    ${WEBVIEW2_INCLUDE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/resources
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

link_directories(${WEBVIEW2_LIB_DIR})

set(SOURCES
    src/main.cpp
    src/app.h
    src/app.cpp
    src/native_login_view.h
    src/native_login_view.cpp
    src/native_settings_window.h
    src/native_settings_window.cpp
    src/passkey_authenticator.h
    src/passkey_authenticator.cpp
    src/settings.h
    src/settings.cpp
    src/credential_vault.h
    src/credential_vault.cpp
    src/auth_manager.h
    src/auth_manager.cpp
    src/webdav_manager.h
    src/webdav_manager.cpp
    src/file_router.h
    src/file_router.cpp
    src/webview_controller.h
    src/webview_controller.cpp
    src/tray_icon.h
    src/tray_icon.cpp
    resources/resource.h
    resources/Prismateams.rc
)

add_executable(Prismateams WIN32 ${SOURCES})

target_link_libraries(Prismateams PRIVATE
    "${WEBVIEW2_LIB_DIR}/WebView2LoaderStatic.lib"
    mpr
    winhttp
    comctl32
    shell32
    advapi32
    ole32
    shlwapi
    dwmapi
    uxtheme
)

set_target_properties(Prismateams PROPERTIES
    OUTPUT_NAME "Prismateams"
)
