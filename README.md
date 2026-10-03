# The Switches That Give Away the Driver - Patchright PoC

Companion PoC for the Hunt-Benito article. It measures, on the same machine
and the same Chromium build, exactly which automation signals a vanilla
Playwright session leaks and which of those disappear when you swap in
[Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright), the patched
Playwright driver.

## What is in here

| File | Purpose |
|---|---|
| `detector_server.py` | Local detection page (stdlib only): 8 documented checks, including the CDP `Runtime.enable` probe popularized by Antoine Vastel's DataDome research and Brotector |
| `probe.py` | Launches vanilla Playwright or Patchright in one of two modes, dumps the driver's launch flags, runs both the local detector and bot.sannysoft.com, saves screenshots + JSON reports |
| `extras_check.py` | Two behavioral differences: closed-shadow-root selectors and console event delivery |

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install playwright==1.63.0 patchright==1.63.0
playwright install chromium && playwright install chromium-headless-shell
patchright install chromium
```

## Usage

```bash
# The four configurations from the article
python probe.py --driver vanilla   --mode headless    --out out
python probe.py --driver vanilla   --mode new-headless --out out
python probe.py --driver patchright --mode headless    --out out
python probe.py --driver patchright --mode new-headless --out out

# Closed shadow roots + console event delivery
python extras_check.py --driver vanilla
python extras_check.py --driver patchright
```

`--mode headless` is the drop-in default (vanilla and Patchright both select
the headless shell binary). `--mode new-headless` launches the full Chromium
binary (`channel="chromium"`), which is the closer approximation of the
Patchright recommended setup short of installing Google Chrome and running
headful.

## Expected results (Chromium 153.0.8010.12, our GPU-less Linux VM)

| Configuration | navigator.webdriver | CDP runtime probe | window.chrome | plugins | sannysoft |
|---|---|---|---|---|---|
| vanilla, headless shell | true | fires | missing | 0 | 15 passed / 3 failed |
| vanilla, new headless | true | fires | ok | ok | 21 passed / 1 failed |
| Patchright, headless shell | false | silent | missing | 0 | 16 passed / 2 failed |
| Patchright, new headless | false | silent | ok | ok | 22 passed / 0 failed |

The two residual Patchright leaks in the last row (software WebGL renderer,
`HeadlessChrome` UA token) are artifacts of headless mode on a VM with no
GPU, not driver leaks. The Patchright documentation's recommended production
setup is a persistent context with the real Google Chrome binary, headful,
`no_viewport=True`, and no custom headers or user agent.

## Flags the drivers pass (from the launch call log)

Vanilla Playwright 1.63.0 headless launches carry 12 automation-associated
defaults (`--enable-unsafe-swiftshader`, `--disable-component-update`,
`--disable-extensions`, `--disable-popup-blocking`,
`--disable-default-apps`, `--metrics-recording-only`, ...). Patchright
drops six of them and adds
`--disable-blink-features=AutomationControlled`, which is what makes
`navigator.webdriver` land as `false`. Run `probe.py` to dump the full lists
on your machine.

## Sources for the detection techniques

- Antoine Vastel / DataDome, "How New Headless Chrome & the CDP Signal Are
  Impacting Bot Detection": https://datadome.co/threat-research/how-new-headless-chrome-the-cdp-signal-are-impacting-bot-detection/
- Rebrowser, "How to fix Runtime.Enable CDP detection": https://rebrowser.net/blog/how-to-fix-runtime-enable-cdp-detection-of-puppeteer-playwright-and-other-automation-libraries-61740
- Brotector (test page and source): https://kaliiiiiiiiii.github.io/brotector/
- bot.sannysoft.com: https://bot.sannysoft.com/
