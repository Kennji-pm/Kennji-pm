#!/usr/bin/env python3
"""Render Kennji-pm — a WinUI-inspired GitHub profile dashboard.

Designed for a GitHub profile README. The script fetches public GitHub data and
Boot.dev's public profile thumbnail, then renders a single PNG so GitHub's
Markdown sanitizer never needs custom CSS or JavaScript.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import math
import os
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

USER = "Kennji-pm"
DISPLAY_NAME = "Hayakawa Kennji"
HANDLE = "_kennji"
LOCATION = "Vietnam"
ORG = "Vastellic Interactive"
BOOTDEV_URL = "https://api.boot.dev/v1/users/public/6ae174f9-7062-4288-b02c-d9f01206d47a/thumbnail"
FEATURED = ["NightfallAutoQuest", "StarlightAbsolute-Bot", "PearlUI_Rainmeter"]
OUT = Path(__file__).resolve().parents[1] / "assets" / "kennji-pm.png"

W, H = 1600, 1180

# Palette — restrained violet/cyan on neutral graphite.
BG = "#06070B"
WINDOW = "#0B0D14"
PANEL = "#10131D"
PANEL_2 = "#0E111A"
BORDER = "#242938"
TEXT = "#F2F4F8"
MUTED = "#8E95A6"
VIOLET = "#8B5CF6"
VIOLET_2 = "#A78BFA"
CYAN = "#67E8F9"
GREEN = "#7EE787"
RED = "#FF6B81"

FONT_REG = "/usr/share/fonts/opentype/inter/InterDisplay-Regular.otf"
FONT_MED = "/usr/share/fonts/opentype/inter/InterDisplay-Medium.otf"
FONT_BOLD = "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [path, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()

F11 = font(FONT_MONO, 11)
F12 = font(FONT_REG, 12)
F13 = font(FONT_REG, 13)
F14 = font(FONT_REG, 14)
F15 = font(FONT_MED, 15)
F16 = font(FONT_MED, 16)
F18 = font(FONT_MED, 18)
F20 = font(FONT_MED, 20)
F24 = font(FONT_BOLD, 24)
F28 = font(FONT_BOLD, 28)
F36 = font(FONT_BOLD, 36)
F50 = font(FONT_BOLD, 50)
M11 = font(FONT_MONO, 11)
M12 = font(FONT_MONO, 12)
M13 = font(FONT_MONO, 13)
M14 = font(FONT_MONO, 14)
M16 = font(FONT_MONO_BOLD, 16)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Kennji-pm-Profile-Renderer/1.0", "Accept": "application/vnd.github+json"})
TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
if TOKEN:
    SESSION.headers["Authorization"] = f"Bearer {TOKEN}"


@dataclass
class Repo:
    name: str
    description: str
    language: str
    stars: int
    forks: int
    url: str
    pushed_at: str


def get_json(url: str, *, timeout: int = 16):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def github_data(demo: bool = False):
    if demo:
        return demo_data()

    try:
        profile = get_json(f"https://api.github.com/users/{USER}")
        repos_raw = get_json(f"https://api.github.com/users/{USER}/repos?per_page=100&sort=updated")
    except Exception as exc:
        print(f"[warn] GitHub REST unavailable: {exc}")
        return demo_data(network_error=True)

    repos_by_name = {r["name"]: r for r in repos_raw if not r.get("fork")}
    chosen = []
    for name in FEATURED:
        if name in repos_by_name:
            chosen.append(repos_by_name[name])
    if len(chosen) < 3:
        for r in repos_raw:
            if r.get("fork") or r in chosen:
                continue
            chosen.append(r)
            if len(chosen) >= 3:
                break

    repos = [Repo(
        name=r.get("name", "unknown"),
        description=(r.get("description") or "No public description.").strip(),
        language=r.get("language") or "mixed",
        stars=int(r.get("stargazers_count", 0)),
        forks=int(r.get("forks_count", 0)),
        url=r.get("html_url") or f"https://github.com/{USER}/{r.get('name', '')}",
        pushed_at=r.get("pushed_at") or "",
    ) for r in chosen[:3]]

    lang_totals: dict[str, int] = {}
    # Aggregate repository language byte counts. Limit to avoid excessive API calls.
    for r in repos_raw[:18]:
        if r.get("fork"):
            continue
        try:
            langs = get_json(r["languages_url"])
            for k, v in langs.items():
                lang_totals[k] = lang_totals.get(k, 0) + int(v)
        except Exception:
            lang = r.get("language")
            if lang:
                lang_totals[lang] = lang_totals.get(lang, 0) + 1

    contrib = contribution_calendar()
    return {
        "public_repos": int(profile.get("public_repos", 0)),
        "followers": int(profile.get("followers", 0)),
        "following": int(profile.get("following", 0)),
        "avatar_url": profile.get("avatar_url"),
        "repos": repos,
        "languages": lang_totals,
        "contrib": contrib,
        "updated": dt.datetime.now(dt.timezone.utc),
        "network_error": False,
    }


def contribution_calendar():
    if not TOKEN:
        return []
    today = dt.datetime.now(dt.timezone.utc)
    start = today - dt.timedelta(days=182)
    query = """
      query($login:String!, $from:DateTime!, $to:DateTime!) {
        user(login:$login) {
          contributionsCollection(from:$from, to:$to) {
            contributionCalendar {
              weeks { contributionDays { date contributionCount color } }
            }
          }
        }
      }
    """
    try:
        r = SESSION.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": {"login": USER, "from": start.isoformat(), "to": today.isoformat()}},
            timeout=20,
        )
        r.raise_for_status()
        weeks = r.json()["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        return [[int(day["contributionCount"]) for day in week["contributionDays"]] for week in weeks][-26:]
    except Exception as exc:
        print(f"[warn] contribution calendar unavailable: {exc}")
        return []


def demo_data(network_error: bool = False):
    # Preview fallback only. It is deliberately labelled as preview in the image.
    seed = random.Random(66234381)
    weeks = []
    for w in range(26):
        week = []
        for d in range(7):
            p = 0.40 + 0.15 * math.sin(w / 3.8)
            week.append(seed.randint(1, 6) if seed.random() < p else 0)
        weeks.append(week)
    return {
        "public_repos": 14,
        "followers": 3,
        "following": 0,
        "avatar_url": None,
        "repos": [
            Repo("NightfallAutoQuest", "Minecraft systems project in the Nightfall series.", "Java", 0, 0, f"https://github.com/{USER}/NightfallAutoQuest", ""),
            Repo("StarlightAbsolute-Bot", "Starlight Absolute Discord Project", "JavaScript", 0, 0, f"https://github.com/{USER}/StarlightAbsolute-Bot", ""),
            Repo("PearlUI_Rainmeter", "Desktop interface experiments for Rainmeter.", "Rainmeter", 0, 0, f"https://github.com/{USER}/PearlUI_Rainmeter", ""),
        ],
        "languages": {"Java": 46, "Python": 27, "JavaScript": 18, "Other": 9},
        "contrib": weeks,
        "updated": dt.datetime.now(dt.timezone.utc),
        "network_error": network_error,
    }


def fetch_image(url: str | None, size: tuple[int, int]) -> Image.Image | None:
    if not url:
        return None
    try:
        r = SESSION.get(url, timeout=20)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        return ImageOps.fit(im, size, method=Image.Resampling.LANCZOS)
    except Exception as exc:
        print(f"[warn] image unavailable {url}: {exc}")
        return None


def gradient_background() -> Image.Image:
    base = Image.new("RGB", (W, H), BG)
    px = base.load()
    c0 = (6, 7, 11)
    c1 = (13, 8, 30)
    for y in range(H):
        for x in range(W):
            # Two soft radial glows; intentionally subtle.
            d1 = math.dist((x, y), (1220, 130)) / 900
            d2 = math.dist((x, y), (270, 1040)) / 820
            a = max(0.0, 1.0 - d1) * 0.33
            b = max(0.0, 1.0 - d2) * 0.14
            r = int(c0[0] * (1-a-b) + c1[0] * (a+b) + 8*b)
            g = int(c0[1] * (1-a-b) + c1[1] * (a+b))
            bl = int(c0[2] * (1-a-b) + c1[2] * (a+b) + 8*a)
            px[x, y] = (r, g, bl)
    # Faint noise makes gradients less synthetic/banded.
    noise = Image.effect_noise((W, H), 6).convert("L")
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(base, noise_rgb, 0.025)


def rr(draw, box, radius=18, fill=PANEL, outline=BORDER, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(draw, xy, s, f=F14, fill=TEXT, anchor=None):
    draw.text(xy, s, font=f, fill=fill, anchor=anchor)


def fit_text(draw, value: str, max_width: int, f, max_lines: int = 2):
    words = value.split()
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=f) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
            if len(lines) == max_lines - 1:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    original = " ".join(lines)
    if len(original) < len(value) and lines:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=f) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def paste_circle(canvas, im: Image.Image, box, border=VIOLET):
    x0, y0, x1, y1 = box
    w, h = x1-x0, y1-y0
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, w-1, h-1), fill=255)
    canvas.paste(im.resize((w, h)), (x0, y0), mask)
    d = ImageDraw.Draw(canvas)
    d.ellipse(box, outline=border, width=3)


def draw_icon(draw, cx, cy, kind, active=False):
    col = TEXT if active else MUTED
    if active:
        draw.rounded_rectangle((cx-20, cy-20, cx+20, cy+20), radius=10, fill="#1A1530")
    if kind == "home":
        draw.line((cx-8, cy, cx, cy-8, cx+8, cy), fill=col, width=2)
        draw.rectangle((cx-6, cy, cx+6, cy+8), outline=col, width=2)
    elif kind == "folder":
        draw.rounded_rectangle((cx-9, cy-6, cx+10, cy+7), radius=2, outline=col, width=2)
        draw.line((cx-7, cy-7, cx-1, cy-7, cx+2, cy-4), fill=col, width=2)
    elif kind == "chart":
        draw.line((cx-8, cy+8, cx-8, cy+1), fill=col, width=3)
        draw.line((cx, cy+8, cx, cy-8), fill=col, width=3)
        draw.line((cx+8, cy+8, cx+8, cy-3), fill=col, width=3)
    elif kind == "terminal":
        draw.rounded_rectangle((cx-10, cy-8, cx+10, cy+8), radius=3, outline=col, width=2)
        draw.line((cx-6, cy-3, cx-2, cy, cx-6, cy+3), fill=col, width=2)
        draw.line((cx+1, cy+4, cx+6, cy+4), fill=col, width=2)


def render(data, *, demo=False):
    canvas = gradient_background().convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # Window shadow.
    shadow = Image.new("RGBA", canvas.size, (0,0,0,0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((45, 42, W-45, H-40), radius=32, fill=(0,0,0,180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    canvas.alpha_composite(shadow)
    d = ImageDraw.Draw(canvas)

    # Main WinUI-like shell.
    rr(d, (52, 42, W-52, H-48), radius=30, fill=WINDOW, outline="#303548", width=2)

    # Titlebar.
    d.rounded_rectangle((53, 43, W-53, 111), radius=28, fill="#0D1018")
    d.rectangle((53, 80, W-53, 111), fill="#0D1018")
    d.line((53, 111, W-53, 111), fill=BORDER, width=1)
    # App glyph.
    rr(d, (82, 63, 112, 93), radius=8, fill="#19142B", outline="#3B2A68")
    text(d, (97, 78), "K", M16, VIOLET_2, anchor="mm")
    text(d, (128, 78), "Kennji Studio", F15, TEXT, anchor="lm")
    text(d, (241, 78), "/ portfolio.os", M11, MUTED, anchor="lm")

    # Win window controls.
    ctrl_y = 78
    d.line((W-178, ctrl_y, W-164, ctrl_y), fill=MUTED, width=2)
    d.rectangle((W-130, ctrl_y-6, W-118, ctrl_y+6), outline=MUTED, width=1)
    d.line((W-78, ctrl_y-6, W-66, ctrl_y+6), fill=RED, width=2)
    d.line((W-66, ctrl_y-6, W-78, ctrl_y+6), fill=RED, width=2)

    # Sidebar.
    d.rectangle((53, 112, 218, H-49), fill="#090B12")
    d.line((218, 112, 218, H-49), fill=BORDER, width=1)
    sidebar_items = [("home", "Overview"), ("folder", "Projects"), ("chart", "Signal"), ("terminal", "Console")]
    sy = 168
    for i, (ico, label) in enumerate(sidebar_items):
        active = i == 0
        draw_icon(d, 88, sy, ico, active)
        text(d, (119, sy), label, F13, TEXT if active else MUTED, anchor="lm")
        sy += 58
    text(d, (84, H-111), "KENNJI OS", M11, VIOLET_2)
    text(d, (84, H-91), "BUILD 2026.09", M11, MUTED)

    # Main content coords.
    left = 252
    right = W - 86
    content_w = right - left

    # Hero card.
    hero = (left, 142, right, 386)
    rr(d, hero, radius=24, fill="#0E111A", outline="#292F40")
    # translucent accent panel on right
    d.rounded_rectangle((right-325, 158, right-18, 370), radius=20, fill="#111525", outline="#2B3350")

    avatar = fetch_image(data.get("avatar_url"), (140, 140)) if not demo else None
    if avatar:
        paste_circle(canvas, avatar, (287, 192, 427, 332))
        d = ImageDraw.Draw(canvas)
    else:
        d.ellipse((287, 192, 427, 332), fill="#14182A", outline=VIOLET, width=3)
        text(d, (357, 262), "K", font(FONT_BOLD, 58), VIOLET_2, anchor="mm")

    text(d, (458, 189), HANDLE, M13, VIOLET_2)
    text(d, (458, 216), DISPLAY_NAME, F50, TEXT)
    text(d, (460, 278), "Minecraft systems  /  Discord automation  /  desktop interfaces", F18, "#C8CDDA")
    text(d, (460, 314), "Build systems. Measure failure. Refactor the cause.", M13, MUTED)

    # Status panel.
    text(d, (right-292, 188), "CURRENT SIGNAL", M11, MUTED)
    d.ellipse((right-293, 219, right-281, 231), fill=GREEN)
    text(d, (right-268, 226), "ONLINE", M12, TEXT, anchor="lm")
    text(d, (right-292, 266), "FOCUS", M11, MUTED)
    text(d, (right-292, 288), "systems / tooling", F15, TEXT)
    text(d, (right-292, 326), "LOCATION", M11, MUTED)
    text(d, (right-292, 348), f"{LOCATION}  ·  UTC+07", F15, TEXT)

    # Metrics row.
    metrics_y0, metrics_y1 = 410, 520
    gap = 14
    card_w = (content_w - gap*3) // 4
    metrics = [
        ("PUBLIC REPOS", str(data.get("public_repos", "—")), "github / source"),
        ("FOLLOWERS", str(data.get("followers", "—")), "public profile"),
        ("FEATURED", str(len(data.get("repos", []))), "selected work"),
        ("MODE", "BUILD", "ship / verify / repeat"),
    ]
    for i, (lab, val, sub) in enumerate(metrics):
        x0 = left + i*(card_w+gap)
        rr(d, (x0, metrics_y0, x0+card_w, metrics_y1), radius=18, fill=PANEL, outline=BORDER)
        text(d, (x0+20, metrics_y0+21), lab, M11, MUTED)
        text(d, (x0+20, metrics_y0+47), val, F28, TEXT)
        text(d, (x0+20, metrics_y0+82), sub, F12, "#747C90")

    # Projects.
    text(d, (left, 561), "SELECTED WORK", M12, VIOLET_2)
    text(d, (left, 585), "Pinned like windows, not trophies.", F13, MUTED)
    py0, py1 = 620, 778
    p_gap = 14
    p_w = (content_w - p_gap*2) // 3
    for i, repo in enumerate(data.get("repos", [])[:3]):
        x0 = left + i*(p_w+p_gap)
        rr(d, (x0, py0, x0+p_w, py1), radius=18, fill=PANEL_2, outline=BORDER)
        # tiny app tile
        rr(d, (x0+18, py0+18, x0+50, py0+50), radius=8, fill="#19142B", outline="#3B2A68")
        text(d, (x0+34, py0+34), repo.name[:1].upper(), M13, VIOLET_2, anchor="mm")
        title = repo.name if len(repo.name) <= 22 else repo.name[:21] + "…"
        text(d, (x0+62, py0+20), title, F16, TEXT)
        text(d, (x0+62, py0+43), repo.language.upper(), M11, CYAN)
        lines = fit_text(d, repo.description, p_w-36, F13, 2)
        yy = py0+76
        for line in lines:
            text(d, (x0+18, yy), line, F13, MUTED)
            yy += 20
        text(d, (x0+18, py1-28), f"stars {repo.stars:02d}   forks {repo.forks:02d}", M11, "#6F778A")
        text(d, (x0+p_w-18, py1-28), "OPEN ↗", M11, VIOLET_2, anchor="ra")

    # Bottom region: activity + languages + Boot.dev.
    by0, by1 = 812, 1064
    left_box_w = 625
    rr(d, (left, by0, left+left_box_w, by1), radius=20, fill=PANEL, outline=BORDER)
    text(d, (left+22, by0+22), "ACTIVITY / 26 WEEKS", M11, MUTED)
    contrib = data.get("contrib") or []
    gx, gy = left+23, by0+60
    cell, cg = 13, 6
    if contrib:
        weeks = contrib[-26:]
        for wi, week in enumerate(weeks):
            for di in range(7):
                count = week[di] if di < len(week) else 0
                if count <= 0:
                    c = "#171B25"
                elif count <= 2:
                    c = "#33245B"
                elif count <= 5:
                    c = "#6547A9"
                else:
                    c = VIOLET_2
                x = gx + wi*(cell+cg)
                y = gy + di*(cell+cg)
                d.rounded_rectangle((x,y,x+cell,y+cell), radius=3, fill=c)
    else:
        text(d, (gx, gy+18), "Contribution calendar unavailable on this render.", F13, MUTED)

    text(d, (left+22, by0+205), "LANGUAGE SIGNAL", M11, MUTED)
    langs = sorted((data.get("languages") or {}).items(), key=lambda kv: kv[1], reverse=True)[:4]
    total = sum(v for _,v in langs) or 1
    lx, ly = left+166, by0+204
    bar_w = 420
    cursor = lx
    palette = [VIOLET_2, CYAN, "#C4B5FD", "#455066"]
    for idx,(name,val) in enumerate(langs):
        seg = max(6, int(bar_w * val / total))
        d.rounded_rectangle((cursor, ly, cursor+seg, ly+10), radius=5, fill=palette[idx % len(palette)])
        cursor += seg + 3
    legend_x = left+22
    legend_y = by0+229
    for idx,(name,val) in enumerate(langs):
        pct = int(round(val*100/total))
        text(d, (legend_x, legend_y), f"{name} {pct}%", M11, palette[idx % len(palette)])
        legend_x += 132

    # Boot.dev panel.
    boot_x0 = left+left_box_w+14
    boot_x1 = right
    rr(d, (boot_x0, by0, boot_x1, by1), radius=20, fill=PANEL_2, outline=BORDER)
    text(d, (boot_x0+22, by0+22), "BOOT.DEV / LEARNING FEED", M11, MUTED)
    boot = fetch_image(BOOTDEV_URL, (boot_x1-boot_x0-44, 156)) if not demo else None
    if boot:
        boot = ImageOps.fit(boot, (boot_x1-boot_x0-44, 156), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", boot.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,*boot.size), radius=14, fill=255)
        canvas.paste(boot, (boot_x0+22, by0+53), mask)
        d = ImageDraw.Draw(canvas)
    else:
        rr(d, (boot_x0+22, by0+53, boot_x1-22, by0+209), radius=14, fill="#0B0E16", outline="#262C3C")
        text(d, ((boot_x0+boot_x1)//2, by0+118), "BOOT.DEV", F24, TEXT, anchor="mm")
        text(d, ((boot_x0+boot_x1)//2, by0+149), "public thumbnail loads on Actions", M11, MUTED, anchor="mm")
    text(d, (boot_x0+22, by1-27), "backend fundamentals / systems thinking", M11, VIOLET_2)

    # Taskbar.
    task_y0, task_y1 = 1083, 1119
    d.rounded_rectangle((590, task_y0, 1010, task_y1), radius=14, fill="#11141D", outline="#2B3040")
    labels = ["GH", "DEV", "BOT", "UI", ">_"]
    xs = [654, 726, 798, 870, 942]
    for x, lab in zip(xs, labels):
        rr(d, (x-18, task_y0+5, x+18, task_y1-5), radius=8, fill="#171B26", outline="#282E40")
        text(d, (x, (task_y0+task_y1)//2), lab, M11, VIOLET_2 if lab in ("GH", ">_") else "#B5BBC8", anchor="mm")
    # Footer metadata.
    updated = data.get("updated") or dt.datetime.now(dt.timezone.utc)
    stamp = updated.strftime("%Y-%m-%d %H:%M UTC")
    text(d, (right, H-65), f"signal refreshed {stamp}", M11, "#626A7D", anchor="ra")
    if demo or data.get("network_error"):
        text(d, (left, H-65), "PREVIEW MODE — workflow replaces sample data with live public data", M11, "#856FD2")
    else:
        text(d, (left, H-65), f"{ORG}  /  {USER}", M11, "#626A7D")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT, quality=94, optimize=True)
    print(f"rendered {OUT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="render deterministic preview without network")
    args = ap.parse_args()
    data = github_data(demo=args.demo)
    render(data, demo=args.demo)


if __name__ == "__main__":
    main()
