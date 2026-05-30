@echo off
:: geosnap.bat — convenience wrapper for geosnap.py
::
:: Usage (drag-and-drop friendly):
::   Drag your image folder onto this .bat file, OR run from cmd:
::   geosnap.bat <image_folder> <gpx_file> [--offset HOURS] [--max-gap SECS] [--verbose]
::
:: First-time setup:
::   pip install -r requirements.txt
::
setlocal

if "%~1"=="" (
    echo.
    echo  GeoSnap - Usage:
    echo    geosnap.bat ^<image_folder^> ^<gpx_file^> [--offset HOURS] [--max-gap SECS] [--verbose]
    echo.
    echo  Examples:
    echo    geosnap.bat "C:\Photos\Trip" "C:\GPS\track.gpx"
    echo    geosnap.bat "C:\Photos\Trip" "C:\GPS\track.gpx" --offset -2
    echo    geosnap.bat "C:\Photos\Trip" "C:\GPS\track.gpx" --offset 1 --max-gap 120 --verbose
    echo.
    pause
    exit /b 1
)

:: Run the Python script, passing all arguments through
python "%~dp0geosnap.py" %*

if errorlevel 1 (
    echo.
    echo ERROR: Script exited with an error. See message above.
    pause
    exit /b 1
)

echo.
pause
