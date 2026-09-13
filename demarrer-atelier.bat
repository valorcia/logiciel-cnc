@echo off
rem ---------------------------------------------------------------------------
rem  ATELIER XYZAC - double-cliquez sur ce fichier.
rem
rem  Ce fichier ne fait RIEN d'autre que trouver Python et lui passer la main.
rem  Toute la logique est dans tools\demarrer_atelier.py, qui est le meme sur
rem  Windows, macOS et Linux - et qui, lui, est eprouve. Un script systeme
rem  aurait du etre ecrit en trois versions dont deux ne seraient jamais
rem  essayees.
rem
rem  Sans accents volontairement : l'invite de commandes Windows ne les affiche
rem  pas de la meme facon selon la machine, et un message d'aide illisible est
rem  pire que pas de message.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 goto avec_py

where python >nul 2>nul
if %errorlevel%==0 goto avec_python

echo.
echo   ======================================================
echo     Python n'est pas installe sur cet ordinateur.
echo   ======================================================
echo.
echo     1. Ouvrez  https://www.python.org/downloads/
echo     2. Telechargez Python 3.12  (3.11 et 3.13 marchent aussi)
echo     3. IMPORTANT : sur le premier ecran de l'installation,
echo        cochez la case  "Add python.exe to PATH"
echo     4. Quand c'est fini, fermez cette fenetre et
echo        double-cliquez a nouveau sur ce fichier.
echo.
pause
exit /b 1

:avec_py
py tools\demarrer_atelier.py %*
goto fin

:avec_python
python tools\demarrer_atelier.py %*
goto fin

:fin
echo.
echo   ======================================================
echo     L'atelier est arrete.
echo   ======================================================
echo.
echo     Si quelque chose s'est mal passe, TOUT est note dans
echo     le fichier  demarrage.log  a cote de ce fichier-ci.
echo     Ouvrez-le avec le Bloc-notes : il survit a la
echo     fermeture de cette fenetre.
echo.
echo     Pour relancer : double-cliquez a nouveau ici.
echo.
pause
