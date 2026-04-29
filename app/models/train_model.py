import pandas as pd
import joblib
import os
from sklearn.ensemble import GradientBoostingClassifier

MODEL_PATH = "models_saved/priority_model.pkl"

EXPECTED_FEATURES = [
    "hour", "day_of_week", "is_weekend",
    "location", "activity", "app_type",
    "urgency_score", "message_length",
    "has_question", "has_exclaim",
    "is_night", "is_work_hours"
]

def train_from_csv(file_path):
    df = pd.read_csv(file_path)

    # Validate expected columns exist
    missing = [f for f in EXPECTED_FEATURES if f not in df.columns]
    if missing:
        return {"error": f"Missing columns: {missing}", "expected": EXPECTED_FEATURES}

    X = df[EXPECTED_FEATURES]
    y = df["label"]

    model = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)
    model.fit(X, y)

    os.makedirs("models_saved", exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    return {"rows": len(df), "status": "trained", "features": EXPECTED_FEATURES}
