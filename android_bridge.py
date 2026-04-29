#!/usr/bin/env python3
"""
android_bridge.py — ADB Notification Bridge for NeuralNotify
─────────────────────────────────────────────────────────────
Reads Android notifications via ADB logcat and POSTs them to
the NeuralNotify /push endpoint in real time.

Requirements:
  pip install requests
  ADB installed and phone connected via USB with USB Debugging enabled

Usage:
  python android_bridge.py --server http://192.168.1.100:8000
  python android_bridge.py --server http://localhost:8000 --device emulator-5554

How it works:
  1. Runs: adb logcat NotificationManager:I *:S
  2. Parses notification events from logcat output
  3. POSTs each notification to NeuralNotify /push
"""

import subprocess
import re
import sys
import json
import time
import argparse
import threading
import datetime

try:
    import requests
except ImportError:
    print("❌ Missing 'requests'. Install with: pip install requests")
    sys.exit(1)

# ── Package → friendly app name map ───────────────────────────────────────────
PKG_MAP = {
    "com.whatsapp":                      "whatsapp",
    "com.whatsapp.w4b":                  "whatsapp",
    "com.google.android.gm":             "gmail",
    "com.slack":                         "slack",
    "org.telegram.messenger":            "telegram",
    "com.instagram.android":             "instagram",
    "com.twitter.android":               "twitter",
    "com.discord":                       "discord",
    "com.google.android.youtube":        "youtube",
    "com.facebook.orca":                 "messenger",
    "com.facebook.katana":               "facebook",
    "com.snapchat.android":              "snapchat",
    "com.microsoft.teams":               "teams",
    "com.linkedin.android":              "linkedin",
    "com.reddit.frontpage":              "reddit",
    "com.google.android.apps.messaging": "sms",
    "com.samsung.android.messaging":     "sms",
    "com.android.mms":                   "sms",
    "com.google.android.dialer":         "phone",
    "com.samsung.android.dialer":        "phone",
}

def pkg_to_app(pkg: str) -> str:
    if pkg in PKG_MAP:
        return PKG_MAP[pkg]
    for k, v in PKG_MAP.items():
        if pkg.startswith(k):
            return v
    return pkg.split(".")[-1] if "." in pkg else pkg


class ADBBridge:
    def __init__(self, server: str, device: str | None = None, verbose: bool = False):
        self.server  = server.rstrip("/")
        self.device  = device
        self.verbose = verbose
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._stats = {"sent": 0, "errors": 0, "total": 0}

    def _adb(self, *args) -> list[str]:
        cmd = ["adb"]
        if self.device:
            cmd += ["-s", self.device]
        cmd += list(args)
        return cmd

    def check_adb(self) -> bool:
        try:
            result = subprocess.run(["adb", "version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def check_device(self) -> bool:
        try:
            result = subprocess.run(
                self._adb("devices"), capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().splitlines()
            devices = [l for l in lines[1:] if l.strip() and "device" in l]
            return len(devices) > 0
        except Exception:
            return False

    def check_server(self) -> bool:
        try:
            r = self._session.get(self.server + "/device/ip", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def post_notification(self, pkg: str, title: str, text: str):
        app  = pkg_to_app(pkg)
        hour = datetime.datetime.now().hour
        payload = {
            "app":     app,
            "package": pkg,
            "sender":  title or "Unknown",
            "message": text  or "",
            "title":   title or "",
            "context": {
                "hour":     hour,
                "location": "home",
                "activity": "idle",
            }
        }
        self._stats["total"] += 1
        try:
            r = self._session.post(
                self.server + "/push",
                data=json.dumps(payload),
                timeout=8,
            )
            if r.status_code == 200:
                self._stats["sent"] += 1
                result = r.json().get("result", [{}])[0]
                action = result.get("action", "?")
                score  = round(result.get("score", 0) * 100)
                if self.verbose:
                    print(f"  ✅ [{app}] {title!r} → {action} ({score}%)")
            else:
                self._stats["errors"] += 1
                if self.verbose:
                    print(f"  ⚠️  Server returned {r.status_code}")
        except Exception as e:
            self._stats["errors"] += 1
            if self.verbose:
                print(f"  ❌ POST failed: {e}")

    def run_logcat(self):
        """
        Stream logcat and extract notification events.
        Parses lines from NotificationManager that contain package/title/text.
        """
        # Pattern for: NotificationManager: enqueueNotificationInternal: pkg=com.whatsapp...
        pkg_re    = re.compile(r"pkg=([^\s,]+)")
        title_re  = re.compile(r"tickerText=([^\n]+?)(?:\s+title=|$)")
        text_re   = re.compile(r"text=([^\n]+?)(?:\s+\w+=|$)")

        cmd = self._adb("logcat", "-v", "brief", "NotificationManager:I", "*:S")
        print(f"\n🔌 Starting logcat stream on {self.device or 'default device'}…")
        print("   Press Ctrl+C to stop.\n")

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                # Only care about enqueue events
                if "enqueueNotification" not in line and "notify" not in line.lower():
                    continue

                pkg_m   = pkg_re.search(line)
                title_m = title_re.search(line)
                text_m  = text_re.search(line)

                if pkg_m:
                    pkg   = pkg_m.group(1)
                    title = (title_m.group(1) if title_m else "").strip()
                    text  = (text_m.group(1)  if text_m  else "").strip()

                    # Skip system packages
                    if pkg.startswith("android") or pkg.startswith("com.android.systemui"):
                        continue

                    app = pkg_to_app(pkg)
                    print(f"📱 [{app}] {title}: {text[:60]}")
                    self.post_notification(pkg, title, text)

        except KeyboardInterrupt:
            pass
        finally:
            proc.terminate()
            print(f"\n📊 Bridge stats: {self._stats['sent']} sent, "
                  f"{self._stats['errors']} errors, {self._stats['total']} total")

    def print_stats_loop(self):
        """Print a stat line every 30 seconds."""
        while True:
            time.sleep(30)
            s = self._stats
            print(f"  📊 Stats: {s['sent']} sent / {s['total']} total / {s['errors']} errors")


def main():
    parser = argparse.ArgumentParser(
        description="NeuralNotify ADB Bridge — forward Android notifications over USB"
    )
    parser.add_argument(
        "--server", default="http://localhost:8000",
        help="NeuralNotify server URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--device", default=None,
        help="ADB device serial (from `adb devices`). Leave empty for default."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print detailed per-notification results"
    )
    args = parser.parse_args()

    bridge = ADBBridge(args.server, args.device, args.verbose)

    print("=" * 60)
    print("  NeuralNotify ADB Bridge")
    print("=" * 60)
    print(f"  Server : {bridge.server}")
    print(f"  Device : {bridge.device or 'default'}")
    print()

    # Pre-flight checks
    if not bridge.check_adb():
        print("❌ ADB not found. Install Android Platform Tools:")
        print("   https://developer.android.com/studio/releases/platform-tools")
        sys.exit(1)
    print("✅ ADB found")

    if not bridge.check_device():
        print("❌ No Android device connected.")
        print("   1. Enable USB Debugging: Settings → Developer Options → USB Debugging")
        print("   2. Connect phone via USB cable")
        print("   3. Accept the 'Allow USB Debugging' prompt on your phone")
        sys.exit(1)
    print("✅ Android device connected")

    if not bridge.check_server():
        print(f"❌ NeuralNotify server not reachable at {bridge.server}")
        print("   Start it with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)
    print(f"✅ NeuralNotify server reachable at {bridge.server}")
    print()

    # Start stats thread
    t = threading.Thread(target=bridge.print_stats_loop, daemon=True)
    t.start()

    # Run logcat loop
    bridge.run_logcat()


if __name__ == "__main__":
    main()
