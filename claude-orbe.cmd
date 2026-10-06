@echo off
rem Claude Code com o canal do orbe, no Windows: o mesmo que o claude-orbe.
rem O orbe de voz (orbe_pulso.py --agente claude) passa a falar com esta sessao.
setlocal
set "ORBE=%~dp0"
set "MCP=%TEMP%\orbe-mcp-%RANDOM%.json"
python "%ORBE%orbe_canal.py" --mcp-config > "%MCP%"
if errorlevel 1 (
    echo claude-orbe: o python nao esta no PATH
    exit /b 1
)
claude --mcp-config="%MCP%" --dangerously-load-development-channels=server:orbe --allowedTools=mcp__orbe__reply %*
del "%MCP%" 2>nul
