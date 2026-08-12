@echo off
title BVC Monitor - Actualizar datos (automatico)
cd /d C:\bvc-monitor
echo [%date% %time%] Inicio actualizacion >> data\descarga.log
C:\Python314\python.exe downloader.py >> data\descarga.log 2>&1
echo [%date% %time%] Fin actualizacion >> data\descarga.log
