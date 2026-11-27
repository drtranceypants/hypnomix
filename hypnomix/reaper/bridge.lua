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

-- ------------------------------------------------------------------ HypnoMix Probe / Main (JSFX) relay
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
      local ln = n:lower()                              -- "HypnoMix Main" now, "Hypnomix Main" in older copies
      local kind = ln:find("hypnomix main", 1, true) and "main" or (ln:find("hypnomix probe", 1, true) and "probe" or nil)
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
  local out = { err = probes.err or probes.last_err, seq = probes.seq, buffered = #probes.buf, version = reaper.gmem_read(0), probes = {} }
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
-- HypnoMix Main's button counts presses in gmem[8]; the state Main shows is gmem[9] (0 idle, 1 recording,
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
  reaper.gmem_write(3, reaper.gmem_read(2))                  -- the probes' windows show "app on" while this is asked
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

-- ------------------------------------------------------------------ the HypnoMix Review panel (review and A/B)
-- A window drawn here with REAPER's own gfx; `hypnomix reaper review` keeps it in step with the app (Lua cannot
-- make web requests): it sets what to show (`panel_set`) and collects the clicks (`panel_events`).
local panel = { open = false, st = {}, events = {}, buttons = {}, was_down = false, flash = "", flash_until = 0,
                mode = "review", sliders = {}, drag = nil, hold = {} }
local PW, PH = 600, 300
local AW, AH = 680, 470                 -- the Align panel

-- the look and the guide, shared by both panels (ui.lua next to this script)
local UI_HERE = (debug.getinfo(1, "S").source:match("^@(.*[/\\])") or "")
local ui_ok, U = pcall(dofile, UI_HERE .. "ui.lua")
if not ui_ok then probes.err = "ui.lua: " .. tostring(U); U = nil end   -- soft: the panels fail, the rest still works

function C.panel_open(a)                -- mode=align: the HypnoMix Align panel (`hypnomix reaper align`) in the same window
  if not U then return { open = false, err = probes.err or probes.last_err } end
  local mode = (a and a.mode) or "review"
  if panel.open and panel.mode ~= mode then gfx.quit(); panel.open = false end
  if not panel.open then
    gfx.ext_retina = 1                  -- full resolution on a Retina screen (REAPER sets it to 2 there)
    if mode == "align" then gfx.init("HypnoMix Align", AW, AH) else gfx.init("HypnoMix Review", PW, PH) end
    panel.open, panel.mode, panel.st, panel.events = true, mode, {}, {}
    U.tour_on = false; panel.drag = nil
    if a and a.guide == "1" or not U.seen(mode) then U.tour_start() end      -- the guide, the first time
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

function C.panel_guide()                -- start the open panel's guide again (the same as its "?")
  if not U then return { open = false, err = probes.err or probes.last_err } end
  if panel.open then panel.drag = nil; U.tour_start() end     -- a drag under way is dropped, not sent when the guide closes
  return { open = panel.open }
end

function C.jump(a)       -- select the finding's track, put the cursor and the time selection around the spot
  -- a finding with no track (none sent, or "") leaves the track selection alone: track_of would give the master
  local tr = (a.track and a.track ~= "") and track_of(a.track) or nil
  if tr then reaper.SetOnlyTrackSelected(tr); reaper.Main_OnCommand(40913, 0) end   -- and scroll it into view
  if a.start then
    local s, e = tonumber(a.start), tonumber(a["end"] or a.start)
    reaper.GetSet_LoopTimeRange(true, false, s, e, false)
    reaper.SetEditCurPos(s, true, true)
  end
  return { track = tr ~= nil }
end

-- a button that sends `action` to `hypnomix reaper review` / `align` when clicked; returns the x after it
local function button(label, x, y, style, action, w, h)
  w = w or U.bw(label, 56)
  if U.button(action, x, y, w, h or 26, label, style) then panel.events[#panel.events + 1] = action end
  return x + w + 6
end

local function flash_line()
  if reaper.time_precise() < panel.flash_until then
    U.col(U.C.amber); U.font(3); U.wrap(panel.flash, 14, U.h - 20, U.w - 28, 13, 1)
  end
end

local SEV = U and { high = U.C.red, medium = U.C.amber, low = U.C.teal } or {}

-- The keys typed while a panel has the focus (returns false when the window was closed, by its close box or Esc).
-- Space runs Transport: Play/stop (40044). A script window cannot hand a key back to REAPER's main window. The panels take the keys while they are in front: space plays and stops (once per press: a held space repeats, and
-- each repeat would flip play and stop), Esc closes the guide or the panel. Other keys do nothing here; click
-- REAPER's own window first for its shortcuts.
local space_held = false
local function panel_keys()
  local space = false
  for _ = 1, 32 do                                   -- every key waiting since the last pass
    local ch = gfx.getchar()
    if ch < 0 then return false end                  -- the window was closed
    if ch == 0 then break end
    if ch == 32 then space = true
    elseif ch == 27 then
      if U.tour_on then U.tour_esc = true else gfx.quit(); return false end
    end
  end
  if space and not space_held then reaper.Main_OnCommand(40044, 0) end   -- play / stop, once
  space_held = space or gfx.getchar(32) > 0          -- still down (auto-repeat): wait for its release
  return true
end

local function panel_draw()
  if not panel_keys() then panel.open = false; panel.events[#panel.events + 1] = "closed"; return end
  local st = panel.st
  U.begin()
  local help = U.header("HypnoMix Review", st.status or "")
  if help then U.tour_start() end
  -- the finding
  U.card(10, 46, U.w - 20, 140)
  local sev = ((st.sev or "") ~= "" and st.sev or (st.head or ""):match("^%[(%w+)%]") or ""):lower()
  local x = 22
  if sev ~= "" then
    U.col(SEV[sev] or U.C.muted); U.font(3)
    local sw = U.textw(sev:upper()) + 18
    U.rrect(x, 58, sw, 18, 9); U.col(U.C.dark); U.textc(x, 58, sw, 18, sev:upper()); x = x + sw + 10
  end
  U.col(U.C.text); U.font(2)
  local head = (st.track or "") ~= "" and (st.track .. (((st.where or "") ~= "") and ("  ·  " .. st.where) or ""))
               or (st.head or ""):gsub("^%[%w+%]%s*", "")
  U.wrap(head, x, 60, U.w - x - 22, 15, 1)
  U.col(U.C.text); U.font(1)
  local _, ph = U.wrap(st.problem, 22, 86, U.w - 44, 16, 3)
  U.col(U.C.teal); U.font(1)
  U.wrap(st.fix, 22, 92 + ph, U.w - 44, 16, 2)
  -- step through and decide
  local y = 198
  x = button("Prev", 10, y, "plain", "prev"); x = button("Next", x, y, "plain", "next")
  x = button("Next open", x, y, "plain", "next_open")
  x = button("Approve", x + 12, y, st.decision == "approve" and "teal" or "amber", "approve")
  x = button("Skip", x, y, st.decision == "skip" and "teal" or "plain", "skip")
  -- A / B / Blind (an A/B project)
  local aby = 234
  if st.ab == "1" then
    U.card(10, aby - 4, U.w - 20, 36)
    x = 18
    if st.blind == "1" then
      x = button("X", x, aby, st.heard == "X" and "teal" or "plain", "X", 44); x = button("Y", x, aby, st.heard == "Y" and "teal" or "plain", "Y", 44)
      x = button("I like X", x + 12, aby, "amber", "like_X"); x = button("I like Y", x, aby, "amber", "like_Y")
    else
      x = button("A · now", x, aby, st.state == "A" and "teal" or "plain", "A"); x = button("B · fix", x, aby, st.state == "B" and "teal" or "plain", "B")
      x = button("Blind", x + 12, aby, "plain", "blind")
    end
    button(st.match == "1" and "Match on" or "Match off", x + 12, aby, st.match == "1" and "teal" or "plain", "match")
  else
    U.col(U.C.muted); U.font(3)
    U.wrap("A / B / Blind appear here in an A/B project (hypnomix abset, then hypnomix reaper review)", 14, aby + 8, U.w - 28, 13, 1)
  end
  flash_line()
  -- the guide
  local r = U.tour({
    { 6, 6, U.w - 50, 26, "HypnoMix Review in REAPER", "This panel follows the review in the HypnoMix app: every finding of the scan, one at a time. When you move to a finding (Prev, Next and Next open here, or Show in REAPER in the app), REAPER's cursor and time selection go to the spot and its track is selected, so you hear it where it is. Your project's content is not changed, and nothing is saved until you save. In an A/B project, A, B and Blind switch which plug-ins and tracks play (see that step)." },
    { 10, 46, U.w - 20, 140, "The finding", "How serious it is (red high, amber medium, teal low), the track and where, what is wrong, and in teal the fix HypnoMix proposes. Press space to play the selection (and again to stop)." },
    { 10, 198, 200, 26, "Prev, Next, Next open", "Step through the findings. Next open skips the ones you already decided." },
    { 220, 198, 160, 26, "Approve or Skip", "Approve marks the fix to be written; Skip leaves it. Nothing is applied yet: hypnomix fix writes only what you approved into ONE new project, next to yours." },
    { 10, aby - 4, U.w - 20, 36, "A, B and Blind", "In an A/B project (hypnomix abset) A is your mix and B the fix, switched instantly with every plug-in playing. Match turns B to A's loudness (needs HypnoMix Main and the bridge). Blind hides which is which until you pick." },
    { U.w - 34, 6, 24, 24, "Help any time", "The ? starts this guide again. The same guide is in HypnoMix Probe, HypnoMix Main and the Align panel. In this panel space plays and stops REAPER, and Esc closes the guide, or the panel when the guide is off." },
  })
  if r == "done" then U.mark_seen("review") end
  U.finish()
  gfx.update()
end


-- ------------------------------------------------------------------ the HypnoMix Align panel
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

-- name, label, lowest, highest, how it reads, scale, and the value shown until the app sends one (the app's own
-- starting values in reaper/align.py: Tight 50%, the rest 0), so the panel never opens showing Formant -3 st
local SLIDERS = { { "tight", "Tight", 0, 1, "%.0f%%", 100, 0.5 }, { "pitch", "Pitch", 0, 1, "%.0f%%", 100, 0 },
                  { "vibrato", "Vibrato", 0, 1, "%.0f%%", 100, 0 }, { "formant", "Formant", -3, 3, "%+.1f st", 1, 0 } }

local function slider(def, x, y, w)
  local key, label, lo, hi, f, k, start = table.unpack(def)
  local v = tonumber(panel.st[key] or start) or start
  local area = U.slider(x, y, w, v, lo, hi, label, string.format(f, v * k))
  area.key = key
  panel.sliders[#panel.sliders + 1] = area
end

local function lane(name, before, after, x, y, w, h)
  U.col(U.C.card); U.rrect(x, y, w, h, 6)
  local s = U.s
  local function draw(list, c, alpha)
    local pts = {}
    for v in tostring(list or ""):gmatch("[^,]+") do pts[#pts + 1] = tonumber(v) or -60 end
    if #pts < 2 then return end
    U.col(c, alpha)
    for i = 2, #pts do
      local x0, x1 = x + w * (i - 2) / (#pts - 1), x + w * (i - 1) / (#pts - 1)
      local y0, y1 = y + h - 2 - (h - 4) * (pts[i - 1] + 60) / 60, y + h - 2 - (h - 4) * (pts[i] + 60) / 60
      gfx.line(x0 * s, y0 * s, x1 * s, y1 * s, 1)
    end
  end
  draw(before, { 150, 146, 150 }, 0.9)
  draw(after, U.C.amber, 1)
  U.col(U.C.text, 0.9); U.font(3); U.text(x + 8, y + 4, name)
end

local function align_draw()
  if not panel_keys() then panel.open = false; panel.events[#panel.events + 1] = "closed"; return end
  local st = panel.st
  panel.sliders = {}
  U.begin()
  if U.header("HypnoMix Align", st.status or "") then U.tour_start() end
  local busy = st.busy == "1"
  -- who: the guide and the parts
  U.card(10, 46, U.w - 20, 72)
  U.col(U.C.muted); U.font(3); U.text(22, 54, "WHO")
  local x = button("Guide ←", 22, 68, "plain", "guide", 88, 22)
  U.col(st.guide ~= "" and st.guide and U.C.text or U.C.muted); U.font(2)
  U.wrap(st.guide ~= "" and st.guide or "select the guide track, then Guide ←", x + 4, 72, U.w - x - 30, 14, 1)
  x = button("+ Part", 22, 92, "plain", "part", 88, 22); x = button("Clear", x, 92, "plain", "clear", 60, 22)
  U.col(st.parts ~= "" and st.parts and U.C.text or U.C.muted); U.font(1)
  U.wrap(st.parts ~= "" and st.parts or "select a part, + Part; repeat for each", x + 4, 96, U.w - x - 30, 14, 1)
  -- where
  U.card(10, 126, U.w - 20, 62)
  U.col(U.C.muted); U.font(3); U.text(22, 134, "WHERE")
  x = button("Selection", 22, 148, st.range_on == "1" and "teal" or "plain", "range", nil, 22)
  x = button("Song", x, 148, st.range_on ~= "1" and "teal" or "plain", "song", nil, 22)
  x = button("Protect", x + 12, 148, "plain", "protect", nil, 22); x = button("Sync here", x, 148, "plain", "sync", nil, 22)
  x = button("Clear marks", x, 148, "plain", "clear_marks", nil, 22)
  U.col(U.C.muted); U.font(3); U.wrap(st.where or "", 22, 173, U.w - 44, 12, 1)
  -- how
  U.card(10, 196, U.w - 20, 70)
  U.col(U.C.muted); U.font(3); U.text(22, 204, "HOW")
  local sw = math.floor((U.w - 64) / 2)
  slider(SLIDERS[1], 22, 222, sw); slider(SLIDERS[2], 42 + sw, 222, sw)
  slider(SLIDERS[3], 22, 244, sw); slider(SLIDERS[4], 42 + sw, 244, sw)
  -- go
  local y = 276
  x = button("Preset: " .. ((st.preset or "") ~= "" and st.preset or "none"), 10, y, (st.preset or "") ~= "" and "teal" or "plain", "preset")
  x = button(st.takes == "1" and "Timing: takes" or "Timing: markers", x + 8, y, st.takes == "1" and "teal" or "plain", "takes")
  x = button(st.write == "1" and "Write project: on" or "Write project: off", x, y, st.write == "1" and "teal" or "plain", "write")
  x = button(busy and "Aligning…" or "Align", x + 8, y, busy and "teal" or "amber", "align", 84)
  if st.can_open == "1" then x = button("Open project", x, y, "plain", "open") end
  U.col(U.C.text); U.font(1); U.wrap(st.result or "", 14, y + 34, U.w - 28, 14, 1)
  -- lanes: grey before, amber after
  local top, n = 330, 0
  local lanes = {}
  for l in tostring(st.lanes or ""):gmatch("[^|]+") do lanes[#lanes + 1] = l end
  if #lanes > 0 then
    local lh = math.min(34, math.floor((U.h - top - 26) / #lanes) - 4)
    for _, l in ipairs(lanes) do
      local name, before, after = l:match("^([^;]*);([^;]*);?(.*)$")
      lane(name or "", before, after, 10, top + n * (lh + 4), U.w - 20, lh); n = n + 1
    end
  else
    U.col(U.C.muted); U.font(3)
    U.wrap("After Align, each part shows here: grey before, amber after, against the guide.", 14, top + 6, U.w - 28, 13, 2)
  end
  flash_line()
  -- mouse: a slider follows a drag (reported when let go); buttons were handled as they were drawn
  if not U.tour_on then
    local mx = U.mx
    if U.press then
      for _, s in ipairs(panel.sliders) do
        if U.inside(s.x - 6, s.y, s.w + 12, s.h) then panel.drag = s end
      end
    end
    if panel.drag then
      local s = panel.drag
      local v = s.lo + (s.hi - s.lo) * math.max(0, math.min(1, (mx - s.x) / s.w))
      v = (s.hi - s.lo) > 2 and math.floor(v * 10 + 0.5) / 10 or math.floor(v * 100 + 0.5) / 100
      panel.st[s.key] = tostring(v)
      panel.hold[s.key] = reaper.time_precise() + 1.5
      if not U.down then
        panel.events[#panel.events + 1] = "set:" .. s.key .. "=" .. tostring(v)
        panel.drag = nil
      end
    end
  else
    panel.drag = nil                                 -- the guide is on: no drag carries over past it
  end
  local r = U.tour({
    { 6, 6, U.w - 50, 26, "HypnoMix Align in REAPER", "Lines up the timing (and, if you like, pitch and formant) of vocal parts to a guide track, like the Align device in Live. It writes stretch markers or new takes into a NEW project: yours is never changed." },
    { 10, 46, U.w - 20, 72, "Who", "Select the guide track (usually the lead) and press Guide ←. Then select each part to line up and press + Part. Clear starts over." },
    { 10, 126, U.w - 20, 62, "Where", "Selection aligns only the time selection; Song the whole song. Protect keeps a stretch untouched; Sync here marks a point every part must meet. Clear marks removes them." },
    { 10, 196, U.w - 20, 70, "How", "Drag the sliders. Tight: how far each part moves toward the guide (gentle is natural). Pitch and Vibrato: how much of the guide's pitch to follow. Formant: the voice's character, in semitones." },
    { 10, 276, U.w - 20, 26, "Align", "Preset recalls saved settings. Timing by markers keeps one item; by takes writes new takes you can switch. Write project makes the new .rpp; Align runs it and Open project opens the result." },
    { 10, 326, U.w - 20, U.h - 336, "Before and after", "Each part's level shape against time: grey before, amber after. Listen in the new project before you keep it. The ? starts this guide again; in this panel space plays and stops REAPER, and Esc closes the guide, or the panel when the guide is off." },
  })
  if r == "done" then U.mark_seen("align") end
  U.finish()
  gfx.update()
end

local CHANGES = { jump = false, panel_guide = false, set_pins = true, remove_fx = true, add_track = true, add_fx = true, set_param = true, set_named = true, fx_enable = true, set_track = true,
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
  if not f then probes.err = "could not write the answer in " .. DIR; return false end   -- the caller times out
  local wrote = f:write(json({ ok = ok, result = body, error = err }))
  f:close()
  if not wrote then os.remove(tmp); probes.err = "could not write the answer in " .. DIR; return false end
  return os.rename(tmp, out) and true or false
end

-- ------------------------------------------------------------------ the mastering chain (HypnoMix Main's buttons)
local HERE = (debug.getinfo(1, "S").source:match("^@(.*[/\\])") or "")
local chain_ok, MC = pcall(function()
  return dofile(HERE .. "masterchain.lua")({ set_shown = set_shown, shown = shown, first_number = first_number,
                                             probes = probes })
end)
if chain_ok then MC.commands(C) else probes.err = "masterchain: " .. tostring(MC); MC = nil end
CHANGES.chain_build = false; CHANGES.chain_save = false; CHANGES.chain_match = false   -- they make their own undo steps
do local ok, MX = pcall(function() return dofile(HERE .. "mixer.lua")({ track_of = track_of, shown = shown }) end); if ok then MX.commands(C, CHANGES) else probes.err = "mixer: " .. tostring(MX) end end

-- The JSFX windows: gmem[2] counts the bridge's passes ("bridge on"); gmem[5] / gmem[6] are "the Probe's / Main's guide
-- was seen", kept in REAPER's extended state so the guide shows once per computer, not once per plug-in.
local beat_n = 0
local function jsfx_poll()
  if not attached then reaper.gmem_attach("hypnomix"); attached = true end
  beat_n = beat_n + 1
  if beat_n == 1 then reaper.gmem_write(3, 0) end   -- gmem outlives the bridge: an old "app" count must not read as on
  reaper.gmem_write(2, beat_n)
  if not U then return end
  for k, key in pairs({ [5] = "probe", [6] = "main" }) do
    local g = reaper.gmem_read(k)
    if g == 1 and not U.seen(key) then U.mark_seen(key)
    elseif g ~= 1 and U.seen(key) then reaper.gmem_write(k, 1) end
  end
end

-- One bridge per REAPER: each start takes a new token (REAPER's extended state, this session only); a bridge whose token
-- is no longer the current one ends at its next pass, so a second start replaces the first instead of doubling it.
local TOKEN = string.format("%.6f-%d", reaper.time_precise(), math.random(1, 1000000000))
reaper.SetExtState("hypnomix", "bridge_token", TOKEN, false)
local replaced = false
os.remove(DIR .. "/busy")                            -- left by a REAPER that closed in the middle of a command

-- REAPER's own process id, so the Python side can tell a `busy` file left by a REAPER that crashed (or was quit) in
-- the middle of a command from one this REAPER is working on. On macOS the shell REAPER starts reports its parent's
-- id; on Windows there is no quick way from Lua, so it stays 0 and the Python side falls back to the file's age.
local PID = 0
if not reaper.GetOS():match("^Win") then
  pcall(function()
    local h = io.popen("echo $PPID")
    if h then PID = tonumber((h:read("*a") or ""):match("%d+")) or 0; h:close() end
  end)
end

-- `alive` says "running" to the Python side (client.py) when it is younger than a few seconds. A command can hold
-- REAPER's main thread far longer (a render runs inside the call), so `busy` is written before every command and
-- removed after it: "<request id>\n<command>\n<token>\n<REAPER's process id>\n". `alive` holds
-- "<time>\n<token>\n<process id>\n". While `busy` is there and its REAPER is still running, the Python side waits
-- instead of calling the bridge dead (and starting another one).
local last_beat = 0
local function beat(force)
  local now = reaper.time_precise()
  if force or now - last_beat > 1 then
    local f = io.open(DIR .. "/alive", "w"); if f then f:write(tostring(os.time()) .. "\n" .. TOKEN .. "\n" .. PID .. "\n"); f:close() end
    last_beat = now
  end
end

local function busy(id, cmd)
  if id then
    local f = io.open(DIR .. "/busy", "w"); if f then f:write(id .. "\n" .. tostring(cmd) .. "\n" .. TOKEN .. "\n" .. PID .. "\n"); f:close() end
  else
    os.remove(DIR .. "/busy")
  end
end

local function run(id, cmd, args)
  local fn = C[cmd]
  if not fn then return answer(id, false, nil, "unknown command " .. tostring(cmd)) end
  busy(id, cmd)
  if CHANGES[cmd] then reaper.Undo_BeginBlock() end
  local ok, body, err = pcall(fn, args)
  if CHANGES[cmd] then reaper.Undo_EndBlock("hypnomix: " .. cmd, -1) end
  busy(nil)
  beat(true)                                         -- fresh again at once after a long command
  if not ok then answer(id, false, nil, tostring(body))
  elseif body == nil then answer(id, false, nil, err or "failed")
  else answer(id, true, body, nil) end
end

local function requests()
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
      run(id, cmd, args)
      if not running then break end                  -- quit: the rest wait for the next bridge
    end
  end
end

local last_err = nil
local function loop()
  if reaper.GetExtState("hypnomix", "bridge_token") ~= TOKEN then   -- a newer bridge took over: leave it its files
    replaced = true
    if panel.open then gfx.quit(); panel.open = false end
    return
  end
  pcall(jsfx_poll)
  local okp, errp = pcall(probe_poll)
  if not okp then probes.err = tostring(errp) end
  local okr, errr = pcall(rec_poll)
  if not okr then probes.err = "record: " .. tostring(errr) end
  if MC then
    local okc, errc = pcall(MC.poll)
    if not okc then probes.err = "chain: " .. tostring(errc) end
  end
  if panel.open and U then
    local okd, errd = pcall(panel.mode == "align" and align_draw or panel_draw)
    if not okd then panel.flash = "panel: " .. tostring(errd); panel.flash_until = reaper.time_precise() + 10; probes.err = panel.flash end
  end
  pcall(beat)
  if probes.err then                                -- a failure inside the bridge: written where the Python side reads it
    last_err = probes.err; probes.last_err = last_err; probes.err = nil   -- cleared, so the same failure again is written again
    pcall(function()
      local f = io.open(DIR .. "/last-error.txt", "w"); if f then f:write(tostring(os.time()) .. "\n" .. last_err .. "\n"); f:close() end
    end)
  end
  local okq, errq = pcall(requests)                  -- one failed request (a full disk, a removed folder) never ends the bridge
  if not okq then probes.err = "requests: " .. tostring(errq); pcall(busy, nil) end
  if running then reaper.defer(loop)
  else
    os.remove(DIR .. "/alive"); os.remove(DIR .. "/busy")
    reaper.DeleteExtState("hypnomix", "bridge_token", false)
  end
end

reaper.atexit(function()
  if replaced then return end                        -- the newer bridge's alive file and app count are its own
  os.remove(DIR .. "/alive"); os.remove(DIR .. "/busy")
  if attached then reaper.gmem_write(3, 0) end      -- the JSFX windows stop showing "app on"
  if reaper.GetExtState("hypnomix", "bridge_token") == TOKEN then reaper.DeleteExtState("hypnomix", "bridge_token", false) end
end)
loop()
