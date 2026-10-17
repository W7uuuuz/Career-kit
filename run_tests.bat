@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHON=%~dp0.venv\Scripts\python.exe

echo.
echo ========================================
echo   Career Kit 测试套件
echo ========================================
echo.

if not exist "%PYTHON%" (
    echo [错误] 未找到虚拟环境解释器: %PYTHON%
    echo 请先创建环境:
    echo   uv venv .venv --python 3.12
    echo   uv pip install -e . --index-url https://pypi.org/simple
    echo   uv pip install pytest pytest-asyncio --index-url https://pypi.org/simple
    exit /b 1
)

if "%CAREER_KIT_DATA_DIR%"=="" set CAREER_KIT_DATA_DIR=%TEMP%\career_kit_test

echo 解释器: %PYTHON%
echo 数据目录: %CAREER_KIT_DATA_DIR%
echo.

"%PYTHON%" -m pytest tests -q --ignore=tests/career-kit-test
if errorlevel 1 goto :error

echo.
echo ========================================
echo   所有测试通过!
echo ========================================
goto :end

:error
echo.
echo ========================================
echo   测试失败!
echo ========================================

:end
pause
