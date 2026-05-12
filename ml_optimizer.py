import csv
import pickle
from pathlib import Path

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

import logger

PROJECT_DIR = Path(__file__).resolve().parent
MODEL_FILE = PROJECT_DIR / "signal_model.pkl"


def load_training_data():
    if not logger.CLOSED_POSITIONS_FILE.exists():
        return []

    data = []
    with logger.CLOSED_POSITIONS_FILE.open("r", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                change_percent = float(row.get('current_price', 0)) / float(row.get('open_level', 1)) - 1
                signal = 1 if change_percent > 0 else 0  # Simple signal based on change
                profit = float(row.get('profit_loss', 0))
                target = 1 if profit > 0 else 0
                data.append([change_percent, signal, target])
            except (ValueError, ZeroDivisionError):
                continue
    return data


def train_model():
    if not SKLEARN_AVAILABLE:
        print("Scikit-learn not available. Skipping ML training.")
        return None

    data = load_training_data()
    if len(data) < 10:
        print("Not enough data to train model.")
        return None

    X = [row[:2] for row in data]
    y = [row[2] for row in data]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Model trained with accuracy: {accuracy:.2f}")

    with MODEL_FILE.open("wb") as f:
        pickle.dump(model, f)

    return model


def load_model():
    if not MODEL_FILE.exists():
        return train_model()
    try:
        with MODEL_FILE.open("rb") as f:
            return pickle.load(f)
    except:
        return train_model()


def predict_signal_quality(change_percent, signal):
    if not SKLEARN_AVAILABLE:
        return 0.5  # Neutral

    model = load_model()
    if not model:
        return 0.5

    prediction = model.predict([[change_percent, signal]])
    proba = model.predict_proba([[change_percent, signal]])[0]
    return proba[1]


if __name__ == "__main__":
    train_model()