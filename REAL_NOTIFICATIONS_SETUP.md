# NeuralNotify — Real Notification Setup Guide

## How It Works Now

```
Your Phone (Android/iOS)
  │
  │  POST /push   (every real notification)
  ▼
FastAPI Backend  ──► ML Pipeline ──► WebSocket ──► Browser UI (live)
  (localhost:8000)                   (/ws)          (real-time feed tab)
```

## Step 1: Start the Backend

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` makes it reachable from your phone on the same Wi-Fi.

Find your PC's local IP:
- Windows: `ipconfig` → look for IPv4 Address
- Mac/Linux: `ifconfig` or `ip addr` → look for 192.168.x.x

## Step 2: Android Setup (Tasker)

1. Install **Tasker** from Play Store (paid, ~$3)
2. Settings → Notification Access → enable Tasker
3. Import `tasker_profile.xml` from this project:
   - Long-press "Profiles" tab → Import → select the file
4. Edit the HTTP action:
   - Change URL to `http://<YOUR_PC_IP>:8000/push`
5. Enable the profile ✅

Every WhatsApp/Gmail/SMS/Slack notification now flows into NeuralNotify automatically.

## Step 3: iOS Setup (Shortcuts)

1. Open **Shortcuts** app → Automation tab → + New Automation
2. Trigger: App → select apps you want → "Notification Received"  
3. Add action: **Get Contents of URL**
   - Method: POST
   - URL: `http://<YOUR_PC_IP>:8000/push`
   - Request Body: JSON
   - Body: `{"app": "Shortcut Input", "sender": "Shortcut Title", "message": "Shortcut Body"}`
4. Disable "Ask Before Running"
5. Done ✅

## Step 4: Open the Dashboard

Open http://localhost:8000 in your browser, go to the **📡 Live Feed** tab.
The WebSocket connects automatically and shows every notification the moment it arrives.

## New API Endpoints Added

| Method | Path | Description |
|--------|------|-------------|
| `WS` | `/ws` | WebSocket — browser subscribes for real-time pushes |
| `POST` | `/push` | Device bridge — Tasker/Shortcuts POST here |
| `GET` | `/ws/status` | How many browser tabs are connected |

All original endpoints (/notify, /bundle, /feedback, etc.) are unchanged.

## /push Payload Format

```json
{
  "app":     "whatsapp",
  "package": "com.whatsapp",
  "sender":  "Mom",
  "message": "Call me when free",
  "title":   "Mom",
  "context": {
    "hour": 14,
    "location": "home",
    "activity": "idle"
  }
}
```

All fields except `message` are optional. Package name is auto-mapped to app name.
