@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python，请先从 https://www.python.org/downloads/ 安装 Python 3.9+，并勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

echo [1/2] 安装打包工具 PyInstaller ...
python -m pip install --upgrade pyinstaller || goto :error

echo [2/2] 打包 BatchRename.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name BatchRename main.py || goto :error

echo.
echo 完成！可执行文件位于：%~dp0dist\BatchRename.exe
explorer "%~dp0dist"
pause
exit /b 0

:error
echo 打包失败，请查看上面的错误信息。
pause
exit /b 1
