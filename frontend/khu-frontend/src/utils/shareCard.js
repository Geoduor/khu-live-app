/**
 * shareCard.js — draws a clean, shareable PNG of a match result or a
 * table (canvas, no extra dependency) and shares it via the phone's
 * share sheet (WhatsApp etc.), falling back to a download.
 *
 * Every card carries the app name, an "Unofficial fan app" label in the
 * header, and just the link in the footer.
 *
 * Callers pass logo URLs that are already resolved through the backend
 * logo proxy (api.teamLogoUrl); a logo that fails to load is replaced by
 * a neutral initials badge, never a broken image.
 */

const RED = "#BB0000";
const GREEN = "#006600";
const AMBER = "#D98A00";
const INK = "#1a0f12";
const MUTED = "#6f6468";
const FONT = "'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

// The one link every shared image and share message carries.
const SHARE_URL = "offpitchafrica.com";

function appLink() {
  return SHARE_URL;
}

function tryLoad(src, timeoutMs) {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    const t = setTimeout(() => { img.onload = img.onerror = null; resolve(null); }, timeoutMs);
    img.onload = () => { clearTimeout(t); resolve(img); };
    img.onerror = () => { clearTimeout(t); resolve(null); };
    img.src = src;
  });
}

/**
 * Loads an image for canvas use. Logos come through the backend proxy,
 * which can be slow on a cold start, so we allow a generous timeout and
 * retry once. The retry adds a cache-busting parameter: the same logo
 * may already sit in the browser cache from a plain <img> load (no CORS
 * headers), and a cached copy like that can't be drawn into a canvas
 * we later export.
 */
async function loadImage(src, timeoutMs = 12000) {
  if (!src) return null;
  // Backend logo proxy URLs: ask for the image as a data URL instead (via
  // the same CORS-enabled API calls the app already makes). A data URL is
  // never "cross-origin", so the canvas can always be exported.
  if (src.includes("/api/logo?")) {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      const resp = await fetch(src.replace("/api/logo?", "/api/logo-data?"), { signal: ctrl.signal });
      clearTimeout(t);
      if (resp.ok) {
        const { data_url } = await resp.json();
        const img = await tryLoad(data_url, timeoutMs);
        if (img) return img;
      }
    } catch (e) { /* fall through to the plain image load */ }
  }
  const first = await tryLoad(src, timeoutMs);
  if (first) return first;
  const sep = src.includes("?") ? "&" : "?";
  return tryLoad(`${src}${sep}cors=${Date.now()}`, timeoutMs);
}

function khuCrestUrl() {
  return `${process.env.PUBLIC_URL || ""}/khu-crest.png`;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Wraps text into at most maxLines lines that fit maxWidth. */
function wrapLines(ctx, text, maxWidth, maxLines = 2) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const w of words) {
    const test = cur ? `${cur} ${w}` : w;
    if (ctx.measureText(test).width <= maxWidth || !cur) cur = test;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    let last = kept[maxLines - 1];
    while (ctx.measureText(last + "…").width > maxWidth && last.length > 1) last = last.slice(0, -1);
    kept[maxLines - 1] = last + "…";
    return kept;
  }
  return lines;
}

function titleLineCount(title, font, maxWidth) {
  const c = document.createElement("canvas").getContext("2d");
  c.font = font;
  return wrapLines(c, String(title || "").toUpperCase(), maxWidth, 2).length;
}

function initials(name) {
  const parts = String(name || "?").replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function drawLogo(ctx, img, name, cx, cy, size) {
  const r = size / 2;
  ctx.save();
  ctx.shadowColor = "rgba(40,10,15,0.18)";
  ctx.shadowBlur = size * 0.12;
  ctx.shadowOffsetY = size * 0.04;
  ctx.fillStyle = "#fff";
  roundRect(ctx, cx - r, cy - r, size, size, size * 0.22);
  ctx.fill();
  ctx.restore();
  if (img && img.width) {
    const pad = size * 0.10;
    const box = size - pad * 2;
    const scale = Math.min(box / img.width, box / img.height);
    const w = img.width * scale, h = img.height * scale;
    ctx.drawImage(img, cx - w / 2, cy - h / 2, w, h);
  } else {
    ctx.fillStyle = "#EFE6E8";
    roundRect(ctx, cx - r, cy - r, size, size, size * 0.22);
    ctx.fill();
    ctx.fillStyle = MUTED;
    ctx.font = `800 ${size * 0.38}px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(initials(name), cx, cy + size * 0.02);
  }
}

function background(ctx, w, h) {
  ctx.fillStyle = "#FBF8F7";
  ctx.fillRect(0, 0, w, h);
  let g = ctx.createRadialGradient(0, 0, 0, 0, 0, w * 0.9);
  g.addColorStop(0, "rgba(187,0,0,0.14)"); g.addColorStop(1, "rgba(187,0,0,0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  g = ctx.createRadialGradient(w, h * 0.3, 0, w, h * 0.3, w * 0.9);
  g.addColorStop(0, "rgba(0,102,0,0.12)"); g.addColorStop(1, "rgba(0,102,0,0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  const third = w / 3;
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, third, 18);
  ctx.fillStyle = RED; ctx.fillRect(third, 0, third, 18);
  ctx.fillStyle = GREEN; ctx.fillRect(third * 2, 0, third, 18);
}

function header(ctx, w, crest) {
  ctx.textBaseline = "alphabetic";
  let x = 60;
  if (crest && crest.width) {
    const h = 92, cw = crest.width * (h / crest.height);
    ctx.drawImage(crest, 60, 38, cw, h);
    x = 60 + cw + 22;
  }
  ctx.textAlign = "left";
  ctx.font = `900 54px ${FONT}`;
  ctx.fillStyle = INK;
  ctx.fillText("KHU ", x, 108);
  const kw = ctx.measureText("KHU ").width;
  ctx.fillStyle = RED;
  ctx.fillText("LIVE", x + kw, 108);
  ctx.textAlign = "right";
  ctx.font = `700 24px ${FONT}`;
  ctx.fillStyle = MUTED;
  ctx.fillText("UNOFFICIAL FAN APP", w - 60, 106);
}

/**
 * Footer: just the link, set in a red pill so it reads as the call to
 * action. (`sourceLine` is accepted for compatibility but no longer drawn;
 * the header still carries the "Unofficial fan app" label.)
 */
function footer(ctx, w, h) {
  ctx.fillStyle = "rgba(26,15,18,0.10)";
  ctx.fillRect(60, h - 190, w - 120, 2);
  const text = appLink();
  ctx.font = `800 46px ${FONT}`;
  const pw = Math.min(w - 160, ctx.measureText(text).width + 120);
  const ph = 84;
  const cy = h - 95;
  ctx.fillStyle = RED;
  roundRect(ctx, w / 2 - pw / 2, cy - ph / 2, pw, ph, ph / 2);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, w / 2, cy + 2);
  ctx.textBaseline = "alphabetic";
}

async function ensureFonts() {
  try {
    if (document.fonts && document.fonts.load) {
      await Promise.all([document.fonts.load(`900 40px Inter`), document.fonts.load(`500 24px Inter`)]);
    }
  } catch (e) { /* fall back to system fonts */ }
}

function groupScorers(scorers, side) {
  const by = new Map();
  (scorers || []).filter((s) => s.team === side).forEach((s) => {
    if (!by.has(s.player_name)) by.set(s.player_name, []);
    if (s.minute != null) by.get(s.player_name).push(s.minute);
  });
  return [...by.entries()].map(([name, mins]) => (mins.length ? `${name} ${mins.sort((a, b) => a - b).map((m) => m + "'").join(", ")}` : name));
}

/**
 * Match card. `match`: { league, date, home_team, away_team, home_score,
 * away_score, home_logo, away_logo (resolved URLs), state, venue, scorers }
 * `sourceLine`: e.g. "Data: kenyahockeyunion.org".
 */
export async function renderMatchCard(match, sourceLine = "Data: kenyahockeyunion.org") {
  await ensureFonts();
  const W = 1080, H = 1350;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  const [homeImg, awayImg, crest] = await Promise.all([loadImage(match.home_logo), loadImage(match.away_logo), loadImage(khuCrestUrl())]);

  background(ctx, W, H);
  header(ctx, W, crest);

  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.font = `800 40px ${FONT}`;
  ctx.fillStyle = AMBER;
  const leagueLines = wrapLines(ctx, String(match.league || "").toUpperCase(), W - 160, 2);
  leagueLines.forEach((l, i) => ctx.fillText(l, W / 2, 230 + i * 48));
  let y = 230 + leagueLines.length * 48;
  if (match.date) {
    ctx.font = `500 30px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(match.date, W / 2, y + 6);
    y += 50;
  }

  const pill = match.state === "LIVE" ? "LIVE" : match.state === "NS" ? "UPCOMING" : "FULL TIME";
  ctx.font = `800 28px ${FONT}`;
  const pw = ctx.measureText(pill).width + 64;
  ctx.fillStyle = match.state === "LIVE" ? RED : match.state === "NS" ? AMBER : INK;
  roundRect(ctx, W / 2 - pw / 2, y + 14, pw, 56, 28);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.textBaseline = "middle";
  ctx.fillText(pill, W / 2, y + 43);
  ctx.textBaseline = "alphabetic";

  const cy = 640;
  drawLogo(ctx, homeImg, match.home_team, 190, cy, 210);
  drawLogo(ctx, awayImg, match.away_team, 890, cy, 210);

  ctx.fillStyle = INK;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  if (match.home_score != null && match.away_score != null) {
    ctx.font = `900 170px ${FONT}`;
    ctx.fillText(`${match.home_score} – ${match.away_score}`, W / 2, cy + 6);
  } else {
    ctx.font = `900 120px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText("VS", W / 2, cy + 6);
  }
  ctx.textBaseline = "alphabetic";

  ctx.font = `800 40px ${FONT}`;
  ctx.fillStyle = INK;
  [[match.home_team, 190], [match.away_team, 890]].forEach(([name, x]) => {
    wrapLines(ctx, name || "TBD", 380, 2).forEach((l, i) => ctx.fillText(l, x, 810 + i * 48));
  });

  // Scorers (only when we have them) — home on the left, away on the right.
  const hs = groupScorers(match.scorers, "home"), as = groupScorers(match.scorers, "away");
  let sy = 990;
  if (hs.length || as.length) {
    ctx.font = `700 24px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText("GOALS", W / 2, sy);
    sy += 14;
    ctx.font = `600 32px ${FONT}`;
    ctx.fillStyle = INK;
    const rows = Math.min(Math.max(hs.length, as.length), 4);
    const baseY = sy + 44;
    ctx.textAlign = "center";
    for (let i = 0; i < rows; i++) {
      const lineY = baseY + i * 46;
      if (hs[i]) ctx.fillText(wrapLines(ctx, hs[i], 440, 1)[0], 270, lineY);
      if (as[i]) ctx.fillText(wrapLines(ctx, as[i], 440, 1)[0], 810, lineY);
    }
    sy = baseY + rows * 46;
  }
  if (match.venue) {
    ctx.textAlign = "center";
    ctx.font = `500 28px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(`Venue: ${match.venue}`, W / 2, Math.min(sy + 40, H - 230));
  }

  footer(ctx, W, H, sourceLine);
  return canvas;
}

/**
 * Table card. `rows`: [{ position, team, logo (resolved URL), played, won,
 * drawn, lost, goal_diff, points }]
 */
export async function renderTableCard({ title, subtitle, rows }, sourceLine = "Data: kenyahockeyunion.org") {
  await ensureFonts();
  const W = 1080;
  const list = rows.slice(0, 14);
  const rowH = 92;
  const topH = 330 + (titleLineCount(title, `900 62px ${FONT}`, W - 120) - 1) * 66;
  const H = topH + list.length * rowH + 250;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  const [crest, ...imgs] = await Promise.all([loadImage(khuCrestUrl()), ...list.map((r) => loadImage(r.logo))]);

  background(ctx, W, H);
  header(ctx, W, crest);

  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.font = `900 62px ${FONT}`;
  ctx.fillStyle = INK;
  const tl = wrapLines(ctx, String(title || "").toUpperCase(), W - 120, 2);
  tl.forEach((l, i) => ctx.fillText(l, 60, 205 + i * 66));
  const sy = 205 + (tl.length - 1) * 66 + 50;
  if (subtitle) {
    ctx.font = `500 30px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(subtitle, 60, sy);
  }

  const colX = { p: 640, w: 710, d: 780, l: 850, gd: 930, pts: 1020 };
  const hy = topH - 14;
  ctx.font = `700 24px ${FONT}`;
  ctx.fillStyle = MUTED;
  ctx.textAlign = "left";
  ctx.fillText("TEAM", 60, hy);
  ctx.textAlign = "right";
  [["P", colX.p], ["W", colX.w], ["D", colX.d], ["L", colX.l], ["GD", colX.gd]].forEach(([t, x]) => ctx.fillText(t, x, hy));
  ctx.fillStyle = AMBER;
  ctx.fillText("PTS", colX.pts, hy);

  list.forEach((r, i) => {
    const top = topH + i * rowH;
    ctx.fillStyle = i % 2 === 0 ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.35)";
    roundRect(ctx, 40, top, W - 80, rowH - 8, 22);
    ctx.fill();
    const cy = top + (rowH - 8) / 2;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.font = `700 28px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(String(r.position ?? i + 1), 82, cy);
    drawLogo(ctx, imgs[i], r.team, 158, cy, 58);
    ctx.textAlign = "left";
    ctx.font = `800 31px ${FONT}`;
    ctx.fillStyle = INK;
    const name = wrapLines(ctx, r.team, 380, 1)[0] || "";
    ctx.fillText(name, 205, cy);
    ctx.textAlign = "right";
    ctx.font = `600 30px ${FONT}`;
    ctx.fillStyle = MUTED;
    [[r.played, colX.p], [r.won, colX.w], [r.drawn, colX.d], [r.lost, colX.l]].forEach(([v, x]) => ctx.fillText(String(v ?? ""), x, cy));
    const gd = parseInt(r.goal_diff, 10);
    ctx.fillStyle = isNaN(gd) || gd === 0 ? MUTED : gd > 0 ? GREEN : RED;
    ctx.fillText(isNaN(gd) ? String(r.goal_diff ?? "") : gd > 0 ? `+${gd}` : String(gd), colX.gd, cy);
    ctx.font = `900 36px ${FONT}`;
    ctx.fillStyle = AMBER;
    ctx.fillText(String(r.points ?? ""), colX.pts, cy);
  });
  ctx.textBaseline = "alphabetic";

  footer(ctx, W, H, sourceLine);
  return canvas;
}

/**
 * Top-scorers card. `rows`: [{ player_name, team_name, goals }]
 */
export async function renderScorersCard({ title, subtitle, rows }, sourceLine = "Data: kenyahockeyunion.org") {
  await ensureFonts();
  const W = 1080;
  const list = rows.slice(0, 10);
  const rowH = 100;
  const topH = 320 + (titleLineCount(title || "TOP SCORERS", `900 62px ${FONT}`, W - 120) - 1) * 66;
  const H = topH + list.length * rowH + 250;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  const crest = await loadImage(khuCrestUrl());

  background(ctx, W, H);
  header(ctx, W, crest);

  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.font = `900 62px ${FONT}`;
  ctx.fillStyle = INK;
  const tl = wrapLines(ctx, String(title || "TOP SCORERS").toUpperCase(), W - 120, 2);
  tl.forEach((l, i) => ctx.fillText(l, 60, 205 + i * 66));
  if (subtitle) {
    ctx.font = `500 30px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(subtitle, 60, 205 + (tl.length - 1) * 66 + 50);
  }

  const hy = topH - 14;
  ctx.font = `700 24px ${FONT}`;
  ctx.fillStyle = MUTED;
  ctx.textAlign = "left";
  ctx.fillText("PLAYER", 60, hy);
  ctx.textAlign = "right";
  ctx.fillStyle = AMBER;
  ctx.fillText("GOALS", W - 70, hy);

  list.forEach((r, i) => {
    const top = topH + i * rowH;
    ctx.fillStyle = i % 2 === 0 ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.35)";
    roundRect(ctx, 40, top, W - 80, rowH - 8, 22);
    ctx.fill();
    const cy = top + (rowH - 8) / 2;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.font = `800 32px ${FONT}`;
    ctx.fillStyle = i === 0 ? AMBER : MUTED;
    ctx.fillText(String(i + 1), 92, cy);
    ctx.textAlign = "left";
    ctx.font = `800 34px ${FONT}`;
    ctx.fillStyle = INK;
    ctx.fillText(wrapLines(ctx, r.player_name, 600, 1)[0] || "", 150, cy - 14);
    ctx.font = `500 25px ${FONT}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(wrapLines(ctx, r.team_name || "", 600, 1)[0] || "", 150, cy + 22);
    ctx.textAlign = "right";
    ctx.font = `900 48px ${FONT}`;
    ctx.fillStyle = AMBER;
    ctx.fillText(String(r.goals ?? 0), W - 70, cy);
  });
  ctx.textBaseline = "alphabetic";

  footer(ctx, W, H, sourceLine);
  return canvas;
}

/** Share via the native share sheet (WhatsApp, etc.); download as fallback. */
export async function shareCanvas(canvas, filename, text) {
  const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
  if (!blob) throw new Error("Could not create the image.");
  const file = new File([blob], filename, { type: "image/png" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], text });
      return "shared";
    } catch (e) {
      if (e && e.name === "AbortError") return "cancelled";
      // any other failure → fall through to download
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return "downloaded";
}

export function slug(s) {
  return String(s || "share").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}

export function shareText(line) {
  return `${line}\nhttps://${appLink()}`;
}
