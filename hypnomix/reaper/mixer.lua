-- hypnomix mixer commands for REAPER: the hands-on tools Live has through AbletonOSC (`hypnomix reaper snapshot`,
-- `loop`, `diagnose`). Loaded by bridge.lua (dofile), which passes its helpers; M.commands(C, CHANGES) adds the
-- commands to the bridge's table.
--
-- mixer_snapshot      every track (the master first): fader, pan, width, mute, solo, phase, sends, and each
--                     plug-in's on/off state and parameters (normalized value and what the plug-in shows)
-- mixer_restore       puts a snapshot back from a flat text file Python writes (one undo step, "hypnomix: snapshot
--                     restore"); only the keys listed in INFO / SEND are ever set
-- mixer_send          one send's level, pan or mute (one undo step)
-- mixer_timemap       the project's length and the start of every bar, in seconds
-- mixer_solo_render   solo some tracks (in place), render the master for a time range, put every solo back as it
--                     was (nothing is left changed, so no undo step)
--
-- Every call below is one bridge.lua or masterchain.lua already uses, or a stock ReaScript function
-- (GetTrackSendInfo_Value, TrackFX_GetFXGUID, TimeMap2_beatsToTime, GetTrackSendName). Run in a private REAPER 7.86
-- on a two-track test project (2026-11-26), never on a real song, nothing judged by ear: it loaded with no error,
-- snapshot, diff and restore were exact, loop --ab and --revert put the mix back, and mixer_solo_render put every
-- solo back; run again after the second review (2026-11-27, the "guide seen" values left out). Not checked: Windows, a real song, a project with folders (solo in place with folders and send returns),
-- the send destination names, and snapshot speed with large plug-ins (see docs/REAPER.md).
return function(H)
local M = {}

local INFO = { D_VOL = true, D_PAN = true, D_WIDTH = true, B_MUTE = true, I_SOLO = true, B_PHASE = true }
local SEND = { D_VOL = true, D_PAN = true, B_MUTE = true, I_SENDMODE = true }
local EPS = 1e-7

local function guid_of(tr) return reaper.GetTrackGUID(tr) end

local function send_dest(tr, s)
  -- GetTrackSendName counts hardware outputs first: track sends start after them
  local _, name = reaper.GetTrackSendName(tr, reaper.GetTrackNumSends(tr, 1) + s, "")
  return name or ""
end

local function fx_entry(tr, k, max_params)
  local _, name = reaper.TrackFX_GetFXName(tr, k, "")
  local n = reaper.TrackFX_GetNumParams(tr, k)
  local e = { index = k, name = name, guid = reaper.TrackFX_GetFXGUID(tr, k), on = reaper.TrackFX_GetEnabled(tr, k),
              offline = reaper.TrackFX_GetOffline(tr, k), nparams = n, params = {} }
  local ln = (name or ""):lower()                                  -- JSFX names are case-insensitive
  local own = ln:find("hypnomix probe", 1, true) or ln:find("hypnomix main", 1, true)
  for p = 0, math.min(n, max_params) - 1 do
    local _, pn = reaper.TrackFX_GetParamName(tr, k, p, "")
    local lp = (pn or ""):lower()
    -- the bridge owns the probes' slots and Main's A/B match gain ("abgain", shown as "match gain dB"); "guide seen"
    -- only says the walkthrough was shown, so a diff never reports it and a restore never shows the guide again
    if not (own and (lp:find("slot", 1, true) or lp:find("abgain", 1, true) or lp:find("match gain", 1, true)
                     or lp:find("guide seen", 1, true))) then
      e.params[#e.params + 1] = { i = p, name = pn, value = reaper.TrackFX_GetParamNormalized(tr, k, p),
                                  shown = H.shown(tr, k, p) }
    end
  end
  if n > max_params then e.truncated = true end
  return e
end

local function track_entry(tr, index, max_params)
  local _, name = reaper.GetTrackName(tr)
  local e = { index = index, name = name, guid = guid_of(tr), master = index < 0,
              volume = reaper.GetMediaTrackInfo_Value(tr, "D_VOL"), pan = reaper.GetMediaTrackInfo_Value(tr, "D_PAN"),
              width = reaper.GetMediaTrackInfo_Value(tr, "D_WIDTH"),
              mute = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1,
              phase = reaper.GetMediaTrackInfo_Value(tr, "B_PHASE") == 1, sends = {}, fx = {} }
  if index >= 0 then
    e.solo = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO")
    e.depth = reaper.GetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH")
    for s = 0, reaper.GetTrackNumSends(tr, 0) - 1 do
      e.sends[#e.sends + 1] = { index = s, dest = send_dest(tr, s),
                                volume = reaper.GetTrackSendInfo_Value(tr, 0, s, "D_VOL"),
                                pan = reaper.GetTrackSendInfo_Value(tr, 0, s, "D_PAN"),
                                mute = reaper.GetTrackSendInfo_Value(tr, 0, s, "B_MUTE") == 1,
                                mode = reaper.GetTrackSendInfo_Value(tr, 0, s, "I_SENDMODE") }
    end
  end
  for k = 0, reaper.TrackFX_GetCount(tr) - 1 do e.fx[#e.fx + 1] = fx_entry(tr, k, max_params) end
  return e
end

local function find_track(guid, index, name)
  local master = reaper.GetMasterTrack(0)
  if index == -1 or guid == guid_of(master) then return master end
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    if guid_of(tr) == guid then return tr end
  end
  local tr = index and index >= 0 and reaper.GetTrack(0, index)              -- moved project, new GUIDs: same place
  if tr and select(2, reaper.GetTrackName(tr)) == name then return tr end
  return nil
end

local function find_fx(tr, guid, index, name)
  for k = 0, reaper.TrackFX_GetCount(tr) - 1 do
    if reaper.TrackFX_GetFXGUID(tr, k) == guid then return k end
  end
  if index and index < reaper.TrackFX_GetCount(tr) and select(2, reaper.TrackFX_GetFXName(tr, index, "")) == name then
    return index
  end
  return nil
end

-- the restore file: tab-separated lines, written by hypnomix/reaper/mixer.py `flatten`
--   track <guid> <index> <name>        the track the next lines are for (-1 = master)
--   info <KEY> <value>                 KEY in INFO
--   send <i> <dest name> <KEY> <value> KEY in SEND; skipped if send i no longer goes to that track
--   fx <guid> <index> <name>           the plug-in the next lines are for
--   param <i> <normalized value>
--   on <0|1>
local function restore_file(path)
  local f = io.open(path, "r"); if not f then return nil, "cannot read " .. tostring(path) end
  local changed, missing = 0, {}
  local tr, tname, fx = nil, nil, nil
  local function miss(what) missing[#missing + 1] = what end
  for line in f:lines() do
    local p = {}
    for field in (line .. "\t"):gmatch("([^\t]*)\t") do p[#p + 1] = field end
    local kind = p[1]
    if kind == "track" then
      tname, fx = p[4], nil
      tr = find_track(p[2], tonumber(p[3]), p[4])
      if not tr then miss("track " .. tostring(p[4])) end
    elseif tr and kind == "info" and INFO[p[2]] then
      local v = tonumber(p[3])
      if v and math.abs(reaper.GetMediaTrackInfo_Value(tr, p[2]) - v) > EPS then
        reaper.SetMediaTrackInfo_Value(tr, p[2], v); changed = changed + 1
      end
    elseif tr and kind == "send" and SEND[p[4]] then
      local s, v = tonumber(p[2]), tonumber(p[5])
      if s and v and s < reaper.GetTrackNumSends(tr, 0) and send_dest(tr, s) == p[3] then
        if math.abs(reaper.GetTrackSendInfo_Value(tr, 0, s, p[4]) - v) > EPS then
          reaper.SetTrackSendInfo_Value(tr, 0, s, p[4], v); changed = changed + 1
        end
      elseif p[4] == "D_VOL" then miss(tname .. ": send to " .. tostring(p[3]))
      end
    elseif tr and kind == "fx" then
      fx = find_fx(tr, p[2], tonumber(p[3]), p[4])
      if not fx then miss(tname .. ": " .. tostring(p[4])) end
    elseif tr and fx and kind == "param" then
      local i, v = tonumber(p[2]), tonumber(p[3])
      if i and v and i < reaper.TrackFX_GetNumParams(tr, fx)
         and math.abs(reaper.TrackFX_GetParamNormalized(tr, fx, i) - v) > EPS then
        reaper.TrackFX_SetParamNormalized(tr, fx, i, v); changed = changed + 1
      end
    elseif tr and fx and kind == "on" then
      local on = p[2] == "1"
      if reaper.TrackFX_GetEnabled(tr, fx) ~= on then reaper.TrackFX_SetEnabled(tr, fx, on); changed = changed + 1 end
    end
  end
  f:close()
  return { changed = changed, missing = missing }
end

function M.commands(C, CHANGES)
  function C.mixer_snapshot(a)
    local max_params = tonumber(a.max_params or 4096) or 4096
    local _, path = reaper.EnumProjects(-1, "")
    local out = { track_entry(reaper.GetMasterTrack(0), -1, max_params) }
    for i = 0, reaper.CountTracks(0) - 1 do out[#out + 1] = track_entry(reaper.GetTrack(0, i), i, max_params) end
    return { project = path, tempo = reaper.Master_GetTempo(), tracks = out }
  end

  function C.mixer_restore(a)
    reaper.Undo_BeginBlock()
    reaper.PreventUIRefresh(1)
    local ok, res, err = pcall(restore_file, a.file)
    reaper.PreventUIRefresh(-1)
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    reaper.Undo_EndBlock("hypnomix: snapshot restore", -1)
    if not ok then return nil, tostring(res) end
    return res, err
  end

  function C.mixer_send(a)
    local tr = H.track_of(a.track); if not tr then return nil, "no track" end
    local s = tonumber(a.send)
    if not s or s < 0 or s >= reaper.GetTrackNumSends(tr, 0) then return nil, "the track has no send " .. tostring(a.send) end
    if a.volume_db then reaper.SetTrackSendInfo_Value(tr, 0, s, "D_VOL", 10 ^ (tonumber(a.volume_db) / 20)) end
    if a.pan then reaper.SetTrackSendInfo_Value(tr, 0, s, "D_PAN", tonumber(a.pan)) end
    if a.mute then reaper.SetTrackSendInfo_Value(tr, 0, s, "B_MUTE", tonumber(a.mute)) end
    return { dest = send_dest(tr, s), volume = reaper.GetTrackSendInfo_Value(tr, 0, s, "D_VOL"),
             pan = reaper.GetTrackSendInfo_Value(tr, 0, s, "D_PAN"),
             mute = reaper.GetTrackSendInfo_Value(tr, 0, s, "B_MUTE") == 1 }
  end

  function C.mixer_timemap()
    local len = reaper.GetProjectLength(0)
    local bars, m = {}, 0
    while m <= 20000 do                                     -- every bar start, through the first one at or past the end
      local t = reaper.TimeMap2_beatsToTime(0, 0, m)
      bars[#bars + 1] = t
      if t >= len then break end
      m = m + 1
    end
    return { length = len, tempo = reaper.Master_GetTempo(), bars = bars }
  end

  function C.mixer_solo_render(a)
    local want, found = {}, 0
    for g in (a.tracks or ""):gmatch("[^,]+") do want[g] = true end
    local keep = {}
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      keep[i] = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO")
      if want[guid_of(tr)] then found = found + 1 end
    end
    if found == 0 then return nil, "none of those tracks is in the project" end
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", want[guid_of(tr)] and 2 or 0)   -- 2: solo in place
    end
    local ok, res, err = pcall(C.render_master, a)
    for i = 0, reaper.CountTracks(0) - 1 do
      reaper.SetMediaTrackInfo_Value(reaper.GetTrack(0, i), "I_SOLO", keep[i])
    end
    if not ok then return nil, tostring(res) end
    if res then res.soloed = found end
    return res, err
  end

  CHANGES.mixer_send = true            -- "hypnomix: mixer_send"
  CHANGES.mixer_restore = false        -- its own undo step, "hypnomix: snapshot restore"
  CHANGES.mixer_solo_render = false    -- every solo is put back: nothing changes
end

return M
end
