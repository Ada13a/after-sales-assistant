@echo off
cd /d "%~dp0"
echo ======================================
echo   售后助手
echo   启动中...
echo   对话测试: http://localhost:5051/
echo   管理后台: http://localhost:5051/admin
echo ======================================
python app.py
pause
