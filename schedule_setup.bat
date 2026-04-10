@echo off
:: schedule_setup.bat
:: Run ONCE as Administrator (right-click → Run as administrator).
:: Creates a Windows Task Scheduler task that runs the pipeline at 4:15 PM daily.
::
:: Edit PYTHON_EXE and SCRIPT_DIR before running.

:: ── EDIT THESE TWO LINES ──────────────────────────────────────────────────────
SET PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe
SET SCRIPT_DIR=C:\Users\%USERNAME%\Documents\sector_pipeline
:: ─────────────────────────────────────────────────────────────────────────────

SET TASK_NAME=SectorDashboardPipeline
SET SCRIPT=%SCRIPT_DIR%\run_pipeline.py

echo Creating task: %TASK_NAME%
echo Python : %PYTHON_EXE%
echo Script : %SCRIPT%
echo Schedule: daily at 16:15 IST
echo.

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON_EXE%\" \"%SCRIPT%\"" ^
  /sc DAILY ^
  /st 16:15 ^
  /ru "%USERNAME%" ^
  /f /rl HIGHEST

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Task "%TASK_NAME%" created successfully.
    echo      It will run daily at 4:15 PM.
    echo.
    echo To verify:  schtasks /query /tn "%TASK_NAME%"
    echo To test now: schtasks /run /tn "%TASK_NAME%"
    echo To remove:  schtasks /delete /tn "%TASK_NAME%" /f
) ELSE (
    echo.
    echo [ERROR] Task creation failed.
    echo         Make sure you right-clicked and chose "Run as administrator".
)

pause
