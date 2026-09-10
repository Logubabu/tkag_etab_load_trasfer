@echo off
cd /d "%~dp0"
echo Starting ETABS to RAM Concept Tool...
py -c "import platform; print('Python:', platform.python_version(), platform.architecture()[0])"
py app.py
if errorlevel 1 pause
