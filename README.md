📱 Context-Aware Notification Filter System

An intelligent system that filters, prioritizes, and schedules notifications based on user context using Machine Learning and Reinforcement Learning techniques.

---

🚀 Features

* 🔍 **Smart Notification Filtering**
  Detects spam and low-priority notifications automatically.

* 🧠 **Context Awareness**
  Uses user activity, time, and behavior to decide importance.

* ⚡ **Priority Prediction Model**
  Classifies notifications into high, medium, and low priority.

* 📦 **Smart Bundling**
  Groups similar notifications together.

* ⏰ **Notification Scheduling**
  Delivers notifications at optimal times.

* 🔁 **Reinforcement Learning Engine**
  Continuously improves decisions based on user feedback.

* 🌐 **Web + Android Integration**
  Includes frontend UI and Android bridge support.

---

🏗️ Project Structure

```
.
├── app/
│   ├── api/                # API routes
│   ├── context/            # Context collection & encoding
│   ├── core/               # Decision engine, scheduler, RL
│   ├── models/             # ML models
│   └── main.py             # Entry point
│
├── android-app/            # PWA / Android interface
├── frontend/               # Web UI
├── data/                   # Logs and datasets
├── models_saved/           # Trained models
├── android_bridge.py       # Android communication
├── retrain.py              # Model retraining
├── requirements.txt        # Dependencies
└── start.sh                # Run script
```

---

⚙️ Installation

1️⃣ Clone the repository

```bash
git clone https://github.com/deepikadharanikota/Context-aware-Notification-Filter-System.git
cd Context-aware-Notification-Filter-System
```

2️⃣ Create virtual environment

```bash
python -m venv venv
venv\Scripts\activate   # Windows
```

3️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

---

▶️ Run the Project

```bash
python app/main.py
```

OR

```bash
bash start.sh
```

---

🧠 How It Works

1. Collects notification data
2. Encodes context (time, app, user activity)
3. Predicts priority using ML model
4. Applies spam detection
5. Uses RL engine for adaptive learning
6. Schedules or delivers notifications

---

📊 Technologies Used

* Python 🐍
* Machine Learning (Scikit-learn / Custom Models)
* Reinforcement Learning
* FastAPI / Backend APIs
* HTML, CSS, JavaScript (Frontend)
* Android Integration (Bridge + PWA)

---

📁 Key Modules

* **Decision Engine** → Final notification decision
* **Scheduler** → Delayed delivery
* **Spam Detector** → Filters unwanted messages
* **RL Engine** → Learns from user behavior
* **Summarizer** → Compresses notifications

---

🔮 Future Enhancements

* Deep Learning models for better accuracy
* Real-time mobile app deployment
* Cloud integration (AWS / Firebase)
* Personalized user dashboards

---


📜 License

This project is for educational purposes.

---

👩‍💻 Author

Dharanikota Naga Deepika**
GitHub: https://github.com/deepikadharanikota

---

⭐ If you like this project

Give it a star ⭐ on GitHub!
