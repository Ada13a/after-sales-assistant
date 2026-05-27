@echo off
cd /d "%~dp0"

echo ============================================================
echo   WeCom Chat Data Extraction Tool
echo ============================================================
echo.
echo This tool will:
echo   1. Scan WeCom process memory for DB keys
echo   2. Decrypt local database files
echo   3. Extract all chat messages
echo.
echo Requirements:
echo   - WeCom (WXWork) must be running and logged in
echo   - Python 3.x installed
echo.
echo ============================================================
echo.

python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Please install Python 3.x first.
    pause
    exit /b 1
)

echo [0/3] Installing dependencies...
pip install psutil pymem pycryptodome zstandard -q
echo Done.
echo.

echo [1/3] Scanning for DB keys...
echo NOTE: Admin privileges may be required.
echo.
python scan_key.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Key scan failed.
    pause
    exit /b 1
)
echo.

echo [2/3] Decrypting databases...
python decrypt_db.py --all
echo.

echo [3/3] Extracting messages...
python extract_messages.py
echo.

echo ============================================================
echo All done!
echo Pack the entire wecom_extract_tool folder and send it back.
echo ============================================================

pause
