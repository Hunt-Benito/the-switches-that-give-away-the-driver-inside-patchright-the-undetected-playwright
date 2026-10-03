#!/usr/bin/env python3
"""
probe.py - Launch vanilla Playwright or Patchright against the local
detector page (and optionally bot.sannysoft.com), capture results.

Modes:
  --driver vanilla|patchright
  --mode  headless      default headless (vanilla: headless shell binary,
                        patchright: --headless=new on full chromium)
  --mode  new-headless  full chromium binary with new headless
                        (vanilla: channel="chromium")
  --target local|sannysoft|both     (default both)
  --out   DIR           artifact directory (default ./out)

Requires: detector_server.py running on 127.0.0.1:8765
"""
import argparse
import json
import os
import threading

from detector_server import Handler

LOCAL_PORT = 8765
LOCAL = f"http://127.0.0.1:{LOCAL_PORT}/"
SANNYSOFT = "https://bot.sannysoft.com/"


def start_local_detector():
    import http.server
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

NOTORIOUS_FLAGS = [
    "--enable-automation",
    "--disable-blink-features=AutomationControlled",
    "--disable-component-update",
    "--disable-extensions",
    "--disable-popup-blocking",
    "--disable-default-apps",
    "--enable-unsafe-swiftshader",
    "--headless=new",
    "--headless",
    "--no-first-run",
    "--disable-infobars",
    "--disable-sync",
    "--metrics-recording-only",
    "--use-mock-keychain",
    "--disable-features",
]


def browser_flags(p, launch_kw):
    """Dump the driver's launch flags by pointing it at a non-executable
    binary. The spawn failure makes the driver print its full launch call
    log (every Chromium switch) in the error message - a convenient way to
    compare what vanilla Playwright and Patchright pass to the browser."""
    decoy = "/tmp/not-a-browser"
    with open(decoy, "w") as f:
        f.write("#!/bin/sh\n")
    os.chmod(decoy, 0o644)
    broken = dict(launch_kw)
    broken["executable_path"] = decoy
    try:
        p.chromium.launch(**broken)
    except Exception as e:
        for line in str(e).splitlines():
            if "<launching>" in line:
                tokens = line.strip().split()
                idx = tokens.index("<launching>")
                return tokens[idx + 2:]
    return None


def summarize_flags(args):
    present, absent = [], []
    for flag in NOTORIOUS_FLAGS:
        hit = flag == "--disable-features" and any(a.startswith("--disable-features") for a in args)
        if flag in args or hit:
            present.append(flag)
        else:
            absent.append(flag)
    print(f"[*] Browser launch flags (from the driver's launch call log):")
    print(f"[*] Automation-relevant flags present:")
    for f in present:
        print(f"      {f}")
    print(f"[*] Absent (not passed by this driver):")
    for f in absent:
        print(f"      {f}")
    return {"flags_present": present, "flags_absent": absent}


def parse_sannysoft(page):
    rows = page.evaluate(
        """() => {
            const out = [];
            for (const tr of document.querySelectorAll('tr')) {
                const c = tr.querySelectorAll('td');
                if (c.length >= 2) out.push([c[0].innerText.trim(), c[1].innerText.trim()]);
            }
            return out;
        }"""
    )
    passed = failed = 0
    fails = []
    for name, result in rows:
        label = name.split("\n")[0]
        if "passed" in result or result == "ok":
            passed += 1
        elif "failed" in result:
            failed += 1
            fails.append(label)
    return passed, failed, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", choices=["vanilla", "patchright"], required=True)
    ap.add_argument("--mode", choices=["headless", "new-headless"], default="headless")
    ap.add_argument("--target", choices=["local", "sannysoft", "both"], default="both")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    if args.target in ("local", "both"):
        start_local_detector()
        print(f"[*] Local detector serving on {LOCAL}")

    if args.driver == "vanilla":
        from playwright.sync_api import sync_playwright
    else:
        from patchright.sync_api import sync_playwright

    tag = f"{args.driver}-{args.mode}"
    report = {"driver": args.driver, "mode": args.mode}

    with sync_playwright() as p:
        launch_kw = {"headless": True}
        if args.mode == "new-headless":
            launch_kw["channel"] = "chromium"
        browser = p.chromium.launch(**launch_kw)
        report["browser_version"] = browser.version
        print(f"[*] {args.driver} playwright, mode={args.mode}, "
              f"browser={browser.version}")

        args_out = browser_flags(p, launch_kw)
        if args_out:
            report["cmdline"] = summarize_flags(args_out)
        else:
            print("[!] could not read browser flags")

        page = browser.new_page()

        if args.target in ("local", "both"):
            print(f"[*] Navigating to {LOCAL}")
            page.goto(LOCAL, timeout=30000)
            page.wait_for_function(
                "document.getElementById('results') && "
                "document.getElementById('results').textContent !== 'pending'",
                timeout=15000,
            )
            raw = page.evaluate(
                "document.getElementById('results').textContent"
            )
            results = json.loads(raw)
            report["detector"] = results
            print("[*] Local detector results:")
            leaks = results["_leaks"]
            if leaks:
                for leak in leaks:
                    print(f"      LEAK: {leak}")
            else:
                print("      no leaks detected")
            shot = os.path.join(args.out, f"detector-{tag}.png")
            page.screenshot(path=shot, full_page=True)
            print(f"[*] Screenshot -> {shot}")

        if args.target in ("sannysoft", "both"):
            print(f"[*] Navigating to {SANNYSOFT}")
            page.goto(SANNYSOFT, timeout=60000)
            page.wait_for_timeout(2500)
            passed, failed, fails = parse_sannysoft(page)
            report["sannysoft"] = {"passed": passed, "failed": failed, "fails": fails}
            print(f"[*] bot.sannysoft.com: {passed} passed, {failed} failed")
            for f in fails:
                print(f"      failed: {f}")
            shot = os.path.join(args.out, f"sannysoft-{tag}.png")
            page.screenshot(path=shot, full_page=True)
            print(f"[*] Screenshot -> {shot}")

        browser.close()

    with open(os.path.join(args.out, f"report-{tag}.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"[*] Report -> {os.path.join(args.out, f'report-{tag}.json')}")


if __name__ == "__main__":
    main()
