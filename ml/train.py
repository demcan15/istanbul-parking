import pandas as pd
import numpy as np
import mlflow
import mlflow.xgboost
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    f1_score, accuracy_score,
    precision_score, recall_score,
    roc_auc_score
)
import joblib
import os

# ── Veriyi yükle ──────────────────────────────────────────
df = pd.read_csv("ml/data/parking_data.csv")

# İlçe → sayıya çevir
le = LabelEncoder()
df["district_enc"] = le.fit_transform(df["district"])

FEATURES = [
    "hour", "day_of_week", "is_weekend",
    "is_raining", "has_event",
    "district_enc", "base_occupancy"
]
TARGET = "is_available"

X = df[FEATURES]
y = df[TARGET]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# ── MLflow experiment ──────────────────────────────────────
mlflow.set_experiment("istanbul-parking-availability")

with mlflow.start_run(run_name="xgboost-v1"):

    params = {
        "n_estimators": 200,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "eval_metric": "logloss",
    }

    model = xgb.XGBClassifier(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False
    )

    # ── Metrikler ─────────────────────────────────────────
    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy":  round(accuracy_score(y_test, preds), 4),
        "f1":        round(f1_score(y_test, preds), 4),
        "precision": round(precision_score(y_test, preds), 4),
        "recall":    round(recall_score(y_test, preds), 4),
        "roc_auc":   round(roc_auc_score(y_test, probs), 4),
    }

    print("\n📊 Model Metrikleri:")
    for k, v in metrics.items():
        print(f"   {k:12s}: {v}")

    # MLflow'a kaydet
    mlflow.log_params(params)
    mlflow.log_metrics(metrics)
    mlflow.xgboost.log_model(model, "model")

    # Modeli dosyaya da kaydet
    os.makedirs("ml/models", exist_ok=True)
    joblib.dump(model, "ml/models/availability_model.pkl")
    joblib.dump(le, "ml/models/label_encoder.pkl")

    print("\n✅ Model kaydedildi: ml/models/availability_model.pkl")
    print(f"   MLflow Run ID: {mlflow.active_run().info.run_id}")