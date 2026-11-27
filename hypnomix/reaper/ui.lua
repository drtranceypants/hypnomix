-- HypnoMix UI for the bridge's panels (the Review / A-B panel and the Align panel): the same look as the HypnoMix
-- Probe and Main windows (hypnomix_ui.jsfx-inc) and the same step-by-step guide ("?" in the top-right corner).
-- Loaded by bridge.lua with dofile; returns a table of drawing functions. Coordinates are in window points: U.s turns
-- them into pixels on a Retina screen (gfx.ext_retina, asked for before gfx.init).
-- Clicks count on RELEASE over the same control (like the JSFX): REAPER does not start playing while the mouse is held.

local U = { s = 1, armed = nil, was = false, tour_on = false, tour_i = 1, tour_esc = false, measure = false }

local C = {
  bg = { 24, 22, 27 }, head = { 20, 18, 23 }, card = { 36, 33, 40 }, edge = { 58, 54, 64 }, text = { 238, 232, 222 },
  muted = { 160, 152, 144 }, amber = { 242, 168, 58 }, teal = { 96, 201, 168 }, red = { 217, 85, 94 },
  plain = { 54, 50, 60 }, dark = { 30, 22, 12 }, track = { 48, 45, 54 }, chip = { 44, 41, 49 }, chipon = { 66, 54, 34 },
}
U.C = C

function U.col(c, a) gfx.set(c[1] / 255, c[2] / 255, c[3] / 255, a or 1) end

function U.font(k)
  local s = U.s
  if k == 2 then gfx.setfont(2, "Arial", 13 * s, string.byte("b"))
  elseif k == 3 then gfx.setfont(3, "Arial", 11 * s)
  elseif k == 4 then gfx.setfont(4, "Arial", 26 * s, string.byte("b"))
  elseif k == 5 then gfx.setfont(5, "Arial", 15 * s, string.byte("b"))
  else gfx.setfont(1, "Arial", 13 * s) end
end

function U.rect(x, y, w, h) local s = U.s; gfx.rect(x * s, y * s, w * s, h * s, 1) end
function U.rrect(x, y, w, h, r)
  local s = U.s
  local R = math.min(r, w / 2, h / 2) * s
  x, y, w, h = x * s, y * s, w * s, h * s
  if R < 1 then gfx.rect(x, y, w, h, 1); return end
  gfx.rect(x + R, y, w - 2 * R, h, 1)
  gfx.rect(x, y + R, R, h - 2 * R, 1); gfx.rect(x + w - R, y + R, R, h - 2 * R, 1)
  gfx.circle(x + R, y + R, R, 1, 1); gfx.circle(x + w - R - 1, y + R, R, 1, 1)
  gfx.circle(x + R, y + h - R - 1, R, 1, 1); gfx.circle(x + w - R - 1, y + h - R - 1, R, 1, 1)
end
function U.outline(x, y, w, h, r) local s = U.s; gfx.roundrect(x * s, y * s, w * s, h * s, r * s, 1) end
function U.dot(x, y, r) local s = U.s; gfx.circle(x * s, y * s, r * s, 1, 1) end
function U.line(x0, y0, x1, y1) local s = U.s; gfx.line(x0 * s, y0 * s, x1 * s, y1 * s, 1) end

function U.text(x, y, t) gfx.x, gfx.y = x * U.s, y * U.s; gfx.drawstr(tostring(t or "")) end
function U.textw(t) return gfx.measurestr(tostring(t or "")) / U.s end
function U.textc(x, y, w, h, t)
  t = tostring(t or "")
  local tw, th = gfx.measurestr(t)
  gfx.x, gfx.y = x * U.s + (w * U.s - tw) / 2, y * U.s + (h * U.s - th) / 2
  gfx.drawstr(t)
end
function U.textr(x, y, t) t = tostring(t or ""); gfx.x, gfx.y = x * U.s - gfx.measurestr(t), y * U.s; gfx.drawstr(t) end

-- one long word (a track name, a path) cut by characters until it and `tail` fit in w points
local function cut(word, w, tail)
  while #word > 1 and gfx.measurestr(word .. tail) > w * U.s do
    word = word:sub(1, (utf8.offset(word, -1) or #word) - 1)
  end
  return word .. tail
end

-- word-wrapped text; returns the lines drawn (at most max_lines) and the height used
function U.wrap(t, x, y, w, lh, max_lines, measure)
  local lines, line = {}, ""
  for word in tostring(t or ""):gmatch("%S+") do
    local try = line == "" and word or (line .. " " .. word)
    if gfx.measurestr(try) > w * U.s and line ~= "" then lines[#lines + 1] = line; line = word
    else line = try end
  end
  if line ~= "" then lines[#lines + 1] = line end
  if max_lines and #lines > max_lines then
    lines = { table.unpack(lines, 1, max_lines) }
    local last = lines[max_lines]
    if last:find("%s") then
      last = last:gsub("%s*%S*$", "") .. " …"
      if gfx.measurestr(last) > w * U.s then last = cut(last:sub(1, -5), w, " …") end   -- its own first word too long
    else                                 -- one long word (a track name, a path): cut characters until it fits
      last = cut(last, w, " …")
    end
    lines[max_lines] = last
  end
  -- a line is wider than the box only when it is one word longer than the box (wrapping never adds a word that does
  -- not fit): cut that word too, on any line, the only line included
  for i, l in ipairs(lines) do
    if gfx.measurestr(l) > w * U.s then lines[i] = cut((l:gsub(" …$", "")), w, "…") end
  end
  if not measure then for i, l in ipairs(lines) do U.text(x, y + (i - 1) * lh, l) end end
  return #lines, #lines * lh
end

-- the frame
function U.begin()
  U.s = (gfx.ext_retina and gfx.ext_retina > 1) and gfx.ext_retina or 1
  U.w, U.h = gfx.w / U.s, gfx.h / U.s
  U.mx, U.my = gfx.mouse_x / U.s, gfx.mouse_y / U.s
  U.down = gfx.mouse_cap & 1 == 1
  U.press, U.release = U.down and not U.was, (not U.down) and U.was
  gfx.set(28 / 255, 25 / 255, 31 / 255, 1)
  gfx.rect(0, 0, gfx.w, gfx.h, 1)
  gfx.gradrect(0, 0, gfx.w, gfx.h, 28 / 255, 25 / 255, 31 / 255, 1, 0, 0, 0, 0,
               -6 / 255 / gfx.h, -5 / 255 / gfx.h, -5 / 255 / gfx.h, 0)
end
function U.finish() if U.release then U.armed = nil end; U.was = U.down end
function U.inside(x, y, w, h) return U.mx >= x and U.mx < x + w and U.my >= y and U.my < y + h end

-- a control that clicks: true on the frame it is released over (the guide blocks every control but its own)
local function clicked(id, x, y, w, h, own)
  local over = U.inside(x, y, w, h) and (own or not U.tour_on)
  if U.press and over then U.armed = id end
  return over, (U.release and U.armed == id and over)
end

-- style: "plain", "amber" (the main action), "red" (record / approve-danger), "teal" (on)
function U.button(id, x, y, w, h, label, style, own)
  local over, hit = clicked(id, x, y, w, h, own)
  U.col(style == "amber" and C.amber or style == "red" and { 196, 72, 82 } or style == "teal" and { 70, 168, 138 }
        or C.plain)
  U.rrect(x, y, w, h, 7)
  if over then gfx.set(1, 1, 1, (U.down and U.armed == id) and 0.06 or 0.1); U.rrect(x, y, w, h, 7) end
  U.col(style == "amber" and C.dark or C.text)
  U.font(2); U.textc(x, y, w, h, label)
  return hit
end
function U.bw(label, min) U.font(2); return math.max(min or 0, U.textw(label) + 26) end

function U.chip(id, x, y, w, label, on)
  local over, hit = clicked(id, x, y, w, 22)
  U.col(on and C.chipon or C.chip); U.rrect(x, y, w, 22, 11)
  if over and id then gfx.set(1, 1, 1, 0.08); U.rrect(x, y, w, 22, 11) end
  U.col(on and C.amber or C.text); U.font(3); U.textc(x, y, w, 22, label)
  return hit
end

function U.card(x, y, w, h) U.col(C.card); U.rrect(x, y, w, h, 10) end

-- the header: the amber lens, the title, a status line and the "?" (returns true when "?" is clicked)
function U.header(title, status)
  U.col(C.head); U.rect(0, 0, U.w, 36)
  U.col(C.amber); U.dot(18, 18, 6); U.col(C.head); U.dot(18, 18, 2.5)
  U.col(C.text); U.font(5); U.text(32, 10, title)
  local tx = 32 + U.textw(title) + 14
  U.col(C.muted); U.font(3)
  U.wrap(status or "", tx, 13, U.w - tx - 46, 13, 1)
  local over, hit = clicked("help", U.w - 33, 7, 22, 22, true)
  U.col(over and C.amber or { 70, 64, 76 }); U.dot(U.w - 22, 18, 10)
  U.col(over and C.dark or C.text); U.font(2); U.textc(U.w - 32, 8, 20, 20, "?")
  return hit
end

-- a slider: a rounded track, amber fill from zero; returns the area for dragging
function U.slider(x, y, w, v, lo, hi, label, shown)
  U.col(C.muted); U.font(3); U.text(x, y, label)
  local bx, by, bw = x + 62, y + 3, w - 62 - 52
  U.col(C.track); U.rrect(bx, by, bw, 8, 4)
  local z = (lo < 0) and (bx + bw * (0 - lo) / (hi - lo)) or bx
  local px = bx + bw * (v - lo) / (hi - lo)
  U.col(C.amber, (v == 0 and lo >= 0) and 0.35 or 1)
  U.rrect(math.min(z, px), by, math.max(8, math.abs(px - z)), 8, 4)
  U.col(C.text); U.dot(px, by + 4, 6)
  U.col(C.text); U.font(2); U.text(bx + bw + 12, y - 1, shown)
  return { x = bx, y = by - 6, w = bw, h = 20, lo = lo, hi = hi }
end

-- Where the guide's card goes: below the spot if it fits, else above; when neither fits, beside the spot on the side
-- with more room (if the card's buttons still fit there), else at the top or bottom edge that covers less of the spot.
-- Returns the card's width, x, y and height (points).
U.CARD_MIN = 240                         -- the narrowest card: Skip guide, Back and Next side by side
function U.tour_place(x, y, w, h, body)
  local function size(cw) U.font(1); local _, bh = U.wrap(body, 0, 0, cw - 28, 15, nil, true); return 43 + bh + 40 end
  local cw = math.min(400, U.w - 24)
  local ch = size(cw)
  local cx = math.max(12, math.min(U.w - cw - 12, x + w / 2 - cw / 2))
  if y + h + 14 + ch <= U.h - 6 then return cw, cx, y + h + 14, ch end
  if y - ch - 14 >= 6 then return cw, cx, y - ch - 14, ch end
  local right, left = U.w - (x + w + 14) - 6, x - 14 - 6
  local sw = math.min(400, math.max(right, left))
  if sw >= U.CARD_MIN then
    local sh = size(sw)
    if sh <= U.h - 12 then
      local sx = right >= left and (x + w + 14) or (x - 14 - sw)
      return sw, sx, math.max(6, math.min(U.h - sh - 6, y + h / 2 - sh / 2)), sh
    end
  end
  local top, bottom = 6, math.max(6, U.h - ch - 6)
  local over_top = math.max(0, math.min(top + ch, y + h) - math.max(top, y))
  local over_bottom = math.max(0, math.min(bottom + ch, y + h) - math.max(bottom, y))
  return cw, cx, (over_bottom < over_top) and bottom or top, ch
end

-- ---- the guide: steps = { {x, y, w, h, title, text}, ... } (a function of the current layout).
-- Returns "done" when the person finishes or skips it.
function U.tour_start() U.tour_on = true; U.tour_i = 1 end
function U.tour(steps)
  if not U.tour_on then return nil end
  local n = #steps
  U.tour_i = math.max(1, math.min(n, U.tour_i))
  local st = steps[U.tour_i]
  local x, y, w, h, title, body = table.unpack(st)
  gfx.set(0, 0, 0, 0.62)
  U.rect(0, 0, U.w, y - 4); U.rect(0, y + h + 4, U.w, U.h - y - h - 4)
  U.rect(0, y - 4, x - 4, h + 8); U.rect(x + w + 4, y - 4, U.w - x - w - 4, h + 8)
  U.col(C.amber); U.outline(x - 4, y - 4, w + 8, h + 8, 8); U.outline(x - 5, y - 5, w + 10, h + 10, 9)
  local cw, cx, cy, ch = U.tour_place(x, y, w, h, body)
  gfx.set(14 / 255, 12 / 255, 16 / 255, 0.5); U.rrect(cx + 2, cy + 3, cw, ch, 12)
  gfx.set(250 / 255, 246 / 255, 238 / 255, 1); U.rrect(cx, cy, cw, ch, 12)
  gfx.set(176 / 255, 112 / 255, 20 / 255, 1); U.font(3); U.text(cx + 14, cy + 10, ("STEP %d OF %d"):format(U.tour_i, n))
  gfx.set(28 / 255, 24 / 255, 30 / 255, 1); U.font(2); U.text(cx + 14, cy + 25, title)
  gfx.set(64 / 255, 58 / 255, 66 / 255, 1); U.font(1); U.wrap(body, cx + 14, cy + 43, cw - 28, 15)
  local bw, result = 64, nil
  if U.tour_i > 1 and U.button("tour_back", cx + cw - 2 * bw - 22, cy + ch - 30, bw, 22, "Back", "plain", true) then
    U.tour_i = U.tour_i - 1
  end
  if U.button("tour_next", cx + cw - bw - 14, cy + ch - 30, bw, 22, U.tour_i == n and "Done" or "Next", "amber", true) then
    if U.tour_i < n then U.tour_i = U.tour_i + 1 else result = "done" end
  end
  local over, hit = clicked("tour_skip", cx + 14, cy + ch - 26, 60, 16, true)
  if over then gfx.set(176 / 255, 112 / 255, 20 / 255, 1) else gfx.set(140 / 255, 128 / 255, 120 / 255, 1) end
  U.font(3); U.text(cx + 14, cy + ch - 24, "Skip guide")
  if hit or U.tour_esc then result = "done" end          -- Esc (bridge.lua) skips the guide like "Skip guide"
  U.tour_esc = false
  if result then U.tour_on = false end
  return result
end

-- The guide is shown the first time each panel opens on this computer (kept in REAPER's extended state, persisted)
function U.seen(key) return reaper.GetExtState("hypnomix", "guide_" .. key) == "1" end
function U.mark_seen(key) reaper.SetExtState("hypnomix", "guide_" .. key, "1", true) end

return U
