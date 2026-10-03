#!/usr/bin/env python3
"""
detector_server.py - Local automation-driver leak detector (stdlib only).

Serves one page at http://127.0.0.1:8765/ that runs a battery of
client-side checks for the signals vanilla Playwright/Puppeteer drivers
leave behind, and reports them as JSON. Based on well-documented,
public detection techniques (see article for sources):

  1. navigator.webdriver                - WebDriver / automation flag
  2. CDP Runtime.enable probe           - Error-object getter fired by
                                          console.debug() serialization
                                          (Vastel/DataDome 2024, simplified
                                          from Brotector)
  3. window.chrome / chrome.runtime     - missing in old headless shell
  4. navigator.plugins / mimeTypes      - zero-length in old headless shell
  5. Permissions vs Notification state  - classic headless mismatch
  6. WebGL vendor/renderer              - SwiftShader software GL in headless
  7. User agent                         - "HeadlessChrome" token
  8. navigator.languages                - empty in some automation setups

Usage:
    python3 detector_server.py [port]
"""
import http.server
import sys

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<title>driver leak detector</title>
<style>
 body { font-family: monospace; background: #10161f; color: #d5dce6; margin: 2rem; }
 h1 { font-size: 1.1rem; }
 table { border-collapse: collapse; font-size: 0.85rem; }
 td, th { border: 1px solid #2c3a4d; padding: 4px 10px; text-align: left; }
 .pass { color: #4ade80; } .fail { color: #f87171; } .warn { color: #fbbf24; }
 #results { display: none; }
</style></head>
<body>
<h1>Automation driver leak detector</h1>
<table id="tbl"><tr><th>check</th><th>value</th><th>verdict</th></tr></table>
<pre id="results">pending</pre>
<script>
function row(tbl, name, value, verdict, cls) {
  const tr = document.createElement("tr");
  for (const txt of [name, String(value), verdict]) {
    const td = document.createElement("td");
    td.textContent = txt;
    if (txt === verdict) td.className = cls;
    tr.appendChild(td);
  }
  tbl.appendChild(tr);
}
async function run() {
  const tbl = document.getElementById("tbl");
  const r = {};
  const leaks = [];

  const webdriver = navigator.webdriver;
  r["navigator.webdriver"] = webdriver;
  row(tbl, "navigator.webdriver", webdriver,
      webdriver ? "FAIL" : "pass", webdriver ? "fail" : "pass");
  if (webdriver) leaks.push("navigator.webdriver");

  let prepFired = false;
  let stackLookups = 0;
  const origPrep = Error.prepareStackTrace;
  Error.prepareStackTrace = function (e, frames) { prepFired = true; return ""; };
  const err = new Error();
  Object.defineProperty(err, "stack", {
    configurable: true,
    get: function () { stackLookups += 1; return ""; }
  });
  let nameLookups = 0;
  const nameDesc = Object.getOwnPropertyDescriptor(Error.prototype, "name");
  Object.defineProperty(Error.prototype, "name", {
    configurable: true,
    get: function () { nameLookups += 1; return "Error"; }
  });
  let c = console;
  try { c = console.context("probe: ") || console; } catch (e) {}
  c.debug(err);
  const prepFirst = prepFired;
  nameLookups = 0;
  c.debug(new Error(""));
  Object.defineProperty(Error.prototype, "name", nameDesc);
  Error.prepareStackTrace = origPrep;
  await new Promise(res => setTimeout(res, 120));
  r["cdp_runtime_probe.prepareStackTrace"] = prepFirst;
  r["cdp_runtime_probe.name_getter_hits"] = nameLookups;
  const cdpLeak = prepFirst || nameLookups >= 2;
  row(tbl, "CDP runtime probe (stack formatting fired)", prepFirst,
      cdpLeak ? "FAIL" : "pass", cdpLeak ? "fail" : "pass");
  if (cdpLeak) leaks.push("cdp_runtime_probe");

  const hasChromeObj = typeof window.chrome === "object" && window.chrome !== null;
  const hasRuntime = hasChromeObj && typeof window.chrome.runtime === "object";
  r["window.chrome"] = hasChromeObj;
  r["chrome.runtime"] = hasRuntime;
  row(tbl, "window.chrome / chrome.runtime",
      hasChromeObj + " / " + hasRuntime,
      hasChromeObj ? "pass" : "FAIL", hasChromeObj ? "pass" : "fail");
  if (!hasChromeObj) leaks.push("window.chrome missing");

  const nPlugins = navigator.plugins ? navigator.plugins.length : -1;
  const nMime = navigator.mimeTypes ? navigator.mimeTypes.length : -1;
  r["navigator.plugins.length"] = nPlugins;
  r["navigator.mimeTypes.length"] = nMime;
  const pluginsOk = nPlugins > 0;
  row(tbl, "navigator.plugins / mimeTypes", nPlugins + " / " + nMime,
      pluginsOk ? "pass" : "FAIL", pluginsOk ? "pass" : "fail");
  if (!pluginsOk) leaks.push("navigator.plugins empty");

  let permState = "n/a", notifPerm = "n/a";
  try {
    permState = (await navigator.permissions.query({name: "notifications"})).state;
    notifPerm = Notification.permission;
  } catch (e) {}
  r["permissions.notifications"] = permState;
  r["Notification.permission"] = notifPerm;
  const permMismatch = permState === "prompt" && notifPerm === "denied";
  row(tbl, "permissions vs Notification", permState + " / " + notifPerm,
      permMismatch ? "FAIL" : "pass", permMismatch ? "fail" : "pass");
  if (permMismatch) leaks.push("permission mismatch");

  let glVendor = "n/a", glRenderer = "n/a";
  try {
    const c = document.createElement("canvas").getContext("webgl");
    const ext = c.getExtension("WEBGL_debug_renderer_info");
    glVendor = c.getParameter(ext.UNMASKED_VENDOR_WEBGL);
    glRenderer = c.getParameter(ext.UNMASKED_RENDERER_WEBGL);
  } catch (e) {}
  r["webgl.vendor"] = glVendor;
  r["webgl.renderer"] = glRenderer;
  const swGl = /SwiftShader|llvmpipe|Software/i.test(glRenderer);
  row(tbl, "WebGL renderer", glRenderer,
      swGl ? "FAIL" : "pass", swGl ? "fail" : "pass");
  if (swGl) leaks.push("software WebGL");

  const ua = navigator.userAgent;
  r["userAgent"] = ua;
  const headlessUa = /Headless/i.test(ua);
  row(tbl, "user agent", ua, headlessUa ? "FAIL" : "pass",
      headlessUa ? "fail" : "pass");
  if (headlessUa) leaks.push("HeadlessChrome UA");

  const langs = navigator.languages ? navigator.languages.join(",") : "";
  r["navigator.languages"] = langs;
  const langsOk = langs.length > 0;
  row(tbl, "navigator.languages", langs || "(empty)",
      langsOk ? "pass" : "FAIL", langsOk ? "pass" : "fail");
  if (!langsOk) leaks.push("languages empty");

  r["_verdict"] = leaks.length === 0 ? "looks human-grade" : "AUTOMATION LEAKS";
  r["_leaks"] = leaks;
  row(tbl, "verdict", leaks.length ? leaks.join("; ") : "no leaks detected",
      leaks.length ? "FAIL" : "pass", leaks.length ? "fail" : "pass");

  document.getElementById("results").textContent = JSON.stringify(r);
}
run();
</script>
</body></html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"[detector] serving on http://127.0.0.1:{port}/ (ctrl-c to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
