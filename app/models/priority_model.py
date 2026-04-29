import os
import warnings
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import GradientBoostingClassifier

# Absolute path — works regardless of working directory
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models_saved", "priority_model.pkl"
)

# Store the sklearn version this model was built with alongside the pkl
VERSION_PATH = MODEL_PATH + ".version"

FEATURE_NAMES = [
    "hour", "day_of_week", "is_weekend",
    "location", "activity", "app_type",
    "urgency_score", "message_length",
    "has_question", "has_exclaim",
    "is_night", "is_work_hours"
]

def train_model():
    X = np.array([
        # hour  dow  wknd  loc  act  app  urg  len   q  !  ngt  wrk
        # --- SEND NOW (label=1) ---
        [10,    1,   0,    1,   2,   1,   3,   120,  0, 1,  0,   1],
        [14,    2,   0,    1,   2,   2,   2,   80,   1, 0,  0,   1],
        [9,     0,   0,    2,   1,   6,   2,   60,   0, 1,  0,   1],
        [18,    3,   0,    0,   2,   0,   3,   150,  0, 1,  0,   0],
        [11,    1,   0,    1,   2,   1,   2,   200,  1, 0,  0,   1],
        [15,    4,   0,    1,   2,   2,   3,   90,   0, 1,  0,   1],
        [8,     2,   0,    3,   5,   7,   1,   40,   0, 1,  0,   1],
        [16,    0,   0,    1,   2,   0,   2,   100,  1, 1,  0,   1],
        [10,    3,   0,    2,   1,   1,   3,   180,  0, 1,  0,   1],
        [13,    1,   0,    1,   2,   6,   2,   50,   1, 0,  0,   1],
        [9,     2,   0,    1,   2,   2,   3,   110,  0, 1,  0,   1],
        [17,    4,   0,    0,   2,   1,   2,   140,  1, 0,  0,   1],
        [11,    0,   0,    1,   2,   0,   1,   70,   0, 1,  0,   1],
        [14,    3,   0,    2,   1,   6,   3,   90,   1, 1,  0,   1],
        [10,    1,   0,    1,   2,   7,   2,   30,   0, 0,  0,   1],
        [12,    2,   0,    1,   2,   1,   2,   160,  1, 0,  0,   1],
        [15,    0,   0,    0,   2,   2,   3,   120,  0, 1,  0,   1],
        [9,     4,   0,    1,   2,   0,   1,   80,   0, 0,  0,   1],
        [8,     1,   0,    3,   5,   6,   2,   55,   0, 1,  0,   1],
        [10,    2,   0,    2,   1,   2,   1,   95,   1, 0,  0,   1],
        [14,    0,   0,    5,   0,   0,   2,   110,  0, 1,  0,   1],
        # --- BATCH/DELAY (label=0) ---
        [2,     1,   0,    0,   4,   3,   0,   20,   0, 0,  1,   0],
        [23,    0,   0,    0,   4,   5,   0,   10,   0, 0,  1,   0],
        [3,     3,   0,    0,   4,   4,   0,   15,   0, 0,  1,   0],
        [1,     2,   0,    0,   4,   3,   0,   25,   0, 0,  1,   0],
        [20,    6,   1,    0,   3,   5,   0,   30,   0, 0,  0,   0],
        [22,    5,   1,    0,   3,   4,   0,   12,   0, 0,  1,   0],
        [4,     1,   0,    0,   4,   3,   0,   8,    0, 0,  1,   0],
        [19,    6,   1,    0,   3,   5,   0,   45,   0, 0,  0,   0],
        [21,    0,   0,    0,   3,   4,   0,   18,   0, 0,  0,   0],
        [0,     4,   0,    0,   4,   3,   0,   10,   0, 0,  1,   0],
        [23,    6,   1,    0,   4,   5,   0,   5,    0, 0,  1,   0],
        [20,    1,   0,    0,   3,   4,   0,   22,   0, 0,  0,   0],
        [2,     5,   1,    0,   4,   3,   0,   14,   0, 0,  1,   0],
        [19,    2,   0,    0,   3,   5,   0,   38,   0, 0,  0,   0],
        [22,    3,   0,    0,   4,   4,   0,   9,    0, 0,  1,   0],
        [1,     6,   1,    0,   4,   3,   0,   7,    0, 0,  1,   0],
        [14,    5,   1,    4,   0,   3,   0,   28,   0, 0,  0,   0],
        [16,    6,   1,    5,   3,   5,   0,   32,   0, 0,  0,   0],
        [13,    5,   1,    4,   0,   4,   0,   20,   0, 0,  0,   0],
    ])

    y = [1]*21 + [0]*19

    clf = GradientBoostingClassifier(
        n_estimators=100, max_depth=4,
        learning_rate=0.1, random_state=42
    )
    clf.fit(X, y)
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    # Save the sklearn version alongside the model
    with open(VERSION_PATH, "w") as f:
        f.write(sklearn.__version__)
    print(f"[NeuralNotify] Model trained with sklearn {sklearn.__version__} and saved.")
    return clf


def _saved_version_matches():
    """Return True only if the saved pkl was built with the current sklearn version."""
    if not os.path.exists(MODEL_PATH):
        return False
    if not os.path.exists(VERSION_PATH):
        # No version file → old pkl, assume mismatch
        return False
    with open(VERSION_PATH) as f:
        saved = f.read().strip()
    return saved == sklearn.__version__


def load_model():
    if _saved_version_matches():
        try:
            # Treat any warning as an error so we catch version issues
            with warnings.catch_warnings():
                warnings.filterwarnings("error", category=UserWarning)
                m = joblib.load(MODEL_PATH)
            # Sanity-check prediction
            m.predict_proba([[10, 1, 0, 1, 2, 1, 2, 100, 0, 1, 0, 1]])
            print(f"[NeuralNotify] Model loaded OK (sklearn {sklearn.__version__})")
            return m
        except Exception as e:
            print(f"[NeuralNotify] Model load failed ({e}), retraining...")
    else:
        if os.path.exists(MODEL_PATH):
            print(f"[NeuralNotify] sklearn version mismatch — retraining fresh model...")
            os.remove(MODEL_PATH)
            if os.path.exists(VERSION_PATH):
                os.remove(VERSION_PATH)
    return train_model()


# Train/load at import time
model = load_model()


def predict_priority(features):
    return float(model.predict_proba([features])[0][1])


def retrain():
    global model
    # Force delete and retrain
    for p in [MODEL_PATH, VERSION_PATH]:
        if os.path.exists(p):
            os.remove(p)
    model = train_model()
    return {"status": "retrained", "features": FEATURE_NAMES}
