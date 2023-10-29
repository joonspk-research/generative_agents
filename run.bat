@echo off

REM START THE FIRST PYTHON SCRIPT IN THE FIRST FOLDER IN A NEW WINDOW

start cmd /k "cd Add/path/to/folder && python manage.py runserver"

REM START THE SECOND PYTHON SCRIPT IN THE SECOND FOLDER IN A NEW WINDOW

start cmd /k "cd Add/path/to/folder && python reverie.py"

REM PAUSE THIS SCRIPT TO KEEP THE CMD WINDOW OPEN

pause
