#!/usr/bin/env python3
"""
extras_check.py - Two behavioral differences between vanilla Playwright
and Patchright that the detection page does not cover:

  1. Closed shadow roots: vanilla locators cannot see inside a closed
     shadow root; Patchright's patched selector engine pierces them.
  2. Console event delivery: vanilla forwards page console events to the
     client; Patchright disables the Console domain entirely (the price
     of the Console.enable leak patch), so no events arrive.

Usage:
    python3 extras_check.py --driver vanilla|patchright
"""
import argparse
import time

CLOSED_SHADOW = """data:text/html,<div id="host"></div><script>
const h = document.getElementById('host');
const r = h.attachShadow({mode: 'closed'});
r.innerHTML = '<button id="secret">hidden button</button>';
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", choices=["vanilla", "patchright"], required=True)
    args = ap.parse_args()

    if args.driver == "vanilla":
        from playwright.sync_api import sync_playwright
    else:
        from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chromium")
        pg = b.new_page()

        pg.goto(CLOSED_SHADOW)
        time.sleep(0.5)
        try:
            txt = pg.inner_text("#secret", timeout=3000)
            print(f"[*] closed shadow root : pierced (found {txt!r})")
        except Exception:
            print("[*] closed shadow root : cannot see inside (TimeoutError)")

        events = []
        pg.on("console", lambda m: events.append(m.text))
        pg.goto("data:text/html,<h1>x</h1>")
        pg.evaluate("console.log('hello-from-page')")
        pg.wait_for_timeout(800)
        if events:
            print(f"[*] console events     : received {events}")
        else:
            print("[*] console events     : none delivered (Console domain disabled)")

        b.close()


if __name__ == "__main__":
    main()
