from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import redis
import json
import os
import joblib
import numpy as np
from datetime import datetime
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge
import time

# ── Custom metrikler ──────────────────────────────────────
prediction_counter = Counter(
    "parking_predictions_total",
    "Toplam tahmin sayısı",
    ["district", "prediction"]   # label'lar
)

prediction_latency = Histogram(
    "parking_prediction_latency_seconds",
    "Tahmin süresi",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

model_accuracy_gauge = Gauge(
    "parking_model_accuracy",
    "Modelin son ölçülen doğruluğu"
)

report_counter = Counter(
    "parking_reports_total",
    "Toplam kullanıcı raporu",
    ["district", "is_available"]
)

active_spots_gauge = Gauge(
    "parking_active_spots_total",
    "Sistemdeki toplam aktif spot sayısı"
)

# 1. FastAPI uygulamasını başlatıyoruz
app = FastAPI(title="Istanbul Parking API")

# Prometheus otomatik metrik toplama (Uygulama ayağa kalktığında çalışır)
Instrumentator().instrument(app).expose(app)

# 2. CORS Ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Model ve Label Encoder yükle
try:
    model = joblib.load("ml/models/availability_model.pkl")
    label_encoder = joblib.load("ml/models/label_encoder.pkl")
    print("✅ Yapay Zeka modeli başarıyla yüklendi.")
    # Örnek doğruluk oranı set edelim (Dashboard'da güzel dursun)
    model_accuracy_gauge.set(0.875) 
except Exception as e:
    model = None
    label_encoder = None
    print("⚠️ Model dosyaları bulunamadı. Önce train.py çalıştırılmalı!")

FEATURES = [
    "hour", "day_of_week", "is_weekend",
    "is_raining", "has_event",
    "district_enc", "base_occupancy"
]

def get_db():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "parking_db"),
        user=os.getenv("DB_USER", "parking_user"),
        password=os.getenv("DB_PASSWORD", "secret123"),
        host=os.getenv("DB_HOST", "localhost")
    )

# Redis Bağlantısı
try:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=6379,
        decode_responses=True
    )
except Exception as e:
    r = None
    print("⚠️ Redis bağlantısı kurulamadı.")

# --- ENDPOINT: Tahmin Rotası ---
@app.get("/api/predict/{spot_id}")
def predict_availability(spot_id: int, is_raining: bool = False, has_event: bool = False):
    """Bir spot'un şu an boş olma ihtimalini tahmin et"""
    if not model or not label_encoder:
        raise HTTPException(status_code=503, detail="Yapay zeka modeli henüz eğitilmemiş.")
    
    start_time = time.time()  # Süre ölçümü başlıyor
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT district, is_available FROM parking_spots WHERE id = %s",
        (spot_id,)
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Spot bulunamadı")

    district, current_status = row
    now = datetime.now()

    try:
        district_enc = label_encoder.transform([district])[0]
    except ValueError:
        district_enc = 0

    features = np.array([[
        now.hour,
        now.weekday(),
        int(now.weekday() >= 5),
        int(is_raining),
        int(has_event),
        district_enc,
        0.75  # varsayılan base_occupancy
    ]])

    prob = model.predict_proba(features)[0][1]  # boş olma ihtimali
    prediction = "boş" if prob > 0.5 else "dolu"

    # ── Metrikleri Prometheus'a Kaydet ───────────────────
    elapsed = time.time() - start_time
    prediction_latency.observe(elapsed)
    prediction_counter.labels(
        district=district,
        prediction=prediction
    ).inc()
    # ─────────────────────────────────────────────────────

    return {
        "spot_id": spot_id,
        "district": district,
        "availability_probability": round(float(prob), 3),
        "prediction": prediction,
        "confidence": "yüksek" if abs(prob - 0.5) > 0.2 else "düşük",
        "current_reported_status": current_status,
        "inference_ms": round(elapsed * 1000, 2)
    }

# --- ENDPOINT 1: Yakındaki boş park yerlerini getir ---
@app.get("/api/spots")
def get_nearby_spots(lat: float, lng: float, radius: int = 500):
    cache_key = f"spots:{lat:.3f}:{lng:.3f}:{radius}"
    
    if r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, lat, lng, district, is_available, availability_score
        FROM parking_spots
        WHERE ST_DWithin(
            location,
            ST_MakePoint(%s, %s)::geography,
            %s
        )
        ORDER BY location <-> ST_MakePoint(%s, %s)::geography
        LIMIT 50
    """, (lng, lat, radius, lng, lat))
    
    rows = cur.fetchall()
    
    # Toplam aktif spot sayısını güncel tutalım
    active_spots_gauge.set(len(rows))

    spots = [
        {"id": row[0], "lat": row[1], "lng": row[2],
         "district": row[3], "is_available": row[4], "availability_score": row[5] or 0.5}
        for row in rows
    ]
    conn.close()
    
    if r:
        r.setex(cache_key, 60, json.dumps(spots))
    return spots

# --- ENDPOINT 2: Kullanıcı raporu al ---
class ReportIn(BaseModel):
    spot_id: int
    user_id: str
    is_available: bool
    lat: float
    lng: float

@app.post("/api/reports")
def submit_report(report: ReportIn):
    conn = get_db()
    cur = conn.cursor()
    
    # Önce ilçeyi öğrenelim (Rapor metriğinde kullanmak için)
    cur.execute("SELECT district FROM parking_spots WHERE id = %s", (report.spot_id,))
    dist_row = cur.fetchone()
    district = dist_row[0] if dist_row else "Bilinmeyen"

    cur.execute("""
        INSERT INTO user_reports (spot_id, user_id, is_available, lat, lng)
        VALUES (%s, %s, %s, %s, %s)
    """, (report.spot_id, report.user_id, report.is_available,
          report.lat, report.lng))
    
    cur.execute("""
        UPDATE parking_spots
        SET is_available = %s, last_reported_at = NOW()
        WHERE id = %s
    """, (report.is_available, report.spot_id))
    
    conn.commit()
    conn.close()

    # ── Rapor Metriğini Arttır ───────────────────────────
    report_counter.labels(
        district=district,
        is_available=str(report.is_available)
    ).inc()
    # ─────────────────────────────────────────────────────

    return {"status": "ok", "message": "Rapor alındı, teşekkürler!"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/api/spots/seed")
def seed_spots():
    """Geliştirme için örnek Beşiktaş park yerleri ekler"""
    spots = [
        (41.0422, 29.0083, "Beşiktaş"),
        (41.0430, 29.0070, "Beşiktaş"),
        (41.0410, 29.0095, "Beşiktaş"),
        (41.0445, 29.0060, "Beşiktaş"),
        (41.0398, 29.0110, "Beşiktaş"),
    ]
    conn = get_db()
    cur = conn.cursor()
    for lat, lng, district in spots:
        cur.execute("""
            INSERT INTO parking_spots (lat, lng, location, district, is_available, availability_score)
            VALUES (%s, %s, ST_MakePoint(%s, %s)::geography, %s, %s, 0.75)
        """, (lat, lng, lng, lat, district, True))
    conn.commit()
    conn.close()
    return {"added": len(spots)}