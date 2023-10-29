@echo off

REM START THE FIRST PYTHON SCRIPT IN THE FIRST FOLDER IN A NEW WINDOW

start cmd /k "cd D:\generative_agents\environment\frontend_server && python manage.py runserver"

REM START THE SECOND PYTHON SCRIPT IN THE SECOND FOLDER IN A NEW WINDOW

start cmd /k "cd D:\generative_agents\reverie\backend_server && python reverie.py"

REM PAUSE THIS SCRIPT TO KEEP THE CMD WINDOW OPEN

pause
