@echo off
title repo2demo
cd /d "%~dp0"
echo Starting repo2demo on http://127.0.0.1:8766
echo (LLM: relay-ai via RELAYAI_API_KEY)
python main.py
pause
