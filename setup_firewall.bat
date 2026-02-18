@echo off
:: ============================================================
::  GestureDrop - Firewall Setup
::  Double-click this file to configure Windows Firewall.
::  It will ask for Administrator permission automatically.
:: ============================================================

:: Check if already running as admin
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :run
)

:: Not admin — re-launch with UAC elevation
echo Requesting Administrator privileges...
powershell -Command "Start-Process '%~f0' -Verb RunAs"
exit /b

:run
echo.
echo  =====================================================
echo    GestureDrop - Firewall Setup
echo  =====================================================
echo.

:: Try to run with Python
where python >nul 2>&1
if %errorLevel% == 0 (
    python "%~dp0setup_firewall.py"
    goto :done
)

:: Python not found — apply rules directly with netsh
echo  [INFO] Python not found. Applying rules directly...
echo.

netsh advfirewall firewall delete rule name="GestureDrop-UDP-Discovery-IN"  >nul 2>&1
netsh advfirewall firewall delete rule name="GestureDrop-UDP-Reply-IN"      >nul 2>&1
netsh advfirewall firewall delete rule name="GestureDrop-TCP-Transfer-IN"   >nul 2>&1
netsh advfirewall firewall delete rule name="GestureDrop-UDP-Discovery-OUT" >nul 2>&1
netsh advfirewall firewall delete rule name="GestureDrop-UDP-Reply-OUT"     >nul 2>&1
netsh advfirewall firewall delete rule name="GestureDrop-TCP-Transfer-OUT"  >nul 2>&1

netsh advfirewall firewall add rule name="GestureDrop-UDP-Discovery-IN"  dir=in  action=allow protocol=UDP localport=5000 profile=private,domain enable=yes
netsh advfirewall firewall add rule name="GestureDrop-UDP-Reply-IN"      dir=in  action=allow protocol=UDP localport=5002 profile=private,domain enable=yes
netsh advfirewall firewall add rule name="GestureDrop-TCP-Transfer-IN"   dir=in  action=allow protocol=TCP localport=5001 profile=private,domain enable=yes
netsh advfirewall firewall add rule name="GestureDrop-UDP-Discovery-OUT" dir=out action=allow protocol=UDP localport=5000 profile=private,domain enable=yes
netsh advfirewall firewall add rule name="GestureDrop-UDP-Reply-OUT"     dir=out action=allow protocol=UDP localport=5002 profile=private,domain enable=yes
netsh advfirewall firewall add rule name="GestureDrop-TCP-Transfer-OUT"  dir=out action=allow protocol=TCP localport=5001 profile=private,domain enable=yes

echo.
echo  =====================================================
echo    Done! GestureDrop firewall rules applied.
echo  =====================================================

:done
echo.
pause
