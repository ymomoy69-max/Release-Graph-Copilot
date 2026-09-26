#!/usr/bin/env python3
"""Three-minute ReleaseGraph demo.

Drives the web app in a real browser and the Acme Shop (the other app) for the
payment-failure threat. A drawn cursor glides on a curve, settles, then clicks.
Timing follows the narration script when a beat finishes early, and waits out
long actions (workspace scan, checkout, Copilot) before moving on.

Beautiful Soup only parses HTML. This app is a React SPA, so clicks go through
Playwright.

Prerequisites (two terminals, or ./scripts/dev-all.sh):

    .venv/bin/pip install -e ".[demo]"
    .venv/bin/playwright install chromium
    .venv/bin/python -m releasegraph.seed --reset
    ./scripts/dev-all.sh

Then:

    .venv/bin/python scripts/demo_walkthrough.py

Home should already be reachable. The bot signs in first, then starts the clock
on Home so 0:00 matches the script.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
from dataclasses import dataclass

UI = "http://127.0.0.1:5173"
SHOP = "http://127.0.0.1:8082"

# Seconds from 0:00. The last beat holds until the close line.
BEAT_AT = {
    "open": 0,
    "home": 10,
    "readiness": 28,
    "graph": 50,
    "incidents": 68,
    "fixprs": 92,
    "releases": 110,
    "copilot": 132,
    "audit": 158,
    "close": 180,
}


@dataclass
class Lines:
    open: str = (
        "ReleaseGraph tells a release engineer three things before they ship: "
        "what is connected, what will break, and whether deploy is allowed. "
        "I’ll show every screen in three minutes."
    )
    home: str = (
        "This is the live snapshot. Scanner issues, open incidents, Fix PRs, "
        "breaking links, and shop payment health all come from the last scan and "
        "the running shop. Production risk is rescored on each refresh. "
        "This banner is the deploy gate: ship, or stay blocked."
    )
    readiness: str = (
        "Readiness scans a real folder — here, the demo shop. That button walks "
        "the code on disk, opens tickets, and syncs the graph. If an org config "
        "is set, the same scan runs the safety checkers: pipeline, Flyway, ETL, "
        "workflow, and Playwright. Green means go. A blocking finding means no-go."
    )
    graph: str = (
        "Each node is a service. Red links are breaks from that scan. Click "
        "payment and you see who feels it if payments fail. That blast radius "
        "is computed from the graph."
    )
    incidents: str = (
        "Incidents are the on-call board. This hits the live shop, turns payment "
        "failure on, places one order, and files this ticket from the gateway "
        "response. The timeline and Analyze files, impact, and fixes come from "
        "that run. Restore payments on the shop, then Check shop & sync tickets, "
        "and the checkout incident can close."
    )
    fixprs: str = (
        "Fix PRs are human-gated. The scanner assigns the ticket and shows the "
        "file and the fix. A person approves. Re-scan and close succeeds only "
        "when the finding is gone from disk. Copilot cannot approve this."
    )
    releases: str = (
        "Releases are the train: what is in production, what is next, and the "
        "risk score. Deploy asks you to confirm and lists the services in the "
        "blast radius. Critical scanner findings keep that button blocked."
    )
    copilot: str = (
        "Copilot answers from tools: the deploy gate, the workspace scan, and "
        "open incidents. These other playbooks do the same for payment blast "
        "radius and blocking scanner issues. Proof lists the tools that ran. "
        "It can rephrase the evidence. It does not invent files, and it cannot "
        "approve a Fix PR."
    )
    audit: str = (
        "Every scan, deploy, approval, and incident is recorded here: who did what."
    )
    close: str = (
        "Scan the workspace, see who breaks, block the deploy, file the incident, "
        "require a person to close the fix, and ask the copilot with evidence. "
        "That is ReleaseGraph."
    )


def stamp(clock_start: float) -> str:
    elapsed = max(0, int(time.monotonic() - clock_start))
    return f"{elapsed // 60}:{elapsed % 60:02d}"


def say(clock_start: float, text: str) -> None:
    print(f"\n{stamp(clock_start)} — {text}\n", flush=True)


def wait_until(clock_start: float, seconds: float, pace: float) -> None:
    target = clock_start + (seconds * pace)
    remaining = target - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


_CURSOR_BOOT = """
() => {
  if (window.__rgCursor) return;
  const style = document.createElement("style");
  style.textContent = `
    #rg-cursor, #rg-ring { pointer-events: none; }
    html, html * { cursor: none !important; }
    #rg-cursor {
      position: fixed; left: 0; top: 0; z-index: 2147483646;
      width: 28px; height: 28px; will-change: transform;
      filter: drop-shadow(0 2px 2px rgba(14,23,42,.35));
    }
    #rg-ring {
      position: fixed; z-index: 2147483644; border-radius: 14px;
      border: 2px solid rgba(38,99,235,.9);
      box-shadow: 0 0 0 7px rgba(38,99,235,.14);
      opacity: 0;
      transition: none;
    }
  `;
  document.documentElement.appendChild(style);
  const cursor = document.createElement("div");
  cursor.id = "rg-cursor";
  cursor.innerHTML = `<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
    <path d="M6 4.2 L6 21.2 L10.6 16.8 L14.2 23.4 L17.1 22 L13.5 15.4 L20.2 14.8 Z"
      fill="#0E172A" stroke="#ffffff" stroke-width="1.6" stroke-linejoin="round"/>
  </svg>`;
  document.documentElement.appendChild(cursor);
  const ring = document.createElement("div");
  ring.id = "rg-ring";
  document.documentElement.appendChild(ring);
  window.__rgCursor = (x, y, down) => {
    const scale = down ? 0.84 : 1;
    cursor.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  };
  window.__rgRing = (x, y, w, h, on) => {
    if (!on) {
      ring.style.opacity = "0";
      return;
    }
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const left = Math.max(8, x - 6);
    const top = Math.max(8, y - 6);
    const right = Math.min(vw - 8, x + w + 6);
    const bottom = Math.min(vh - 80, y + h + 6);
    ring.style.left = `${left}px`;
    ring.style.top = `${top}px`;
    ring.style.width = `${Math.max(12, right - left)}px`;
    ring.style.height = `${Math.max(12, bottom - top)}px`;
    ring.style.opacity = "1";
  };
  window.__rgGlide = (points, ms) => new Promise((resolve) => {
    const t0 = performance.now();
    const last = points.length - 1;
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      const [x, y] = points[last];
      window.__rgCursor(x, y, false);
      resolve([x, y]);
    };
    const frame = (now) => {
      if (settled) return;
      const t = Math.min(1, (now - t0) / ms);
      const i = Math.min(last, Math.round(t * last));
      const [x, y] = points[i];
      window.__rgCursor(x, y, false);
      if (t < 1) requestAnimationFrame(frame);
      else finish();
    };
    requestAnimationFrame(frame);
    setTimeout(finish, ms + 250);
  });
}
"""


class Hand:
    """Visible cursor. Playwright's real pointer is invisible, so this one is drawn."""

    def __init__(self, page) -> None:
        self.page = page
        self.x = 220.0
        self.y = 260.0

    def ensure(self) -> None:
        self.page.evaluate(_CURSOR_BOOT)
        self.page.evaluate("(p) => window.__rgCursor(p[0], p[1], false)", [self.x, self.y])

    def _curve(self, x1: float, y1: float) -> tuple[list[list[float]], int]:
        x0, y0 = self.x, self.y
        dist = math.hypot(x1 - x0, y1 - y0)
        length = max(dist, 1.0)
        bend = min(90.0, dist * 0.22) * (1 if int(x0 + y0) % 2 == 0 else -1)
        px, py = -(y1 - y0) / length, (x1 - x0) / length
        cx, cy = (x0 + x1) / 2 + px * bend, (y0 + y1) / 2 + py * bend
        steps = max(24, min(64, int(dist / 12)))
        points: list[list[float]] = []
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)
            u = 1 - e
            points.append([
                u * u * x0 + 2 * u * e * cx + e * e * x1,
                u * u * y0 + 2 * u * e * cy + e * e * y1,
            ])
        # A small settle past the target, then back, like a hand arriving.
        if dist > 40 and points:
            over_x = x1 + (x1 - x0) / length * 8
            over_y = y1 + (y1 - y0) / length * 8
            points.append([over_x, over_y])
            points.append([x1, y1])
        duration = int(min(420, max(240, dist * 0.42)))
        return points, duration

    def nudge(self, x: float, y: float) -> None:
        """A short drift, used while scrolling so the pointer keeps moving."""
        self.ensure()
        self.x, self.y = x, y
        self.page.mouse.move(x, y)
        self.page.evaluate("(p) => window.__rgCursor(p[0], p[1], false)", [x, y])

    def glide(self, x: float, y: float) -> None:
        self.ensure()
        self.page.evaluate("() => window.__rgRing(0, 0, 0, 0, false)")
        if math.hypot(x - self.x, y - self.y) < 4:
            self.x, self.y = x, y
            self.page.mouse.move(x, y)
            self.page.evaluate("(p) => window.__rgCursor(p[0], p[1], false)", [x, y])
            return
        points, duration = self._curve(x, y)
        try:
            self.page.evaluate(
                "([points, ms]) => window.__rgGlide(points, ms)",
                [points, duration],
            )
        except Exception:
            try:
                self.page.evaluate("(p) => window.__rgCursor(p[0], p[1], false)", [x, y])
            except Exception:
                pass
        self.x, self.y = x, y
        try:
            self.page.mouse.move(x, y)
        except Exception:
            pass

    def press(self) -> None:
        self.page.mouse.down()
        self.page.evaluate("(p) => window.__rgCursor(p[0], p[1], true)", [self.x, self.y])
        self.page.wait_for_timeout(70)
        self.page.mouse.up()
        self.page.evaluate("(p) => window.__rgCursor(p[0], p[1], false)", [self.x, self.y])
        self.page.wait_for_timeout(90)

    def ring(self, box: dict | None, on: bool = True) -> None:
        self.ensure()
        if not box:
            self.page.evaluate("() => window.__rgRing(0,0,0,0,false)")
            return
        self.page.evaluate(
            "(b) => window.__rgRing(b.x, b.y, b.width, b.height, b.on)",
            {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"], "on": on},
        )


def _hands() -> dict[int, Hand]:
    hands = getattr(_hands, "cache", None)
    if hands is None:
        hands = {}
        setattr(_hands, "cache", hands)
    return hands


def hand(page) -> Hand:
    found = _hands().get(id(page))
    if found is None or found.page is not page:
        found = Hand(page)
        _hands()[id(page)] = found
    found.ensure()
    return found


def _aim(box: dict) -> tuple[float, float]:
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    ox = ((int(box["x"]) % 7) - 3)
    oy = ((int(box["y"]) % 5) - 2)
    inset = 4
    x = min(max(cx + ox, box["x"] + inset), box["x"] + max(box["width"] - inset, inset))
    y = min(max(cy + oy, box["y"] + inset), box["y"] + max(box["height"] - inset, inset))
    return x, y


def _reveal(page, locator, scroll: bool = True) -> dict | None:
    """Return a box only after scrolling has stopped, so the ring is not painted mid-move."""
    box = locator.bounding_box()
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    visible = (
        box
        and 8 < box["height"] < viewport["height"] * 0.72
        and 64 <= box["y"] <= viewport["height"] - 120
        and box["y"] + box["height"] <= viewport["height"] - 40
        and 0 <= box["x"] <= viewport["width"] - 8
    )
    if scroll and not visible:
        handle = locator.element_handle()
        if handle is None:
            return None
        page.evaluate(
            """(el) => el.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" })""",
            handle,
        )
        page.evaluate(
            """() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))"""
        )
        box = locator.bounding_box()
    if not box or box["width"] < 2 or box["height"] < 2:
        return None
    return box


def _hide_ring(page) -> None:
    page.evaluate("() => { if (window.__rgRing) window.__rgRing(0, 0, 0, 0, false); }")


def spot(page, locator, timeout: float = 8000, dwell: int = 480, scroll: bool = True) -> bool:
    """Glide the cursor onto a control and hold, the way a presenter points."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        return False
    _hide_ring(page)
    box = _reveal(page, locator.first, scroll=scroll)
    if not box:
        return False
    x, y = _aim(box)
    hand(page).glide(x, y)
    fresh = locator.first.bounding_box()
    if fresh and fresh["width"] > 1:
        box = fresh
    hand(page).ring(box, True)
    page.wait_for_timeout(dwell)
    return True


def human_click(page, locator, timeout: float = 8000) -> bool:
    """Move to a control, pause on it, then press."""
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        return False
    _hide_ring(page)
    box = _reveal(page, locator.first)
    if not box:
        return False
    x, y = _aim(box)
    cursor = hand(page)
    cursor.glide(x, y)
    cursor.ring(box, True)
    page.wait_for_timeout(90)
    fresh = locator.first.bounding_box() or box
    x, y = _aim(fresh)
    if math.hypot(x - cursor.x, y - cursor.y) > 14:
        cursor.glide(x, y)
        cursor.ring(fresh, True)
    cursor.press()
    return True


def human_type(page, locator, text: str) -> None:
    human_click(page, locator)
    page.keyboard.press("Meta+A")
    page.wait_for_timeout(80)
    page.keyboard.type(text, delay=22)


def human_scroll(page, dy: int = 420) -> None:
    """Wheel in short strokes while the cursor drifts, instead of one jump."""
    cursor = hand(page)
    cursor.page.evaluate("() => window.__rgRing(0, 0, 0, 0, false)")
    ticks = 4
    for _ in range(ticks):
        page.mouse.wheel(0, dy / ticks)
        cursor.nudge(cursor.x + 6, min(cursor.y + 22, 760))
        page.wait_for_timeout(50)


def caption(page, text: str) -> None:
    """Spoken lines stay in the terminal. The page has no subtitle bar."""
    return


def click_nav(page, label: str) -> None:
    link = page.get_by_role("link", name=re.compile(rf"^{re.escape(label)}\b", re.I)).first
    human_click(page, link)
    page.wait_for_timeout(280)


def wait_button_idle(page, idle_name: str, busy_name: str, timeout: float = 120000) -> None:
    """Wait until a button leaves its in-progress label and shows the idle label again."""
    try:
        page.get_by_role("button", name=busy_name).wait_for(timeout=4000)
    except Exception:
        pass
    page.get_by_role("button", name=re.compile(idle_name, re.I)).wait_for(timeout=timeout)


def ensure_home(page, email: str, password: str) -> None:
    page.goto(UI, wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    hand(page)
    if "/login" in page.url or page.get_by_role("button", name="Sign in").count():
        human_type(page, page.locator("input[type='email']"), email)
        human_type(page, page.locator("input[type='password']"), password)
        human_click(page, page.get_by_role("button", name="Sign in"))
        page.wait_for_url(re.compile(r"/$"), timeout=20000)
        hand(page)
    page.get_by_role("heading", name="Home", exact=True).wait_for(timeout=20000)


def beat_home(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, lines.home)
    caption(page, lines.home)
    spot(page, page.locator(".ops-strip"), dwell=700)
    spot(page, page.get_by_role("heading", name=re.compile(r"Production risk", re.I)), dwell=700)
    gate = page.locator(".deploy-blocked, h3").filter(has_text=re.compile(r"Deploy blocked|Scanner findings", re.I))
    if not spot(page, gate, timeout=2500):
        spot(page, page.locator(".grid").first)


def beat_readiness(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, "[Click Readiness. Click Scan workspace & sync.]")
    say(clock_start, lines.readiness)
    click_nav(page, "Readiness")
    caption(page, lines.readiness)
    page.get_by_role("heading", name="Release readiness", exact=True).wait_for()
    button = page.get_by_role("button", name=re.compile(r"Scan workspace", re.I))
    human_click(page, button)
    wait_button_idle(page, r"Scan workspace", "Scanning…")
    spot(page, page.locator(".deploy-blocked, .ok, h3").filter(has_text=re.compile(r"Deploy blocked|issue|Analysis|GO|NO-GO", re.I)))


def beat_graph(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, "[Click Release Graph. Click payment.]")
    say(clock_start, lines.graph)
    click_nav(page, "Release Graph")
    caption(page, lines.graph)
    page.get_by_role("heading", name="Release Graph", exact=True).wait_for()
    page.locator(".react-flow__node").first.wait_for(timeout=20000)
    payment = page.locator(".react-flow__node").filter(has_text=re.compile(r"payment", re.I))
    target = payment.first if payment.count() else page.locator(".react-flow__node").first
    human_click(page, target)
    spot(page, page.get_by_role("heading", name="What can be affected"), dwell=650)


def beat_shop_threat(shop, clock_start: float) -> None:
    """Show the failure on Acme Shop itself, then leave failure mode on."""
    say(clock_start, "[Shop] Enable payment failure, then place one order.")
    shop.bring_to_front()
    shop.goto(SHOP, wait_until="domcontentloaded")
    caption(shop, "Acme Shop — turn payment failure on, then place one order. Checkout should fail.")
    human_click(shop, shop.get_by_role("button", name="Enable payment failure"))
    shop.locator("#fail-msg").wait_for(timeout=15000)
    shop.wait_for_timeout(220)
    human_click(shop, shop.get_by_role("button", name="Place order"))
    shop.locator("#order-out").filter(has_text=re.compile(r"ERROR|fail|reject|detail", re.I)).wait_for(timeout=20000)
    spot(shop, shop.locator("#order-out"), dwell=450)


def beat_shop_restore(shop, clock_start: float) -> None:
    say(clock_start, "[Shop] Restore payments.")
    shop.bring_to_front()
    caption(shop, "Acme Shop — restore payments so the checkout incident can close.")
    human_click(shop, shop.get_by_role("button", name="Restore payments"))
    shop.locator("#fail-msg").filter(has_text=re.compile(r"restored", re.I)).wait_for(timeout=15000)
    shop.wait_for_timeout(280)


def beat_incidents(page, shop, clock_start: float, lines: Lines, use_shop: bool) -> None:
    say(clock_start, "[Click Incidents. Click Run a failing checkout. When the ticket appears, click it.]")
    say(clock_start, lines.incidents)
    page.bring_to_front()
    click_nav(page, "Incidents")
    caption(page, lines.incidents)
    page.get_by_role("heading", name="Incidents", exact=True).wait_for()

    if use_shop:
        try:
            beat_shop_threat(shop, clock_start)
        except Exception as exc:
            print(f"Shop threat step failed ({exc}). Continuing with Run a failing checkout.", flush=True)
        page.bring_to_front()
        caption(page, lines.incidents)

    run = page.get_by_role("button", name="Run a failing checkout")
    human_click(page, run)
    wait_button_idle(page, r"Run a failing checkout", "Placing order…", timeout=60000)
    chips = page.locator("button.chip")
    checkout = chips.filter(has_text=re.compile(r"checkout|payment|order", re.I))
    ticket = checkout.first if checkout.count() else chips.first
    if ticket.count():
        human_click(page, ticket)
    spot(page, page.get_by_role("heading", name="Timeline (oldest first)"), dwell=420)
    analyze = page.get_by_role("button", name=re.compile(r"Analyze files", re.I))
    if analyze.count() and human_click(page, analyze, timeout=3000):
        wait_button_idle(page, r"Analyze files", "Analyzing…", timeout=60000)

    if use_shop:
        try:
            beat_shop_restore(shop, clock_start)
        except Exception as exc:
            print(f"Shop restore step failed ({exc}).", flush=True)
        page.bring_to_front()
        caption(page, lines.incidents)

    sync = page.get_by_role("button", name=re.compile(r"Check shop", re.I))
    human_click(page, sync)
    wait_button_idle(page, r"Check shop", "Syncing…", timeout=30000)


def beat_fixprs(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, "[Click Fix PRs. Point at one ticket: assignee, engine fix, Approve (human).]")
    say(clock_start, lines.fixprs)
    click_nav(page, "Fix PRs")
    caption(page, lines.fixprs)
    page.get_by_role("heading", name="Fix PRs", exact=True).wait_for()
    card = page.locator("article.issue-card").first
    if not card.count():
        print("No Fix PR tickets on the board.", flush=True)
        return
    spot(page, card.locator("select"), dwell=520)
    spot(page, card.get_by_text("Engine fix", exact=False), dwell=520)
    approve = card.get_by_role("button", name=re.compile(r"Approve \(human\)|Re-scan and close", re.I))
    spot(page, approve, dwell=560)


def beat_releases(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, "[Click Releases. Open the draft or production release. Point at Deploy to production and the gate banner.]")
    say(clock_start, lines.releases)
    click_nav(page, "Releases")
    caption(page, lines.releases)
    page.get_by_role("heading", name="Releases", exact=True).wait_for()
    prod = page.locator("tbody tr").filter(has_text=re.compile(r"production|DRAFT|READY", re.I))
    row = prod.first if prod.count() else page.locator("tbody tr").first
    link = row.get_by_role("link").first
    human_click(page, link)
    page.get_by_role("heading", name=re.compile(r"^Release ", re.I)).first.wait_for(timeout=15000)
    deploy = page.get_by_role("button", name="Deploy to production")
    blocked = page.get_by_text(re.compile(r"Deploy blocked", re.I))
    if deploy.count():
        spot(page, deploy)
    elif not spot(page, blocked, timeout=3000):
        spot(page, page.get_by_role("heading", name=re.compile(r"Release ", re.I)))
    page.wait_for_timeout(250)
    gate = page.locator(".deploy-blocked, h3").filter(has_text=re.compile(r"Deploy blocked|Scanner findings", re.I))
    spot(page, gate, timeout=3000)


def beat_copilot(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, "[Click Copilot. Click Is it safe to deploy to production right now? Click Ask.]")
    say(clock_start, lines.copilot)
    click_nav(page, "Copilot")
    page.get_by_role("heading", name="Copilot", exact=True).wait_for()
    # The same questions are listed twice. Point only at the playbook row.
    playbooks = page.locator(".chip-row").first
    for name in ("What breaks if payment-service fails?", "What scanner issues block deploy?"):
        chip = playbooks.get_by_role("button", name=name, exact=True)
        if chip.count():
            spot(page, chip, timeout=3000, dwell=320)
    ask_q = playbooks.get_by_role("button", name="Is it safe to deploy to production right now?", exact=True)
    human_click(page, ask_q)
    human_click(page, page.get_by_role("button", name="Ask", exact=True))
    try:
        page.get_by_role("button", name="Looking up evidence…").wait_for(timeout=4000)
    except Exception:
        pass
    page.get_by_role("heading", name="Answer", exact=True).wait_for(timeout=120000)
    proof = page.get_by_role("heading", name="Proof — tools that ran", exact=True)
    proof.wait_for(timeout=20000)
    page.locator("pre.snippet").last.wait_for(timeout=10000)
    page.wait_for_timeout(180)
    spot(page, proof, dwell=520)


def _row_on_screen(page):
    """A single audit row already in view, so the ring is one line and the page does not jump."""
    rows = page.locator("tbody tr")
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    count = rows.count()
    for i in range(count):
        box = rows.nth(i).bounding_box()
        if not box:
            continue
        if 90 <= box["y"] <= viewport["height"] - 140 and box["height"] < 80:
            return rows.nth(i)
    return None


def beat_audit(page, clock_start: float, lines: Lines) -> None:
    say(clock_start, "[Click Audit log. Scroll the latest rows.]")
    say(clock_start, lines.audit)
    click_nav(page, "Audit log")
    page.get_by_role("heading", name="Audit log", exact=True).wait_for()
    page.locator("table").wait_for(timeout=15000)
    spot(page, page.locator("thead"), dwell=280)
    human_scroll(page, 280)
    human_scroll(page, 180)
    page.wait_for_timeout(120)
    row = _row_on_screen(page)
    if row is not None:
        spot(page, row, dwell=420, scroll=False)


def shop_is_up(playwright_request) -> bool:
    try:
        response = playwright_request.get(f"{SHOP}/", timeout=3000)
        return response.ok
    except Exception:
        return False


def main() -> int:
    global UI, SHOP
    parser = argparse.ArgumentParser(description="Play the ReleaseGraph three-minute demo.")
    parser.add_argument("--ui", default=UI, help="ReleaseGraph URL")
    parser.add_argument("--shop", default=SHOP, help="Acme Shop URL")
    parser.add_argument("--email", default="admin@acme.demo")
    parser.add_argument("--password", default="admin123!")
    parser.add_argument("--pace", type=float, default=1.0, help="Stretch every timestamp (1.5 = slower)")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-shop", action="store_true", help="Skip the Acme Shop threat window")
    args = parser.parse_args()

    UI = args.ui.rstrip("/")
    SHOP = args.shop.rstrip("/")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed. Run:\n"
            '  .venv/bin/pip install -e ".[demo]"\n'
            "  .venv/bin/playwright install chromium",
            file=sys.stderr,
        )
        return 1

    lines = Lines()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script("window.alert = () => {}; window.confirm = () => false;")
        page = context.new_page()

        print("Signing in so Home is on screen before 0:00…", flush=True)
        ensure_home(page, args.email, args.password)
        shop = context.new_page()
        page.bring_to_front()
        use_shop = not args.no_shop and shop_is_up(context.request)
        if not args.no_shop and not use_shop:
            print(
                f"Acme Shop is not up at {SHOP}. Start it with python demo/ecommerce/run_all.py "
                "or ./scripts/dev-all.sh. The incident button will still call the shop API.",
                flush=True,
            )

        clock = time.monotonic()
        say(clock, lines.open)
        caption(page, lines.open)
        page.bring_to_front()
        spot(page, page.get_by_role("heading", name="Home", exact=True), dwell=400)

        wait_until(clock, BEAT_AT["home"], args.pace)
        beat_home(page, clock, lines)

        wait_until(clock, BEAT_AT["readiness"], args.pace)
        beat_readiness(page, clock, lines)

        wait_until(clock, BEAT_AT["graph"], args.pace)
        beat_graph(page, clock, lines)

        wait_until(clock, BEAT_AT["incidents"], args.pace)
        beat_incidents(page, shop, clock, lines, use_shop)

        wait_until(clock, BEAT_AT["fixprs"], args.pace)
        beat_fixprs(page, clock, lines)

        wait_until(clock, BEAT_AT["releases"], args.pace)
        beat_releases(page, clock, lines)

        wait_until(clock, BEAT_AT["copilot"], args.pace)
        beat_copilot(page, clock, lines)

        wait_until(clock, BEAT_AT["audit"], args.pace)
        beat_audit(page, clock, lines)

        wait_until(clock, BEAT_AT["close"], args.pace)
        say(clock, lines.close)
        caption(page, lines.close)
        page.bring_to_front()
        remain = (BEAT_AT["close"] * args.pace) - (time.monotonic() - clock)
        if remain > 0:
            page.wait_for_timeout(int(remain * 1000))
        browser.close()

    print("\nDemo finished.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        raise SystemExit(130)
