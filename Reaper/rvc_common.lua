-- RVC Portable per REAPER — funzioni condivise (configurazione su ExtState).
-- Richiede: runtime di RVC Portable e tools/reaper_helper.py.

local M = {}

M.EXT = "RVC_PORTABLE"
M.VERSION = "1.0"

-- La cartella si ricava dal file sorgente: funziona anche quando lo script
-- viene caricato con dofile (es. harness di test) e non da un'azione registrata.
local function script_dir()
  local ok, info = pcall(debug.getinfo, 1, "S")
  local source = ok and info and info.source or ""
  if source:sub(1, 1) == "@" then source = source:sub(2) end
  local dir = source:match("^(.*)[/\\][^/\\]+$")
  if dir and dir ~= "" then return dir end
  local _, path = reaper.get_action_context()
  return path and path:match("^(.*)[/\\][^/\\]+$") or ""
end

M.script_dir = script_dir

function M.repo_root()
  local dir = script_dir()
  local separator = package.config:sub(1, 1)
  local candidate = dir
  for _ = 1, 6 do
    if M.file_exists(candidate .. separator .. "tools" .. separator .. "reaper_helper.py") then
      return candidate
    end
    local parent = candidate:match("^(.*)[/\\][^/\\]+$")
    if not parent or parent == candidate then break end
    candidate = parent
  end
  return dir:match("^(.*)[/\\][^/\\]+$") or dir
end

function M.defaults()
  local root = M.repo_root()
  local sep = package.config:sub(1, 1)
  return {
    python = root .. sep .. "runtime" .. sep .. "python.exe",
    helper = root .. sep .. "tools" .. sep .. "reaper_helper.py",
    model = "",
    index = "",
    pitch = "0",
    method = "rmvpe",
    protect = "0.33",
    index_rate = "0.3",
    formant = "0",
    auto = "0",
    auto_seconds = "10",
    suffix = "_RVC",
    folder = "1",
    output_subdir = "RVC_out",
  }
end

function M.load()
  local cfg = M.defaults()
  for key in pairs(cfg) do
    local value = reaper.GetExtState(M.EXT, key)
    if value ~= "" then cfg[key] = value end
  end
  return cfg
end

function M.save(cfg)
  for key, value in pairs(cfg) do
    reaper.SetExtState(M.EXT, key, tostring(value), true)
  end
end

function M.ask_settings(cfg, title)
  local fields = "Python,Helper,Modello .pth,Indice .index,Pitch (-24..24),Metodo (rmvpe/harvest/crepe/pm),Protezione,Index rate,Formanti (-12..12),Auto-test 0/1,Secondi auto-test,Suffisso,Crea cartella 0/1"
  local defaults = table.concat({
    cfg.python, cfg.helper, cfg.model, cfg.index, cfg.pitch, cfg.method,
    cfg.protect, cfg.index_rate, cfg.formant, cfg.auto, cfg.auto_seconds, cfg.suffix, cfg.folder,
  }, ",")
  local ok, csv = reaper.GetUserInputs(title or "RVC Portable - Impostazioni", 13, fields, defaults)
  if not ok then return nil end
  local values = {}
  for part in (csv .. ","):gmatch("(.-),") do
    table.insert(values, part)
  end
  if #values < 13 then return nil end
  cfg.python = values[1]
  cfg.helper = values[2]
  cfg.model = values[3]
  cfg.index = values[4]
  cfg.pitch = values[5]
  cfg.method = values[6]
  cfg.protect = values[7]
  cfg.index_rate = values[8]
  cfg.formant = values[9]
  cfg.auto = values[10]
  cfg.auto_seconds = values[11]
  cfg.suffix = values[12]
  cfg.folder = values[13]
  M.save(cfg)
  return cfg
end

function M.file_exists(path)
  if not path or path == "" then return false end
  local handle = io.open(path, "rb")
  if handle then handle:close(); return true end
  return false
end

function M.quote(path)
  return '"' .. tostring(path or "") .. '"'
end

function M.json_string(json, key)
  local value = json and json:match('"' .. key .. '"%s*:%s*"(.-)"')
  if not value then return nil end
  value = value:gsub("\\u(%x%x%x%x)", function(hex)
    local code = tonumber(hex, 16)
    if code and code < 128 then return string.char(code) end
    return "?"
  end)
  value = value:gsub("\\(.)", function(char)
    if char == "n" then return "\n" elseif char == "t" then return "\t" elseif char == "r" then return "\r" end
    return char
  end)
  return value
end

function M.json_bool(json, key)
  return json ~= nil and json:match('"' .. key .. '"%s*:%s*true') ~= nil
end

function M.console(message)
  local line = "[RVC] " .. tostring(message)
  reaper.ShowConsoleMsg(line .. "\n")
  local path = rawget(_G, "RVC_CONSOLE_LOG")
  if path then
    local handle = io.open(path, "a")
    if handle then
      handle:write(line .. "\n")
      handle:close()
    end
  end
end

function M.gui_open(title)
  if not gfx then return false end
  gfx.init(title or "RVC Portable", 470, 116, 0, 320, 320)
  return true
end

function M.gui_draw(percent, label)
  if not gfx then return end
  local value = math.max(0, math.min(100, tonumber(percent) or 0))
  gfx.set(0.03, 0.05, 0.09, 1)
  gfx.rect(0, 0, gfx.w, gfx.h, 1)
  gfx.set(0.91, 0.94, 1, 1)
  gfx.setfont(1, "Segoe UI", 17)
  gfx.x, gfx.y = 18, 14
  gfx.drawstr(label or "RVC Portable")
  gfx.set(0.07, 0.10, 0.19, 1)
  gfx.rect(18, 52, gfx.w - 36, 18, 1)
  gfx.set(0.43, 0.55, 1, 1)
  gfx.rect(18, 52, math.floor((gfx.w - 36) * value / 100), 18, 1)
  gfx.set(0.70, 0.76, 0.92, 1)
  gfx.setfont(1, "Segoe UI", 12)
  gfx.x, gfx.y = 18, 78
  gfx.drawstr(string.format("%.0f%%", value))
  gfx.update()
end

function M.gui_close()
  if gfx then gfx.quit() end
end

return M
