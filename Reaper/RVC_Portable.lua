-- RVC Portable per REAPER — converte gli item audio selezionati con il motore
-- locale di RVC Portable e li importa in una traccia figlia (cartella), come
-- fa UVR per gli stem.
--
-- Installazione: copia la cartella "Reaper" (con rvc_common.lua) dove preferisci,
-- poi in REAPER: Actions > Show action list > New action > Load ReaScript...

local function current_dir()
  local ok, info = pcall(debug.getinfo, 1, "S")
  local source = ok and info and info.source or ""
  if source:sub(1, 1) == "@" then source = source:sub(2) end
  return source:match("^(.*)[/\\][^/\\]+$") or "."
end
local script_dir = rawget(_G, "RVC_SCRIPT_DIR") or current_dir()
local M = dofile(script_dir .. "/rvc_common.lua")

local cfg = M.load()

local function config_ok()
  return M.file_exists(cfg.python) and M.file_exists(cfg.helper) and M.file_exists(cfg.model)
end

if not config_ok() then
  M.console("Prima configurazione: indica Python, helper e modello.")
  cfg = M.ask_settings(cfg, "RVC Portable - configurazione iniziale")
  if not cfg or not config_ok() then
    M.console("Configurazione incompleta: azione annullata.")
    return
  end
end

-- ------------------------------------------------------------------ selezione
local items = {}
if reaper.CountSelectedMediaItems(0) > 0 then
  for index = 0, reaper.CountSelectedMediaItems(0) - 1 do
    items[#items + 1] = reaper.GetSelectedMediaItem(0, index)
  end
elseif reaper.CountSelectedTracks(0) > 0 then
  for index = 0, reaper.CountSelectedTracks(0) - 1 do
    local track = reaper.GetSelectedTrack(0, index)
    for item_index = 0, reaper.CountTrackMediaItems(track) - 1 do
      items[#items + 1] = reaper.GetTrackMediaItem(track, item_index)
    end
  end
end

if #items == 0 then
  M.console("Seleziona almeno un item audio (o una traccia con audio).")
  return
end

local jobs = {}
for _, item in ipairs(items) do
  local take = reaper.GetActiveTake(item)
  if take and not reaper.TakeIsMIDI(take) then
    local source = reaper.GetMediaSourceFileName(reaper.GetMediaItemTake_Source(take), "")
    if source and source ~= "" then
      jobs[#jobs + 1] = {
        item = item,
        take = take,
        track = reaper.GetMediaItem_Track(item),
        source = source,
        position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
      }
    end
  end
end

if #jobs == 0 then
  M.console("Nessun item con file audio (MIDI e sorgenti virtuali sono ignorati).")
  return
end

-- --------------------------------------------------------------------- utility
local function directory_of(path)
  return path:match("^(.*)[/\\][^/\\]+$") or "."
end

local function ensure_directory(path)
  if reaper.RecursiveCreateDirectory then
    reaper.RecursiveCreateDirectory(path, 0)
  end
end

local function take_label(job)
  local name = reaper.GetTakeName(job.take)
  if name and name ~= "" then return name end
  return "Voce"
end

local function insert_output(job, output_path)
  local track = job.track
  local track_number = math.floor(reaper.GetMediaTrackInfo_Value(track, "IP_TRACKNUMBER") or 0)
  local insert_index = math.max(0, track_number)
  reaper.InsertTrackAtIndex(insert_index, true)
  local new_track = reaper.GetTrack(0, insert_index)
  if not new_track then return false end

  reaper.GetSetMediaTrackInfo_String(new_track, "P_NAME", take_label(job) .. " [RVC]", true)
  reaper.SetMediaTrackInfo_Value(new_track, "I_CUSTOMCOLOR", 0x0A1320 | 0x1000000)

  local new_item = reaper.AddMediaItemToTrack(new_track)
  local new_take = reaper.AddTakeToMediaItem(new_item)
  local source = reaper.PCM_Source_CreateFromFile(output_path)
  if not source then
    reaper.DeleteTrack(new_track)
    return false
  end
  reaper.SetMediaItemTake_Source(new_take, source)
  local length = reaper.GetMediaSourceLength(source)
  reaper.SetMediaItemInfo_Value(new_item, "D_POSITION", job.position)
  reaper.SetMediaItemInfo_Value(new_item, "D_LENGTH", length)
  reaper.SetMediaItemInfo_Value(new_item, "I_CUSTOMCOLOR", 0x0A1320 | 0x1000000)
  reaper.GetSetMediaItemTakeInfo_String(new_take, "P_NAME", take_label(job) .. " [RVC]", true)

  if tostring(cfg.folder) == "1" then
    local depth = reaper.GetMediaTrackInfo_Value(track, "I_FOLDERDEPTH")
    if depth <= 0 then
      reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", 1)
      reaper.SetMediaTrackInfo_Value(new_track, "I_FOLDERDEPTH", -1)
    end
  end
  return true
end

-- ------------------------------------------------------------------ esecuzione
local gui_ready = M.gui_open("RVC Portable")
reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local completed = 0
local failed = 0
local total = #jobs

for index, job in ipairs(jobs) do
  local output_dir = directory_of(job.source) .. string.char(92) .. tostring(cfg.output_subdir)
  ensure_directory(output_dir)
  M.console(string.format("(%d/%d) %s", index, total, job.source))

  local command = table.concat({
    M.quote(cfg.python), "-B", M.quote(cfg.helper),
    "--input", M.quote(job.source),
    "--output-dir", M.quote(output_dir),
    "--model", M.quote(cfg.model),
    "--pitch", tostring(tonumber(cfg.pitch) or 0),
    "--method", tostring(cfg.method),
    "--protect", tostring(cfg.protect),
    "--index-rate", tostring(cfg.index_rate),
    "--formant", tostring(tonumber(cfg.formant) or 0),
    "--suffix", M.quote(cfg.suffix),
  }, " ")
  if cfg.index and cfg.index ~= "" then
    command = command .. " --index " .. M.quote(cfg.index)
  end
  if tostring(cfg.auto) == "1" then
    command = command .. string.format(" --auto --auto-seconds %s", tostring(tonumber(cfg.auto_seconds) or 10))
  end

  -- Su Windows ``io.popen`` passa da cmd.exe: un comando che inizia con una
  -- virgoletta (percorso dell'exe) viene frainteso. Uso un .bat temporaneo
  -- invocato con "call", che non inizia con una virgoletta.
  local temp_dir = os.getenv("TEMP") or os.getenv("TMP") or "."
  local batch_path = string.format("%s\\rvc_portable_%d_%d.bat", temp_dir, os.time(), index)
  local batch_handle = io.open(batch_path, "w")
  if batch_handle then
    batch_handle:write("@echo off\r\n" .. command .. " 2>&1\r\n")
    batch_handle:close()
  end
  local pipe = nil
  if batch_handle then
    pipe = io.popen('call "' .. batch_path .. '"')
  else
    pipe = io.popen(command .. " 2>&1")
  end
  local result_line = nil
  if rawget(_G, "RVC_DEBUG") then M.console("cmd: " .. command) end
  if pipe then
    for line in pipe:lines() do
      if rawget(_G, "RVC_DEBUG") then M.console("raw: " .. line) end
      local percent, stage = line:match("^PROGRESS%s+([%d%.]+)%s*(.*)$")
      if percent then
        local overall = ((index - 1) + tonumber(percent) / 100.0) / total * 100.0
        M.gui_draw(overall, string.format("RVC · %s · %d/%d", stage or "", index, total))
      else
        local auto_line = line:match("^AUTO%s+(.+)$")
        if auto_line then M.console("Auto-test: " .. auto_line) end
        local result = line:match("^RESULT%s+(.+)$")
        if result then result_line = result end
      end
    end
    pipe:close()
  else
    M.console("io.popen non disponibile")
  end
  if batch_handle then os.remove(batch_path) end

  if result_line and M.json_bool(result_line, "ok") then
    local output_path = M.json_string(result_line, "output")
    if output_path and insert_output(job, output_path) then
      completed = completed + 1
      M.console("OK: " .. output_path)
    else
      failed = failed + 1
      M.console("Output non importabile: " .. tostring(output_path))
    end
  else
    failed = failed + 1
    local message = result_line and M.json_string(result_line, "error") or "nessun risultato"
    M.console("Errore: " .. tostring(message))
  end
end

M.gui_draw(100, "RVC Portable · completato")
M.gui_close()
reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()
reaper.Undo_EndBlock("RVC Portable - voice to voice", -1)
M.console(string.format("Finito: %d convertiti, %d errori.", completed, failed))
