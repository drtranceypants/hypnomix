-- hypnomix mastering chain for REAPER: the buttons on Hypnomix Main (Build chain, Match target, Save chain).
-- Loaded by bridge.lua (dofile), which passes its helpers and calls M.poll() on every pass of its loop.
--
-- Build chain   REAPER's own plug-ins just before Hypnomix Main on the master, each renamed "Hypnomix · ...":
--               Tone (ReaEQ), Glue (ReaComp), Tame (ReaXcomp, bypassed), Warmth (JS: Saturation, bypassed),
--               Width (bass mono: JS Mid/Side Encoder, ReaEQ side high-pass, ReaEQ mid all-pass, JS Mid/Side Decoder)
--               and Limiter (ReaLimit). Every gain starts at 0 dB. Or a template you saved (a menu asks which).
-- Match target  plays (or keeps playing) and listens to Main after the chain, then turns ReaLimit's threshold (its
--               gain) until the master lands on the song card's Target LUFS, the master fader included.
-- Save chain    whatever is before Hypnomix Main on the master, as a REAPER FX chain file in
--               FXChains/hypnomix/NAME.RfxChain: every plug-in with every setting, third-party ones included. REAPER's
--               own "Add FX chain" opens these files too.
-- While the chain is the one hypnomix built, it follows the song card: Ceiling sets ReaLimit's ceiling (the gain
-- is kept), and the Limiter character sets ReaLimit's release and the Glue's attack.
--
-- What Main shows: gmem[14] is the state (codes below), gmem[15] and gmem[16] two numbers for it.
return function(H)
local M = {}
local GM_BUILD, GM_MATCH, GM_SAVE, GM_STATE, GM_A, GM_B = 11, 12, 13, 14, 15, 16
local S = { IDLE = 0, BUILT = 1, MATCHING = 2, MATCHED = 3, SAVED = 4, NO_LIMITER = 5, STOPPED = 6, CANCELLED = 7,
            SILENT = 8, ERROR = 9, HARD = 10, NO_MAIN = 11, NOTHING = 12, LOADED = 13, ASKING = 14 }
M.S = S
local TAG = "Hypnomix · "
local REAEQ, REACOMP, REAXCOMP, REALIMIT = "ReaEQ (Cockos)", "ReaComp (Cockos)", "ReaXcomp (Cockos)", "ReaLimit (Cockos)"
local MS_ENC, MS_DEC, SAT = "JS: Mid/Side Encoder", "JS: Mid/Side Decoder", "JS: Saturation"
local CHARACTER = { clean = { release = 120, glue_attack = 30 }, punch = { release = 60, glue_attack = 30 },
                    loud = { release = 20, glue_attack = 10 } }
local presses = {}
local match = nil
local menu = nil      -- the template menu, opened over a few passes (see M.build)
local card_seen = {}

local function say(code, a, b)
  reaper.gmem_write(GM_STATE, code); reaper.gmem_write(GM_A, a or 0); reaper.gmem_write(GM_B, b or 0)
end
local function master() return reaper.GetMasterTrack(0) end
local function fx_name(tr, i) return select(2, reaper.TrackFX_GetFXName(tr, i, "")) end
local function renamed(tr, i)
  local ok, n = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
  return ok and n or ""
end
local function main_index(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    if fx_name(tr, i):find("Hypnomix Main", 1, true) then return i end
  end
  return nil
end
local function ours(tr, i) return renamed(tr, i):sub(1, #TAG) == TAG end
local function chain_dir() return reaper.GetResourcePath() .. "/FXChains/hypnomix" end

-- the song card, from Main's own controls (the same labels the probes relay reads)
local function card()
  local tr = master(); local m = main_index(tr); local c = {}
  if not m then return c end
  for p = 0, reaper.TrackFX_GetNumParams(tr, m) - 1 do
    local _, pn = reaper.TrackFX_GetParamName(tr, m, p, "")
    local _, s = reaper.TrackFX_GetFormattedParamValue(tr, m, p, "")
    if pn == "Target LUFS" then c.target = tonumber(s) end
    if pn == "Ceiling dBTP" then c.ceiling = tonumber(s) end
    if pn == "Limiter" then c.mode = s end
  end
  return c
end

local function param(tr, fx, names)
  for _, want in ipairs(names) do
    local low = want:lower()
    for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
      local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
      if pn:lower() == low then return p end
    end
  end
  return nil
end
local function set(tr, fx, names, value, miss, label)
  local p = param(tr, fx, names)
  if not p then miss[#miss + 1] = label .. ": " .. names[1]; return end
  local s = H.set_shown(tr, fx, p, value)
  if not s then miss[#miss + 1] = label .. ": " .. names[1] end
end
local function add(tr, name, at, label, miss)
  local fx = reaper.TrackFX_AddByName(tr, name, false, -1000 - at)
  if fx < 0 then miss[#miss + 1] = label .. " (" .. name .. " not found)"; return nil end
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", TAG .. label)
  return fx
end

-- ReaEQ: k = band 0..4; type 0 low shelf, 1 high shelf, 3 low-pass, 4 high-pass, 5 all-pass, 8 band
local function band(tr, fx, k, typ, hz, gain, oct)
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "BANDTYPE" .. k, tostring(typ))
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "BANDENABLED" .. k, "1")
  H.set_shown(tr, fx, 3 * k, hz)
  if gain then H.set_shown(tr, fx, 3 * k + 1, gain) end
  H.set_shown(tr, fx, 3 * k + 2, oct)
end
local function octaves(q) return 2 / math.log(2) * math.log(1 / (2 * q) + math.sqrt(1 / (4 * q * q) + 1)) end

-- the stock chain, at position `at` on the master; returns how many plug-ins it added
local function build_stock(tr, at, miss)
  local n0 = reaper.TrackFX_GetCount(tr)
  local c = card()
  local eq = add(tr, REAEQ, at, "Tone (ReaEQ)", miss)
  if eq then
    band(tr, eq, 0, 4, 25, nil, octaves(0.71))          -- high-pass 25 Hz: rumble the limiter would react to
    band(tr, eq, 1, 0, 90, 0, octaves(0.71))            -- low shelf, 0 dB: low-end weight, ready to move
    band(tr, eq, 2, 8, 300, 0, octaves(0.9))            -- mud
    band(tr, eq, 3, 8, 3000, 0, octaves(0.9))           -- presence or harshness
    band(tr, eq, 4, 1, 10000, 0, octaves(0.71))         -- air
    at = at + 1
  end
  local comp = add(tr, REACOMP, at, "Glue (ReaComp)", miss)
  if comp then
    set(tr, comp, { "Threshold" }, -12, miss, "Glue"); set(tr, comp, { "Ratio" }, 2, miss, "Glue")
    set(tr, comp, { "Attack" }, 30, miss, "Glue"); set(tr, comp, { "Release" }, 150, miss, "Glue")
    set(tr, comp, { "RMS size" }, 50, miss, "Glue"); set(tr, comp, { "Knee" }, 6, miss, "Glue")
    at = at + 1
  end
  local xc = add(tr, REAXCOMP, at, "Tame (ReaXcomp, off until needed)", miss)
  if xc then reaper.TrackFX_SetEnabled(tr, xc, false); at = at + 1 end
  local sat = add(tr, SAT, at, "Warmth (Saturation, off)", miss)
  if sat then set(tr, sat, { "Amount (%)", "Amount" }, 15, miss, "Warmth"); reaper.TrackFX_SetEnabled(tr, sat, false); at = at + 1 end
  -- bass mono below 120 Hz: M/S, the side high-passed (two 12 dB = Linkwitz-Riley 24), the mid all-passed to match
  local enc = add(tr, MS_ENC, at, "Width 1/4 (M/S encode)", miss)
  if enc then at = at + 1 end
  local bw = octaves(0.7071)
  for _, one in ipairs({ { ch = 2, bands = { 4, 4 }, label = "Width 2/4 (side high-pass 120 Hz)" },
                         { ch = 1, bands = { 5 }, label = "Width 3/4 (mid all-pass 120 Hz)" } }) do
    local fx = add(tr, REAEQ, at, one.label, miss)
    if fx then
      for k = 0, 4 do
        if k < #one.bands then band(tr, fx, k, one.bands[k + 1], 120, nil, bw)
        else reaper.TrackFX_SetNamedConfigParm(tr, fx, "BANDENABLED" .. k, "0") end
      end
      for _, out in ipairs({ 0, 1 }) do
        reaper.TrackFX_SetPinMappings(tr, fx, out, 0, one.ch, 0)
        reaper.TrackFX_SetPinMappings(tr, fx, out, 1, 0, 0)
      end
      at = at + 1
    end
  end
  local dec = add(tr, MS_DEC, at, "Width 4/4 (M/S decode)", miss)
  if dec then at = at + 1 end
  local lim = add(tr, REALIMIT, at, "Limiter (ReaLimit)", miss)
  if lim then
    local ceil = c.ceiling or -1
    set(tr, lim, { "Ceiling" }, ceil, miss, "Limiter"); set(tr, lim, { "Threshold" }, ceil, miss, "Limiter")
  end
  return reaper.TrackFX_GetCount(tr) - n0
end

-- ------------------------------------------------------------------ FX chain files (templates)
-- a track's state chunk lists each plug-in as: BYPASS line, the plug-in block <...>, then FLOATPOS / FXID / WAK
-- lines; an .RfxChain file is exactly those entries
local function fx_entries(chunk)
  local s, e = chunk:find("\n<FXCHAIN[^\n]*\n")
  if not s then return nil end
  local depth, entries, cur = 1, {}, nil
  for line in chunk:sub(e + 1):gmatch("([^\n]*)\n") do
    local t = line:match("^%s*(.-)%s*$")
    if depth == 1 and t == ">" then break end
    if depth == 1 and t:find("^BYPASS") then cur = {}; entries[#entries + 1] = cur end
    if cur then cur[#cur + 1] = line end
    if t:sub(1, 1) == "<" then depth = depth + 1 elseif t == ">" then depth = depth - 1 end
  end
  return entries, s, e
end

local function save_chain(name)
  local tr = master(); local m = main_index(tr)
  if not m then say(S.NO_MAIN); return end
  if m == 0 then say(S.NOTHING); return end
  local _, chunk = reaper.GetTrackStateChunk(tr, "", false)
  local entries = fx_entries(chunk)
  if not entries or #entries < m then say(S.ERROR); return end
  reaper.RecursiveCreateDirectory(chain_dir(), 0)
  local out = {}
  for k = 1, m do
    for _, line in ipairs(entries[k]) do
      if not line:match("^%s*FXID ") then out[#out + 1] = line end   -- REAPER gives each loaded plug-in a new id
    end
  end
  local safe = name:gsub("[^%w%s%-%._()]", ""):gsub("^%s+", ""):gsub("%s+$", "")
  if safe == "" then safe = "my chain" end
  local f = io.open(chain_dir() .. "/" .. safe .. ".RfxChain", "w")
  if not f then say(S.ERROR); return end
  f:write(table.concat(out, "\n") .. "\n"); f:close()
  say(S.SAVED, m)
end

local function templates()
  local out, i = {}, 0
  while true do
    local f = reaper.EnumerateFiles(chain_dir(), i)
    if not f then break end
    local n = f:match("^(.+)%.[Rr][Ff][Xx][Cc][Hh][Aa][Ii][Nn]$")
    if n then out[#out + 1] = n end
    i = i + 1
  end
  table.sort(out)
  return out
end

-- insert a saved chain's plug-ins at `at` (via the chunk: every setting comes back), each tagged as ours
local function build_template(tr, at, name)
  local f = io.open(chain_dir() .. "/" .. name .. ".RfxChain", "r")
  if not f then return 0 end
  local text = f:read("*a"); f:close()
  text = text:gsub("\r\n", "\n")
  local _, chunk = reaper.GetTrackStateChunk(tr, "", false)
  local entries, s, e = fx_entries(chunk)
  if not entries then return 0 end
  -- where plug-in number `at` (Hypnomix Main) starts: the new plug-ins go just before it
  local rest, offset, where = chunk:sub(e + 1), 0, nil
  for k, ent in ipairs(entries) do
    local block = table.concat(ent, "\n") .. "\n"
    local a = rest:find(block, offset + 1, true)
    if not a then return 0 end
    if k == at + 1 then where = a - 1; break end
    offset = a + #block - 1
  end
  if not where then return 0 end
  offset = where
  local n0 = reaper.TrackFX_GetCount(tr)
  local new = chunk:sub(1, e + offset) .. text .. chunk:sub(e + offset + 1)
  reaper.SetTrackStateChunk(tr, new, false)
  local added = reaper.TrackFX_GetCount(tr) - n0
  for i = at, at + added - 1 do
    if not ours(tr, i) then
      local base = renamed(tr, i); if base == "" then base = fx_name(tr, i) end
      reaper.TrackFX_SetNamedConfigParm(tr, i, "renamed_name", TAG .. base)
    end
  end
  return added
end

-- Build with a name (the stock chain or a template). With no name and saved templates, a menu asks which: on macOS
-- a menu shows only from a real window that is already up, so a 1x1 window opens at the mouse and the menu follows
-- a few passes later (menu_poll). A 0x0 window with the menu at once closed by itself (measured in REAPER 7.86).
local function build_named(name)
  local tr = master(); local m = main_index(tr)
  if not m then say(S.NO_MAIN); return end
  local have = {}
  for i = 0, m - 1 do if ours(tr, i) then have[#have + 1] = i end end
  if #have > 0 and not M.yes then
    say(S.ASKING)
    if reaper.MB("Replace the HypnoMix chain on the master (" .. #have .. " plug-ins, your edits included)?",
                 "HypnoMix", 4) ~= 6 then say(S.CANCELLED); return end
  end
  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)
  for k = #have, 1, -1 do reaper.TrackFX_Delete(tr, have[k]) end
  m = main_index(tr)
  local miss, n = {}, 0
  if name == "hypnomix stock" then n = build_stock(tr, m, miss) else n = build_template(tr, m, name) end
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("hypnomix: build mastering chain (" .. name .. ")", -1)
  M.last_missing = miss
  if #miss > 0 then reaper.ShowConsoleMsg("HypnoMix chain: not set: " .. table.concat(miss, "; ") .. "\n") end
  card_seen = card()
  say(name == "hypnomix stock" and S.BUILT or S.LOADED, n, #miss)
  return n, miss
end

function M.build(name)
  if not main_index(master()) then say(S.NO_MAIN); return end
  if name then return build_named(name) end
  local list = templates()
  if #list == 0 then return build_named("hypnomix stock") end
  local opened = false
  if gfx.getchar() < 0 then                  -- no window of ours is open (the review panel would do)
    local x, y = reaper.GetMousePosition()
    gfx.init("HypnoMix", 1, 1, 0, x, y); opened = true
  end
  menu = { list = list, opened = opened, passes = 0 }
  say(S.ASKING)
end

local function menu_poll()
  local m = menu
  m.passes = m.passes + 1
  if m.passes < 3 then return end
  menu = nil
  local items = { "hypnomix stock" }
  for _, n in ipairs(m.list) do items[#items + 1] = n end
  if m.opened then gfx.x, gfx.y = 0, 0 else gfx.x, gfx.y = gfx.mouse_x, gfx.mouse_y end
  local k = gfx.showmenu(table.concat(items, "|"))
  if m.opened then gfx.quit() end
  if k < 1 then say(S.CANCELLED); return end
  build_named(items[k])
end

function M.save(name)
  if not name then
    say(S.ASKING)
    local ok, v = reaper.GetUserInputs("Save the mastering chain", 1, "Template name,extrawidth=120", "my master")
    if not ok then say(S.CANCELLED); return end
    name = v
  end
  save_chain(name)
end

-- ------------------------------------------------------------------ Match target
local function limiter()
  local tr = master(); local m = main_index(tr); local hit = nil
  if not m then return nil end
  for i = 0, m - 1 do if fx_name(tr, i):find("ReaLimit", 1, true) then hit = i end end
  return hit
end

local function gated(blocks)                 -- BS.1770: 400 ms windows of 100 ms blocks, absolute and relative gates
  local w, keep, s = {}, {}, 0
  for i = 4, #blocks do w[#w + 1] = (blocks[i] + blocks[i - 1] + blocks[i - 2] + blocks[i - 3]) / 4 end
  for _, x in ipairs(w) do if x > 0 and -0.691 + 10 * math.log(x, 10) > -70 then keep[#keep + 1] = x; s = s + x end end
  if #keep == 0 then return -120 end
  local rel = -0.691 + 10 * math.log(s / #keep, 10) - 10
  local s2, n2 = 0, 0
  for _, x in ipairs(keep) do if -0.691 + 10 * math.log(x, 10) > rel then s2 = s2 + x; n2 = n2 + 1 end end
  return n2 > 0 and -0.691 + 10 * math.log(s2 / n2, 10) or -120
end

function M.match()
  if match then
    if match.started and reaper.GetPlayState() & 1 == 1 then reaper.OnStopButton() end   -- leave it as we found it
    match = nil; say(S.CANCELLED); return
  end
  local fx = limiter()
  if not fx then say(S.NO_LIMITER); return end
  local c = card()
  local started = reaper.GetPlayState() & 1 == 0
  match = { fx = fx, target = c.target or -14, round = 0, blocks = {}, wait = 10, seq = H.probes.seq, started = started }
  if started then reaper.OnPlayButton() end
  say(S.MATCHING, match.target, 1)
end

local function match_poll()
  local m = match
  local tr = master()
  if reaper.GetPlayState() & 1 == 0 then match = nil; say(S.STOPPED); return end
  for _, b in ipairs(H.probes.buf) do
    if b.seq > m.seq and b.main then
      m.seq = b.seq
      if m.wait > 0 then m.wait = m.wait - 1
      else m.blocks[#m.blocks + 1] = b.vals[1] * b.vals[1] + b.vals[2] * b.vals[2] end
    elseif b.seq > m.seq then m.seq = b.seq end
  end
  if #m.blocks < 80 then return end
  local vol = reaper.GetMediaTrackInfo_Value(tr, "D_VOL")
  local L = gated(m.blocks) + (vol > 0 and 20 * math.log(vol, 10) or -120)
  m.round, m.blocks, m.wait = m.round + 1, {}, 10
  local th = param(tr, m.fx, { "Threshold" }); local ce = param(tr, m.fx, { "Ceiling" })
  local thv = H.first_number(H.shown(tr, m.fx, th)); local cev = H.first_number(H.shown(tr, m.fx, ce))
  local gain = cev - thv
  if L < -60 then match = nil; if m.started then reaper.OnStopButton() end; say(S.SILENT); return end
  local diff = m.target - L
  if math.abs(diff) < 0.4 or m.round >= 4 then
    match = nil
    if m.started then reaper.OnStopButton() end                  -- it started playing for the match: stop it
    say(math.abs(diff) < 0.4 and S.MATCHED or S.HARD, L, gain)
    return
  end
  local step = diff > 0 and math.min(diff * (m.round > 1 and 1.3 or 1), 6) or math.max(diff, -6)
  reaper.Undo_BeginBlock()
  H.set_shown(tr, m.fx, th, thv - step)
  reaper.Undo_EndBlock("hypnomix: Match target (ReaLimit gain)", -1)
  say(S.MATCHING, L, m.round + 1)
end

-- ------------------------------------------------------------------ the song card follows into our chain
local function follow()
  local tr = master(); local m = main_index(tr)
  if not m then return end
  local c = card()
  if c.ceiling == card_seen.ceiling and c.mode == card_seen.mode then return end
  local first = card_seen.ceiling == nil
  card_seen = c
  if first then return end                        -- the values as they were when the bridge started
  local ch = CHARACTER[c.mode or "clean"] or CHARACTER.clean
  for i = 0, m - 1 do
    if ours(tr, i) then
      local n = fx_name(tr, i)
      if n:find("ReaLimit", 1, true) and c.ceiling then
        local th, ce = param(tr, i, { "Threshold" }), param(tr, i, { "Ceiling" })
        local gain = H.first_number(H.shown(tr, i, ce)) - H.first_number(H.shown(tr, i, th))
        H.set_shown(tr, i, ce, c.ceiling); H.set_shown(tr, i, th, c.ceiling - gain)
        local rel = param(tr, i, { "Release" }); if rel then H.set_shown(tr, i, rel, ch.release) end
      elseif n:find("ReaComp", 1, true) then
        local at = param(tr, i, { "Attack" }); if at then H.set_shown(tr, i, at, ch.glue_attack) end
      end
    end
  end
end

local last_follow = 0
function M.poll()
  for _, k in ipairs({ GM_BUILD, GM_MATCH, GM_SAVE }) do
    local p = reaper.gmem_read(k)
    if presses[k] == nil then presses[k] = p end
    if p ~= presses[k] then
      presses[k] = p
      if k == GM_BUILD then M.build() elseif k == GM_MATCH then M.match() else M.save() end
    end
  end
  if menu then menu_poll() end
  if match then match_poll() end
  local now = reaper.time_precise()
  if now - last_follow > 0.5 then last_follow = now; follow() end
end

M.templates, M.card, M.limiter, M.gated = templates, card, limiter, gated

-- the same as the buttons, for `hypnomix reaper chain ...` and the tests (no dialogs: name and yes are given)
function M.commands(C)
  function C.chain_build(a)
    M.yes = a.yes == "1"
    local n, miss = M.build(a.name or "hypnomix stock")
    M.yes = false
    if not n then return nil, "not built (state " .. reaper.gmem_read(GM_STATE) .. ")" end
    return { added = n, missing = miss, state = reaper.gmem_read(GM_STATE) }
  end
  function C.chain_save(a)
    save_chain(a.name or "my chain")
    return { state = reaper.gmem_read(GM_STATE), plugins = reaper.gmem_read(GM_A), dir = chain_dir() }
  end
  function C.chain_match() M.match(); return { state = reaper.gmem_read(GM_STATE) } end
  function C.chain_state()
    local tr = master(); local m = main_index(tr); local fx = {}
    for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
      fx[#fx + 1] = { name = fx_name(tr, i), renamed = renamed(tr, i), on = reaper.TrackFX_GetEnabled(tr, i) }
    end
    return { state = reaper.gmem_read(GM_STATE), a = reaper.gmem_read(GM_A), b = reaper.gmem_read(GM_B),
             main = m, fx = fx, templates = templates(), matching = match ~= nil, card = card() }
  end
end
return M
end
