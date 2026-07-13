@echo off
setlocal enabledelayedexpansion

echo ================================
echo   bili-sniffer Windows 安装器
echo ================================
echo.
echo   1) 单文件脚本      - 下载 .py + pip 安装依赖 (推荐)
echo   2) 预编译二进制    - PyInstaller .exe (Windows x64)
echo.

set /p choice="  选择 [1-2] (回车=1): "
if "%choice%"=="" set choice=1

set INSTALL_DIR=%USERPROFILE%\.local\bin
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

set RAW=https://raw.githubusercontent.com/anomalyco/bili-sniffer/main
set RELEASE=https://github.com/anomalyco/bili-sniffer/releases/latest/download

if "%choice%"=="1" (
    echo.
    echo [*] 下载脚本...
    curl -fsSLo "%INSTALL_DIR%\bilibili_sniffer.py" "%RAW%/bilibili_sniffer.py"
    if %errorlevel% neq 0 goto :fail
    echo [*] 安装依赖...
    pip install requests browser_cookie3 cryptography --quiet 2>nul
    (
      echo @echo off
      echo python "%%USERPROFILE%%\.local\bin\bilibili_sniffer.py" %%*
    ) > "%INSTALL_DIR%\bili-sniffer.bat"
    setx PATH "%PATH%;%INSTALL_DIR%" >nul 2>&1
    echo [+] 完成! 重启终端后运行: bili-sniffer
) else if "%choice%"=="2" (
    echo.
    echo [*] 下载二进制...
    curl -fsSLo "%INSTALL_DIR%\bili-sniffer.exe" "%RELEASE%/bili-sniffer-windows.exe"
    if %errorlevel% neq 0 goto :fail
    setx PATH "%PATH%;%INSTALL_DIR%" >nul 2>&1
    echo [+] 完成! 重启终端后运行: bili-sniffer
) else (
    echo [-] 无效选择
)

goto :end

:fail
echo [-] 下载失败, 请检查网络 / GitHub 可用性

:end
endlocal
