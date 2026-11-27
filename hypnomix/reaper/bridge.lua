-- hypnomix bridge for REAPER: lets `hypnomix` read and change the open project, one request at a time.
--
-- Started by `hypnomix reaper start` (REAPER runs a script given on its command line, in the running REAPER).
-- No install, no remote script, nothing changed in REAPER's settings. It keeps running in the background
-- (Actions list: "Terminate instances" or `hypnomix reaper stop` ends it).
--
-- Requests are small text files in the bridge folder: req-<id>.txt, first line the command, then key=value lines.
-- Answers are res-<id>.json. Every change is one undo step named "hypnomix: ..." (Edit > Undo takes it back).
-- Only the commands below exist: the bridge never runs code it is sent.

local DIR = HYPNOMIX_DIR or (reaper.GetResourcePath() .. "/hypnomix-bridge")
local VERSION = "1"
reaper.RecursiveCreateDirectory(DIR, 0)

-- ------------------------------------------------------------------ JSON out
local function esc(s)
  return (s:gsub('[%c"\\]', function(c)
    local m = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
    return m[c] or string.format("\\u%04x", c:byte())
  end))
end

local function json(v)
  local t = type(v)
  if t == "nil" then return "null"
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    return string.format("%.10g", v)
  elseif t == "string" then return '"' .. esc(v) .. '"'
  elseif t == "table" then
    if #v > 0 or next(v) == nil then
      local out = {}
      for i = 1, #v do out[i] = json(v[i]) end
      return "[" .. table.concat(out, ",") .. "]"
    end
    local out = {}
    for k, x in pairs(v) do out[#out + 1] = json(tostring(k)) .. ":" .. json(x) end
    return "{" .. table.concat(out, ",") .. "}"
  end
  return "null"
end

-- ------------------------------------------------------------------ helpers
local function track_of(ref)
  if ref == nil or ref == "" or ref == "master" then return reaper.GetMasterTrack(0) end
  local n = tonumber(ref)
  if n then return reaper.GetTrack(0, n) end
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, name = reaper.GetTrackName(tr)
    if name == ref then return tr end
  end
  return nil
end

local function fx_of(tr, ref)
  local n = tonumber(ref)
  if n then return n end
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, name = reaper.TrackFX_GetFXName(tr, i, "")
    if name == ref then return i end
  end
  return -1
end

local function param_of(tr, fx, ref)
  local n = tonumber(ref)
  if n then return n end
  local low = ref:lower()
  for i = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, i, "")
    if name:lower() == low then return i end
  end
  return -1
end

local function shown(tr, fx, p)
  local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
  return s
end

local function first_number(s)
  if s and s:find("%-inf") then return -math.huge end        -- "-inf" dB: the bottom of the range
  if s and s:lower():find("inf") then return math.huge end    -- "inf" (a ratio of infinity to one): the top
  local x = s and s:match("[-+]?%d*%.?%d+") or nil
  if not x then return nil end
  local v = tonumber((x:gsub("^%+", "")))                   -- Lua does not read "+0.00"
  if s:match("[%d%.]%s*[kK]") then v = v * 1000 end        -- "1.2 kHz", "1.2k"
  return v
end

-- the plug-in shows the value it plays; find the normalized position that shows `target` (values rise or fall
-- monotonically with the knob, as on every stock plug-in this is used with)
local function set_shown(tr, fx, p, target)
  local lo, hi = 0.0, 1.0
  reaper.TrackFX_SetParamNormalized(tr, fx, p, 0.0); local a = first_number(shown(tr, fx, p))
  reaper.TrackFX_SetParamNormalized(tr, fx, p, 1.0); local b = first_number(shown(tr, fx, p))
  if a == nil or b == nil then return nil, "the plug-in does not show this value as a number" end
  local rising = b >= a
  for _ = 1, 40 do
    local mid = (lo + hi) / 2
    reaper.TrackFX_SetParamNormalized(tr, fx, p, mid)
    local v = first_number(shown(tr, fx, p))
    if v == nil then break end
    if (v < target) == rising then lo = mid else hi = mid end
  end
  -- whichever end of the last step shows the value nearest the target (displays round)
  local best, bestd = (lo + hi) / 2, math.huge
  for _, x in ipairs({ lo, (lo + hi) / 2, hi }) do
    reaper.TrackFX_SetParamNormalized(tr, fx, p, x)
    local v = first_number(shown(tr, fx, p))
    if v and math.abs(v - target) < bestd then best, bestd = x, math.abs(v - target) end
  end
  reaper.TrackFX_SetParamNormalized(tr, fx, p, best)
  return shown(tr, fx, p)
end

-- ------------------------------------------------------------------ commands
local C = {}

function C.ping()
  local _, path = reaper.EnumProjects(-1, "")
  return { bridge = VERSION, reaper = reaper.GetAppVersion(), project = path,
           tempo = reaper.Master_GetTempo(), tracks = reaper.CountTracks(0), sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) }
end

function C.tracks()
  local out = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, name = reaper.GetTrackName(tr)
    local fx = {}
    for k = 0, reaper.TrackFX_GetCount(tr) - 1 do
      local _, n = reaper.TrackFX_GetFXName(tr, k, "")
      fx[#fx + 1] = { name = n, on = reaper.TrackFX_GetEnabled(tr, k) }
    end
    out[#out + 1] = { index = i, name = name, guid = reaper.GetTrackGUID(tr), fx = fx,
                      volume = reaper.GetMediaTrackInfo_Value(tr, "D_VOL"), pan = reaper.GetMediaTrackInfo_Value(tr, "D_PAN"),
                      mute = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1,
                      depth = reaper.GetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH") }
  end
  return out
end

function C.fx_list(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local out = {}
  for k = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, n = reaper.TrackFX_GetFXName(tr, k, "")
    out[#out + 1] = { index = k, name = n, on = reaper.TrackFX_GetEnabled(tr, k) }
  end
  return out
end

function C.fx_installed(a)
  local out, i, want = {}, 0, (a.filter or ""):lower()
  while true do
    local ok, name = reaper.EnumInstalledFX(i)
    if not ok then break end
    if want == "" or name:lower():find(want, 1, true) then out[#out + 1] = name end
    i = i + 1
  end
  return out
end

function C.add_fx(a)
  local tr = track_of(a.track)
  if not tr then return nil, "no track " .. tostring(a.track) end
  local fx = reaper.TrackFX_AddByName(tr, a.name, false, -1)
  if fx < 0 then return nil, "REAPER has no plug-in called " .. a.name end
  return { fx = fx, name = select(2, reaper.TrackFX_GetFXName(tr, fx, "")) }
end

function C.fx_params(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  local out = {}
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
    out[#out + 1] = { index = p, name = name, value = reaper.TrackFX_GetParamNormalized(tr, fx, p), shown = shown(tr, fx, p) }
  end
  return out
end

function C.set_param(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  local p = param_of(tr, fx, a.param); if p < 0 then return nil, "no parameter " .. a.param end
  if a.shown then
    local s, err = set_shown(tr, fx, p, tonumber(a.shown))
    if not s then return nil, err end
    return { param = p, shown = s }
  end
  reaper.TrackFX_SetParamNormalized(tr, fx, p, tonumber(a.value))
  return { param = p, shown = shown(tr, fx, p) }
end

function C.set_named(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  local ok = reaper.TrackFX_SetNamedConfigParm(tr, fx, a.key, a.value)
  local _, now = reaper.TrackFX_GetNamedConfigParm(tr, fx, a.key)
  return { ok = ok, now = now }
end

function C.get_named(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  local ok, now = reaper.TrackFX_GetNamedConfigParm(tr, fx, a.key)
  return { ok = ok, value = now }
end

function C.fx_enable(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  reaper.TrackFX_SetEnabled(tr, fx, a.on == "1")
  return { on = reaper.TrackFX_GetEnabled(tr, fx) }
end

function C.set_track(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  if a.volume_db then reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 10 ^ (tonumber(a.volume_db) / 20)) end
  if a.pan then reaper.SetMediaTrackInfo_Value(tr, "D_PAN", tonumber(a.pan)) end
  if a.mute then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", tonumber(a.mute)) end
  return { volume = reaper.GetMediaTrackInfo_Value(tr, "D_VOL"), pan = reaper.GetMediaTrackInfo_Value(tr, "D_PAN") }
end

-- render the master output of a time range to a file (the project's own render settings are put back after)
function C.render_master(a)
  local keys = { "RENDER_FILE", "RENDER_PATTERN", "RENDER_FORMAT" }
  local nums = { "RENDER_SETTINGS", "RENDER_BOUNDSFLAG", "RENDER_STARTPOS", "RENDER_ENDPOS", "RENDER_SRATE", "RENDER_CHANNELS" }
  local keep_s, keep_n = {}, {}
  for _, k in ipairs(keys) do keep_s[k] = select(2, reaper.GetSetProjectInfo_String(0, k, "", false)) end
  for _, k in ipairs(nums) do keep_n[k] = reaper.GetSetProjectInfo(0, k, 0, false) end
  local dir, file = a.path:match("^(.*)/([^/]+)%.wav$")
  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", dir, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", file, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdyAAAQ==", true)     -- WAV, 32-bit float
  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, true)                       -- master mix
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, true)                     -- custom time range
  reaper.GetSetProjectInfo(0, "RENDER_STARTPOS", tonumber(a.start), true)
  reaper.GetSetProjectInfo(0, "RENDER_ENDPOS", tonumber(a["end"]), true)
  reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", 2, true)
  reaper.Main_OnCommand(42230, 0)                                               -- render, auto-close
  for _, k in ipairs(keys) do reaper.GetSetProjectInfo_String(0, k, keep_s[k], true) end
  for _, k in ipairs(nums) do reaper.GetSetProjectInfo(0, k, keep_n[k], true) end
  return { path = a.path, exists = reaper.file_exists(a.path) }
end

-- route a plug-in's input or output pin to channels (mask: 1 = channel 1, 2 = channel 2, 0 = none); channels no
-- output pin writes pass through unchanged
function C.set_pins(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  local ok = reaper.TrackFX_SetPinMappings(tr, fx, tonumber(a.output), tonumber(a.pin), tonumber(a.mask), 0)
  return { ok = ok }
end

function C.remove_fx(a)
  local tr = track_of(a.track); if not tr then return nil, "no track" end
  local fx = fx_of(tr, a.fx); if fx < 0 then return nil, "no such plug-in on the track" end
  reaper.TrackFX_Delete(tr, fx)
  return { removed = fx }
end

-- a new, empty project tab (for checks that must not touch the person's project); close_tab closes only a tab
-- this bridge opened, and never saves it
-- the tabs this bridge opened, remembered for the whole REAPER session (a restarted bridge still knows them)
local function opened_tabs()
  local t = {}
  for id in (reaper.GetExtState("hypnomix", "tabs") or ""):gmatch("[^,]+") do t[id] = true end
  return t
end

function C.new_tab()
  reaper.Main_OnCommand(40859, 0)
  local proj = reaper.EnumProjects(-1, "")
  local t = opened_tabs(); t[tostring(proj)] = true
  local ids = {}; for id in pairs(t) do ids[#ids + 1] = id end
  reaper.SetExtState("hypnomix", "tabs", table.concat(ids, ","), false)
  return { tab = tostring(proj) }
end

function C.open_project(a)        -- a project in a NEW tab (closable with close_tab, which never saves it)
  reaper.Main_OnCommand(40859, 0)
  reaper.Main_openProject("noprompt:" .. a.path)
  local proj = reaper.EnumProjects(-1, "")
  local t = opened_tabs(); t[tostring(proj)] = true
  local ids = {}; for id in pairs(t) do ids[#ids + 1] = id end
  reaper.SetExtState("hypnomix", "tabs", table.concat(ids, ","), false)
  return { tracks = reaper.CountTracks(0) }
end

function C.add_track(a)
  local n = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(n, true)
  local tr = reaper.GetTrack(0, n)
  if a.name then reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", a.name, true) end
  if a.file then
    local it = reaper.AddMediaItemToTrack(tr)
    local tk = reaper.AddTakeToMediaItem(it)
    local src = reaper.PCM_Source_CreateFromFile(a.file)
    reaper.SetMediaItemTake_Source(tk, src)
    reaper.SetMediaItemInfo_Value(it, "D_POSITION", tonumber(a.pos or 0))
    reaper.SetMediaItemInfo_Value(it, "D_LENGTH", reaper.GetMediaSourceLength(src))
    reaper.UpdateArrange()
  end
  return { index = n }
end

-- ------------------------------------------------------------------ teacher mode: starting a song
function C.teach_tempo(a)
  reaper.SetCurrentBPM(0, tonumber(a.bpm), true)
  return { bpm = reaper.Master_GetTempo() }
end

function C.teach_click(a)         -- Options: Toggle metronome (40364)
  local on = reaper.GetToggleCommandState(40364) == 1
  if a.on ~= nil and (a.on == "1") ~= on then reaper.Main_OnCommand(40364, 0) end
  return { on = reaper.GetToggleCommandState(40364) == 1 }
end

function C.teach_track(a)         -- a new track, armed: input = mono interface input N (1-based) or "midi"
  local n = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(n, true)
  local tr = reaper.GetTrack(0, n)
  if a.name then reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", a.name, true) end
  if a.input == "midi" then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", 6112)     -- 4096 + 63 * 32: every MIDI input, every channel
  elseif a.input then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", math.max(0, (tonumber(a.input) or 1) - 1))
  end
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", tonumber(a.monitor or 1))
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", a.arm == "0" and 0 or 1)
  reaper.TrackList_AdjustWindows(false)
  return { index = n }
end

function C.teach_drums(a)         -- a track with ReaSynDr and a looped MIDI item: notes = "pitch,start,len,vel;..." in beats
  local n = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(n, true)
  local tr = reaper.GetTrack(0, n)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", a.name or "Drums", true)
  local fx = reaper.TrackFX_AddByName(tr, "ReaSynDr (Cockos)", false, -1)
  local beats = tonumber(a.beats or 16)
  local it = reaper.CreateNewMIDIItemInProj(tr, 0, beats, true)
  local tk = reaper.GetActiveTake(it)
  local count = 0
  for p, s, d, v in (a.notes or ""):gmatch("(%d+),([%d.]+),([%d.]+),(%d+)") do
    local s0 = reaper.MIDI_GetPPQPosFromProjQN(tk, tonumber(s))
    local s1 = reaper.MIDI_GetPPQPosFromProjQN(tk, tonumber(s) + tonumber(d))
    reaper.MIDI_InsertNote(tk, false, false, s0, s1, 0, tonumber(p), tonumber(v), true)
    count = count + 1
  end
  reaper.MIDI_Sort(tk)
  reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", a.name or "Drums", true)
  reaper.SetMediaItemInfo_Value(it, "B_LOOPSRC", 1)
  reaper.UpdateArrange()
  return { index = n, fx = fx, notes = count }
end

function C.close_tab()
  local proj = reaper.EnumProjects(-1, "")
  if not opened_tabs()[tostring(proj)] then return nil, "the open tab was not made by HypnoMix: not closing it" end
  -- closing a changed tab asks "save?" (a dialog the bridge would wait on): save a throwaway copy, reload it into
  -- this tab without a prompt (now unchanged), then close
  local scratch = DIR .. "/scratch.rpp"
  reaper.Main_SaveProjectEx(proj, scratch, 0)
  reaper.Main_openProject("noprompt:" .. scratch)
  reaper.Main_OnCommand(40860, 0)
  return { closed = true }
end

-- ------------------------------------------------------------------ Hypnomix Probe / Main (JSFX) relay
-- The probes write their 20 values per 100 ms block into shared memory (gmem "hypnomix", see hypnomix_meter.jsfx-inc);
-- each is given a slot here, and every new block is kept in a ring for the app to fetch (`probe_blocks since=N`).
local GM_BASE, GM_NV, GM_RING = 64, 20, 8
local GM_REC = GM_NV + 4
local GM_BLK = 2 + GM_RING * GM_REC
local probes = { slots = {}, next_slot = 0, found = {}, last = {}, buf = {}, seq = 0, scanned = 0 }
local CARD_KEYS = { ["What it is"] = "role", ["Priority"] = "priority", ["Protect"] = "protect", ["Genre"] = "genre",
                    ["Key"] = "key", ["Scale"] = "scale", ["Limiter"] = "mode", ["Target LUFS"] = "target",
                    ["Ceiling dBTP"] = "ceiling", ["Amount %"] = "amount" }
local attached = false

local function probe_scan()
  if not attached then reaper.gmem_attach("hypnomix"); attached = true end
  local found = {}
  local function look(tr, is_main)
    for k = 0, reaper.TrackFX_GetCount(tr) - 1 do
      local _, n = reaper.TrackFX_GetFXName(tr, k, "")
      local kind = n:find("Hypnomix Main", 1, true) and "main" or (n:find("Hypnomix Probe", 1, true) and "probe" or nil)
      if kind then
        local key = is_main and "master" or reaper.GetTrackGUID(tr)
        if not probes.slots[key] then probes.slots[key] = probes.next_slot; probes.next_slot = probes.next_slot + 1 end
        local slot = probes.slots[key]
        local sp = -1
        for p = 0, reaper.TrackFX_GetNumParams(tr, k) - 1 do
          local _, pn = reaper.TrackFX_GetParamName(tr, k, p, "")
          if pn:find("slot", 1, true) then sp = p end
        end
        if sp >= 0 and math.floor(reaper.TrackFX_GetParam(tr, k, sp) + 0.5) ~= slot then
          reaper.TrackFX_SetParam(tr, k, sp, slot)
        end
        found[#found + 1] = { tr = tr, fx = k, slot = slot, main = is_main or kind == "main", sp = sp }
        break                                           -- one probe per track: the first (last in chain is advised)
      end
    end
  end
  look(reaper.GetMasterTrack(0), true)
  for i = 0, reaper.CountTracks(0) - 1 do look(reaper.GetTrack(0, i), false) end
  probes.found = found
end

local function probe_name(f)
  if f.main then return "Main" end
  local _, n = reaper.GetTrackName(f.tr)
  return n
end

local function probe_poll()
  local now = reaper.time_precise()
  if now - probes.scanned > 1.0 then probe_scan(); probes.scanned = now end
  for _, f in ipairs(probes.found) do
    local base = GM_BASE + f.slot * GM_BLK
    local cnt = reaper.gmem_read(base)
    if probes.last[f.slot] == nil then probes.last[f.slot] = cnt end   -- first sight: start from now
    local last = probes.last[f.slot]
    if cnt < last then last = cnt end                          -- the effect was reloaded
    if cnt - last > GM_RING then last = cnt - GM_RING end      -- fell behind: the ring keeps the newest RING blocks
    if cnt > last then
      local vol = reaper.GetMediaTrackInfo_Value(f.tr, "D_VOL")
      local fader = vol > 0 and 20 * math.log(vol, 10) or -120
      local pan = reaper.GetMediaTrackInfo_Value(f.tr, "D_PAN")
      local sr = reaper.gmem_read(base + 1)
      local name = probe_name(f)
      for c = last, cnt - 1 do
        local o = base + 2 + (c % GM_RING) * GM_REC
        local vals = {}
        for i = 0, GM_NV - 1 do vals[#vals + 1] = reaper.gmem_read(o + 4 + i) end
        probes.seq = probes.seq + 1
        probes.buf[#probes.buf + 1] = { seq = probes.seq, id = 900000 + f.slot, name = name, main = f.main,
                                        beat = reaper.gmem_read(o), playing = reaper.gmem_read(o + 1),
                                        fader = fader, pan = pan, sr = sr, vals = vals }
      end
      probes.last[f.slot] = cnt
      while #probes.buf > 4000 do table.remove(probes.buf, 1) end
    end
  end
end

function C.probe_debug(a)       -- what the relay sees: probes found, their slots, and the shared memory at each
  if not attached then reaper.gmem_attach("hypnomix"); attached = true end
  local out = { err = probes.err, seq = probes.seq, buffered = #probes.buf, version = reaper.gmem_read(0), probes = {} }
  for _, f in ipairs(probes.found) do
    local base = GM_BASE + f.slot * GM_BLK
    out.probes[#out.probes + 1] = { name = probe_name(f), slot = f.slot, sp = f.sp, count = reaper.gmem_read(base),
                                     sr = reaper.gmem_read(base + 1), last = probes.last[f.slot] }
  end
  return out
end

function C.transport(a)
  if a.at then reaper.SetEditCurPos(tonumber(a.at), true, true) end
  if a.go == "play" then reaper.OnPlayButton() elseif a.go == "stop" then reaper.OnStopButton()
  elseif a.go == "record" then reaper.CSurf_OnRecord() end
  return { state = reaper.GetPlayState(), pos = reaper.GetPlayPosition() }
end


-- ------------------------------------------------------------------ Record and review before export
-- Hypnomix Main's button counts presses in gmem[8]; the state Main shows is gmem[9] (0 idle, 1 recording,
-- 2 rendering, 3 no app, 4 reviewing in the app, 5 under a second played: nothing sent, 6 the review failed) and gmem[10] the seconds recorded. While recording, the probes
-- listen as usual; on stop the app renders the master for exactly the stretch that played (`render_master`) and
-- reviews it. The events go to the app's relay with `probe_blocks rec=1` (one reader: the app that owns the probes).
local GM_PRESS, GM_STATE, GM_SECS = 8, 9, 10
local rec = { on = false, start = 0, last = 0, began = 0, seen = false, presses = nil, events = {}, fed = 0 }

local function rec_begin()
  local playing = reaper.GetPlayState() & 1 == 1
  rec.start = playing and reaper.GetPlayPosition() or reaper.GetCursorPosition()
  rec.last, rec.on, rec.began, rec.seen = rec.start, true, reaper.time_precise(), playing
  if not playing then reaper.OnPlayButton() end
  reaper.gmem_write(GM_STATE, 1); reaper.gmem_write(GM_SECS, 0)
  rec.events[#rec.events + 1] = { ev = "start", pos = rec.start }
end

local function rec_finish(stop_transport)
  rec.on = false
  if stop_transport and reaper.GetPlayState() & 1 == 1 then reaper.OnStopButton() end
  if rec.last - rec.start < 1.0 then reaper.gmem_write(GM_STATE, 5); return false end   -- nothing worth reviewing
  reaper.gmem_write(GM_STATE, 2)
  rec.events[#rec.events + 1] = { ev = "stop", start = rec.start, ["end"] = rec.last }
  return true
end

local function rec_toggle()
  if rec.on then return rec_finish(true) and "stop" or "short" end
  if reaper.time_precise() - rec.fed > 3 then          -- nobody to review it: the app's relay is not polling
    reaper.gmem_write(GM_STATE, 3); return "no app"
  end
  rec_begin(); return "start"
end

local function rec_poll()
  if not attached then reaper.gmem_attach("hypnomix"); attached = true end
  local p = reaper.gmem_read(GM_PRESS)
  if rec.presses == nil then rec.presses = p end
  if p ~= rec.presses then rec.presses = p; rec_toggle() end
  if rec.on then
    if reaper.GetPlayState() & 1 == 1 then
      rec.seen = true
      local pos = reaper.GetPlayPosition()
      if pos > rec.last then rec.last = pos end         -- loop playback wraps back: keep the furthest point
      reaper.gmem_write(GM_SECS, rec.last - rec.start)
    elseif (rec.seen and reaper.time_precise() - rec.began > 0.5) or reaper.time_precise() - rec.began > 3 then
      rec_finish(false)                                 -- REAPER was stopped (or reached the end, or never started)
    end
  end
end

function C.record()             -- the same as pressing Main's button
  if not attached then reaper.gmem_attach("hypnomix"); attached = true end
  return { did = rec_toggle(), recording = rec.on, start = rec.start, ["end"] = rec.last }
end

function C.rec_status(a)        -- the app says how it went; 3 (no app) or 6 (it failed) also stops a recording
  local code = tonumber(a.code) or 0
  if (code == 3 or code == 6) and rec.on then rec.on = false; if reaper.GetPlayState() & 1 == 1 then reaper.OnStopButton() end end
  reaper.gmem_write(GM_STATE, code)
  return { state = code }
end

function C.probe_blocks(a)
  if a.rec == "1" then rec.fed = reaper.time_precise() end   -- a relay that reviews recordings
  local since = tonumber(a.since or "0") or 0
  local out = {}
  for _, b in ipairs(probes.buf) do if b.seq > since then out[#out + 1] = b end end
  local meta, names = {}, {}
  for _, f in ipairs(probes.found) do
    local params = {}
    for p = 0, reaper.TrackFX_GetNumParams(f.tr, f.fx) - 1 do
      if p ~= f.sp then
        local _, pn = reaper.TrackFX_GetParamName(f.tr, f.fx, p, "")
        local key = CARD_KEYS[pn]
        if key then
          local _, shown = reaper.TrackFX_GetFormattedParamValue(f.tr, f.fx, p, "")
          params[key] = tonumber(shown) or shown
        end
      end
    end
    meta[#meta + 1] = { id = 900000 + f.slot, name = probe_name(f), main = f.main, params = params }
  end
  for i = 0, reaper.CountTracks(0) - 1 do names[#names + 1] = select(2, reaper.GetTrackName(reaper.GetTrack(0, i))) end
  local evs = {}
  if a.rec == "1" then evs = rec.events; rec.events = {} end
  return { seq = probes.seq, blocks = out, meta = meta, names = names, rec = evs }
end

-- ------------------------------------------------------------------ the Hypnomix panel (review and A/B)
-- A window drawn here with REAPER's own gfx; `hypnomix reaper review` keeps it in step with the app (Lua cannot
-- make web requests): it sets what to show (`panel_set`) and collects the clicks (`panel_events`).
local panel = { open = false, st = {}, events = {}, buttons = {}, was_down = false, flash = "", flash_until = 0,
                mode = "review", sliders = {}, drag = nil, hold = {} }
local PW, PH = 520, 236
local AW, AH = 640, 380                 -- the Align panel

function C.panel_open(a)                -- mode=align: the Hypnomix Align panel (`hypnomix reaper align`) in the same window
  local mode = (a and a.mode) or "review"
  if panel.open and panel.mode ~= mode then gfx.quit(); panel.open = false end
  if not panel.open then
    if mode == "align" then gfx.init("HypnoMix Align", AW, AH) else gfx.init("HypnoMix", PW, PH) end
    panel.open, panel.mode, panel.st, panel.events = true, mode, {}, {}
  end
  return { open = true, mode = panel.mode }
end

function C.panel_close()
  if panel.open then gfx.quit(); panel.open = false end
  return { open = false }
end

function C.panel_set(a)
  local now = reaper.time_precise()
  for k, v in pairs(a) do
    if not (panel.hold[k] and now < panel.hold[k]) then panel.st[k] = v end   -- a slider just moved here wins
  end
  if a.flash and a.flash ~= "" then panel.flash = a.flash; panel.flash_until = reaper.time_precise() + 4 end
  return { open = panel.open }
end

function C.panel_events()
  local ev = panel.events
  panel.events = {}
  return { open = panel.open, events = ev }
end

function C.jump(a)       -- select the finding's track, put the cursor and the time selection around the spot
  local tr = track_of(a.track)
  if tr then reaper.SetOnlyTrackSelected(tr); reaper.Main_OnCommand(40913, 0) end   -- and scroll it into view
  if a.start then
    local s, e = tonumber(a.start), tonumber(a["end"] or a.start)
    reaper.GetSet_LoopTimeRange(true, false, s, e, false)
    reaper.SetEditCurPos(s, true, true)
  end
  return { track = tr ~= nil }
end

local function wrap(text, width, max_lines)
  local lines, line = {}, ""
  for word in tostring(text or ""):gmatch("%S+") do
    local try = line == "" and word or (line .. " " .. word)
    if gfx.measurestr(try) > width and line ~= "" then
      lines[#lines + 1] = line; line = word
      if #lines >= max_lines then return lines end
    else line = try end
  end
  if line ~= "" and #lines < max_lines then lines[#lines + 1] = line end
  return lines
end

local function button(label, x, y, on, action, w)
  w = w or (gfx.measurestr(label) + 16)
  gfx.set(on and 0.56 or 0.24, on and 0.78 or 0.24, on and 0.64 or 0.25, 1)
  gfx.rect(x, y, w, 22, 1)
  gfx.set(on and 0.1 or 0.93, on and 0.1 or 0.91, on and 0.1 or 0.87, 1)
  gfx.x, gfx.y = x + 8, y + 5
  gfx.drawstr(label)
  panel.buttons[#panel.buttons + 1] = { x = x, y = y, w = w, h = 22, action = action }
  return x + w + 6
end

local function panel_draw()
  if gfx.getchar() < 0 then panel.open = false; panel.events[#panel.events + 1] = "closed"; return end
  local st = panel.st
  panel.buttons = {}
  gfx.set(0.13, 0.125, 0.11, 1); gfx.rect(0, 0, gfx.w, gfx.h, 1)
  gfx.setfont(1, "Arial", 14, string.byte("b"))
  gfx.set(0.93, 0.91, 0.87, 1); gfx.x, gfx.y = 10, 8; gfx.drawstr("HYPNOMIX")
  gfx.setfont(1, "Arial", 13)
  gfx.set(0.63, 0.6, 0.56, 1); gfx.x, gfx.y = 90, 9
  gfx.drawstr(st.status or "")
  gfx.set(0.93, 0.91, 0.87, 1); gfx.x, gfx.y = 10, 30
  gfx.drawstr(st.head or "")
  local y = 50
  gfx.set(0.85, 0.82, 0.77, 1)
  for _, l in ipairs(wrap(st.problem, gfx.w - 20, 3)) do gfx.x, gfx.y = 10, y; gfx.drawstr(l); y = y + 16 end
  gfx.set(0.56, 0.78, 0.64, 1)
  for _, l in ipairs(wrap(st.fix, gfx.w - 20, 2)) do gfx.x, gfx.y = 10, y; gfx.drawstr(l); y = y + 16 end
  y = math.max(y + 6, 136)
  local x = 10
  x = button("Prev", x, y, false, "prev"); x = button("Next", x, y, false, "next"); x = button("Next open", x, y, false, "next_open")
  x = button("Approve", x + 10, y, st.decision == "approve", "approve"); x = button("Skip", x, y, st.decision == "skip", "skip")
  if st.ab == "1" then
    y = y + 30; x = 10
    if st.blind == "1" then
      x = button("X", x, y, st.heard == "X", "X"); x = button("Y", x, y, st.heard == "Y", "Y")
      x = button("I like X", x + 10, y, false, "like_X"); x = button("I like Y", x, y, false, "like_Y")
    else
      x = button("A · now", x, y, st.state == "A", "A"); x = button("B · fix", x, y, st.state == "B", "B")
      x = button("Blind", x + 10, y, false, "blind")
    end
    x = button(st.match == "1" and "Match on" or "Match off", x + 10, y, st.match == "1", "match")
  end
  if reaper.time_precise() < panel.flash_until then
    gfx.set(0.98, 0.8, 0.45, 1); gfx.x, gfx.y = 10, gfx.h - 20; gfx.drawstr(panel.flash)
  end
  local down = gfx.mouse_cap & 1 == 1
  if panel.was_down and not down then                    -- a click: on release, where the button is
    for _, b in ipairs(panel.buttons) do
      if gfx.mouse_x >= b.x and gfx.mouse_x <= b.x + b.w and gfx.mouse_y >= b.y and gfx.mouse_y <= b.y + b.h then
        panel.events[#panel.events + 1] = b.action
      end
    end
  end
  panel.was_down = down
  gfx.update()
end


-- ------------------------------------------------------------------ the Hypnomix Align panel
-- `hypnomix reaper align` drives it like the review panel: it sets what to show and collects the clicks. The
-- sliders are moved here (dragged left / right) and reported as "set:<name>=<value>" when let go.
function C.align_where()       -- what the panel picks from: selected tracks, the time selection, the edit cursor
  local names = {}
  for i = 0, reaper.CountSelectedTracks(0) - 1 do
    names[#names + 1] = select(2, reaper.GetTrackName(reaper.GetSelectedTrack(0, i)))
  end
  local s, e = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
  local _, path = reaper.EnumProjects(-1, "")
  return { tracks = names, sel_start = s, sel_end = e, cursor = reaper.GetCursorPosition(), project = path or "",
           dirty = reaper.IsProjectDirty(0), tempo = reaper.Master_GetTempo() }
end

local SLIDERS = { { "tight", "Tight", 0, 1, "%.0f%%", 100 }, { "pitch", "Pitch", 0, 1, "%.0f%%", 100 },
                  { "vibrato", "Vibrato", 0, 1, "%.0f%%", 100 }, { "formant", "Formant", -3, 3, "%+.1f st", 1 } }

local function slider(def, x, y, w)
  local key, label, lo, hi, f, k = table.unpack(def)
  local v = tonumber(panel.st[key] or lo) or lo
  gfx.set(0.63, 0.6, 0.56, 1); gfx.x, gfx.y = x, y; gfx.drawstr(label)
  local bx, by, bw = x + 58, y + 2, w - 58
  gfx.set(0.24, 0.24, 0.25, 1); gfx.rect(bx, by, bw, 12, 1)
  local z = (lo < 0) and (bx + bw * (0 - lo) / (hi - lo)) or bx
  local px = bx + bw * (v - lo) / (hi - lo)
  gfx.set(0.98, 0.72, 0.3, (v == 0 and lo >= 0) and 0.35 or 1)
  gfx.rect(math.min(z, px), by, math.max(2, math.abs(px - z)), 12, 1)
  gfx.set(0.93, 0.91, 0.87, 1); gfx.x, gfx.y = bx + bw + 6, y
  gfx.drawstr(string.format(f, v * k))
  panel.sliders[#panel.sliders + 1] = { key = key, x = bx, y = by - 3, w = bw, h = 18, lo = lo, hi = hi }
end

local function lane(name, before, after, x, y, w, h)
  gfx.set(0.18, 0.17, 0.16, 1); gfx.rect(x, y, w, h, 1)
  local function draw(list, r, g_, b, alpha)
    local pts = {}
    for v in tostring(list or ""):gmatch("[^,]+") do pts[#pts + 1] = tonumber(v) or -60 end
    if #pts < 2 then return end
    gfx.set(r, g_, b, alpha)
    for i = 2, #pts do
      local x0, x1 = x + w * (i - 2) / (#pts - 1), x + w * (i - 1) / (#pts - 1)
      local y0, y1 = y + h - 2 - (h - 4) * (pts[i - 1] + 60) / 60, y + h - 2 - (h - 4) * (pts[i] + 60) / 60
      gfx.line(x0, y0, x1, y1, 1)
    end
  end
  draw(before, 0.6, 0.6, 0.6, 0.9)
  draw(after, 0.98, 0.72, 0.3, 1)
  gfx.set(0.93, 0.91, 0.87, 0.9); gfx.x, gfx.y = x + 4, y + 2; gfx.drawstr(name)
end

local function align_draw()
  if gfx.getchar() < 0 then panel.open = false; panel.events[#panel.events + 1] = "closed"; return end
  local st = panel.st
  panel.buttons, panel.sliders = {}, {}
  gfx.set(0.13, 0.125, 0.11, 1); gfx.rect(0, 0, gfx.w, gfx.h, 1)
  gfx.setfont(1, "Arial", 14, string.byte("b"))
  gfx.set(0.93, 0.91, 0.87, 1); gfx.x, gfx.y = 10, 8; gfx.drawstr("HYPNOMIX ALIGN")
  gfx.setfont(1, "Arial", 13)
  gfx.set(0.63, 0.6, 0.56, 1); gfx.x, gfx.y = 140, 9; gfx.drawstr(st.status or "")
  local busy = st.busy == "1"
  -- who
  local y = 32
  local x = button("Guide ←", 10, y, false, "guide")
  gfx.set(0.93, 0.91, 0.87, 1); gfx.x, gfx.y = x, y + 5; gfx.drawstr(st.guide ~= "" and st.guide or "(select the guide track)")
  y = 58
  x = button("+ Part", 10, y, false, "part"); x = button("Clear", x, y, false, "clear")
  gfx.set(0.93, 0.91, 0.87, 1)
  local pl = wrap(st.parts ~= "" and st.parts or "(select a part, + Part; repeat)", gfx.w - x - 10, 1)
  gfx.x, gfx.y = x, y + 5; gfx.drawstr(pl[1] or "")
  -- where
  y = 86
  x = button("Range: selection", 10, y, st.range_on == "1", "range")
  x = button("Song", x, y, st.range_on ~= "1", "song")
  x = button("Protect", x + 10, y, false, "protect"); x = button("Sync here", x, y, false, "sync")
  x = button("Clear marks", x, y, false, "clear_marks")
  gfx.set(0.63, 0.6, 0.56, 1); gfx.x, gfx.y = 10, y + 28
  gfx.drawstr(st.where or "")
  -- how
  y = 136
  local sw = math.floor((gfx.w - 30) / 2)
  slider(SLIDERS[1], 10, y, sw - 60); slider(SLIDERS[2], 20 + sw, y, sw - 60)
  slider(SLIDERS[3], 10, y + 22, sw - 60); slider(SLIDERS[4], 20 + sw, y + 22, sw - 60)
  y = 186
  x = button("Preset: " .. (st.preset ~= "" and st.preset or "none"), 10, y, st.preset ~= "", "preset")
  x = button(st.takes == "1" and "Timing: takes" or "Timing: markers", x + 10, y, st.takes == "1", "takes")
  x = button(st.write == "1" and "Write project: on" or "Write project: off", x, y, st.write == "1", "write")
  x = button(busy and "Aligning…" or "Align", x + 10, y, busy, "align")
  if st.can_open == "1" then x = button("Open project", x, y, false, "open") end
  gfx.set(0.85, 0.82, 0.77, 1); gfx.x, gfx.y = 10, y + 28
  gfx.drawstr((wrap(st.result or "", gfx.w - 20, 1))[1] or "")
  -- lanes: grey before, amber after
  local top, n = 236, 0
  local lanes = {}
  for l in tostring(st.lanes or ""):gmatch("[^|]+") do lanes[#lanes + 1] = l end
  if #lanes > 0 then
    local lh = math.min(34, math.floor((gfx.h - top - 26) / #lanes) - 3)
    for _, l in ipairs(lanes) do
      local name, before, after = l:match("^([^;]*);([^;]*);?(.*)$")
      lane(name or "", before, after, 10, top + n * (lh + 3), gfx.w - 20, lh); n = n + 1
    end
  end
  if reaper.time_precise() < panel.flash_until then
    gfx.set(0.98, 0.8, 0.45, 1); gfx.x, gfx.y = 10, gfx.h - 20; gfx.drawstr(panel.flash)
  end
  -- mouse: a slider follows a drag; a button fires on release
  local down = gfx.mouse_cap & 1 == 1
  local mx, my = gfx.mouse_x, gfx.mouse_y
  if down and not panel.was_down then
    for _, s in ipairs(panel.sliders) do
      if mx >= s.x - 4 and mx <= s.x + s.w + 4 and my >= s.y and my <= s.y + s.h then panel.drag = s end
    end
  end
  if panel.drag then
    local s = panel.drag
    local v = s.lo + (s.hi - s.lo) * math.max(0, math.min(1, (mx - s.x) / s.w))
    v = (s.hi - s.lo) > 2 and math.floor(v * 10 + 0.5) / 10 or math.floor(v * 100 + 0.5) / 100
    panel.st[s.key] = tostring(v)
    panel.hold[s.key] = reaper.time_precise() + 1.5
    if not down then
      panel.events[#panel.events + 1] = "set:" .. s.key .. "=" .. tostring(v)
      panel.drag = nil
    end
  elseif panel.was_down and not down then
    for _, b in ipairs(panel.buttons) do
      if mx >= b.x and mx <= b.x + b.w and my >= b.y and my <= b.y + b.h then
        panel.events[#panel.events + 1] = b.action
      end
    end
  end
  panel.was_down = down
  gfx.update()
end

local CHANGES = { jump = false, set_pins = true, remove_fx = true, add_track = true, add_fx = true, set_param = true, set_named = true, fx_enable = true, set_track = true,
                  teach_tempo = true, teach_click = true, teach_track = true, teach_drums = true }
local running = true
function C.quit() running = false; return { bye = true } end

-- ------------------------------------------------------------------ loop
local function read_request(path)
  local f = io.open(path, "r"); if not f then return nil end
  local cmd = f:read("*l")
  local args = {}
  for line in f:lines() do
    local k, v = line:match("^([%w_]+)=(.*)$")
    if k then args[k] = v end
  end
  f:close()
  return cmd, args
end

local function answer(id, ok, body, err)
  local tmp, out = DIR .. "/res-" .. id .. ".tmp", DIR .. "/res-" .. id .. ".json"
  local f = io.open(tmp, "w")
  f:write(json({ ok = ok, result = body, error = err }))
  f:close()
  os.rename(tmp, out)
end

-- ------------------------------------------------------------------ the mastering chain (Hypnomix Main's buttons)
local HERE = (debug.getinfo(1, "S").source:match("^@(.*[/\\])") or "")
local chain_ok, MC = pcall(function()
  return dofile(HERE .. "masterchain.lua")({ set_shown = set_shown, shown = shown, first_number = first_number,
                                             probes = probes })
end)
if chain_ok then MC.commands(C) else probes.err = "masterchain: " .. tostring(MC); MC = nil end
CHANGES.chain_build = false; CHANGES.chain_save = false; CHANGES.chain_match = false   -- they make their own undo steps

local last_beat = 0
local function loop()
  local okp, errp = pcall(probe_poll)
  if not okp then probes.err = tostring(errp) end
  local okr, errr = pcall(rec_poll)
  if not okr then probes.err = "record: " .. tostring(errr) end
  if MC then
    local okc, errc = pcall(MC.poll)
    if not okc then probes.err = "chain: " .. tostring(errc) end
  end
  if panel.open then
    local okd, errd = pcall(panel.mode == "align" and align_draw or panel_draw)
    if not okd then panel.flash = "panel: " .. tostring(errd); panel.flash_until = reaper.time_precise() + 10 end
  end
  local now = reaper.time_precise()
  if now - last_beat > 1 then
    local f = io.open(DIR .. "/alive", "w"); if f then f:write(tostring(os.time())); f:close() end
    last_beat = now
  end
  local names, i = {}, 0
  while true do                                      -- a fresh listing each pass (index 0 re-reads the folder)
    local name = reaper.EnumerateFiles(DIR, i)
    if not name then break end
    names[#names + 1] = name
    i = i + 1
  end
  for _, name in ipairs(names) do
    local id = name:match("^req%-(.+)%.txt$")
    local path = id and (DIR .. "/" .. name)
    local cmd, args
    if path then cmd, args = read_request(path) end
    if cmd then                                      -- nil: already handled (a stale listing)
      os.remove(path)
      local fn = C[cmd]
      if not fn then
        answer(id, false, nil, "unknown command " .. tostring(cmd))
      else
        if CHANGES[cmd] then reaper.Undo_BeginBlock() end
        local ok, body, err = pcall(fn, args)
        if CHANGES[cmd] then reaper.Undo_EndBlock("hypnomix: " .. cmd, -1) end
        if not ok then answer(id, false, nil, tostring(body))
        elseif body == nil then answer(id, false, nil, err or "failed")
        else answer(id, true, body, nil) end
      end
    end
  end
  if running then reaper.defer(loop) else os.remove(DIR .. "/alive") end
end

reaper.atexit(function() os.remove(DIR .. "/alive") end)
loop()
