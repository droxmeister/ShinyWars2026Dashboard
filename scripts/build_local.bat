@echo off
cd /d %~dp0\..
python -m src.build_dashboard --local-input-dir local_input --output web\data\strategy.json
if errorlevel 1 exit /b 1
python scripts\validate_site_data.py web\data\strategy.json
if errorlevel 1 exit /b 1
echo Start a local server with: python -m http.server 8000 --directory web
