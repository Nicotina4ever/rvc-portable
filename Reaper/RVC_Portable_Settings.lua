-- RVC Portable per REAPER — impostazioni (modello, indice, parametri, auto-test).
-- Condivide la configurazione con RVC_Portable.lua tramite ExtState.

local function current_dir()
  local ok, info = pcall(debug.getinfo, 1, "S")
  local source = ok and info and info.source or ""
  if source:sub(1, 1) == "@" then source = source:sub(2) end
  return source:match("^(.*)[/\\][^/\\]+$") or "."
end
local script_dir = rawget(_G, "RVC_SCRIPT_DIR") or current_dir()
local M = dofile(script_dir .. "/rvc_common.lua")

local cfg = M.load()
local updated = M.ask_settings(cfg, "RVC Portable - impostazioni")
if updated then
  M.console("Impostazioni salvate.")
  M.console("Python: " .. updated.python)
  M.console("Helper: " .. updated.helper)
  M.console("Modello: " .. updated.model)
  M.console("Indice: " .. updated.index)
  M.console(string.format("Pitch %s · metodo %s · protect %s · index rate %s · auto %s",
    updated.pitch, updated.method, updated.protect, updated.index_rate, updated.auto))
else
  M.console("Impostazioni non modificate.")
end
