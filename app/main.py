from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import os
import json
import time
import numpy as np
import joblib
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Istanbul Parking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Model yükle ───────────────────────────────────────────
try:
    model = joblib.load("ml/models/availability_model.pkl")
    label_encoder = joblib.load("ml/models/label_encoder.pkl")
    MODEL_AVAILABLE = True
    print("✅ Model yüklendi")
except Exception as e:
    MODEL_AVAILABLE = False
    print(f"⚠️  Model yüklenemedi: {e}")

# ── Redis — opsiyonel ─────────────────────────────────────
try:
    import redis as redis_lib
    r = redis_lib.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=6379,
        decode_responses=True,
        socket_connect_timeout=2
    )
    r.ping()
    REDIS_AVAILABLE = True
    print("✅ Redis bağlandı")
except Exception:
    r = None
    REDIS_AVAILABLE = False
    print("⚠️  Redis yok — cache devre dışı")

# ── DB bağlantısı ─────────────────────────────────────────
def get_db():
    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        raise ValueError("DB_PASSWORD bulunamadı")

    db_host = os.getenv("DB_HOST", "localhost")

    # Cloud SQL Unix socket
    if db_host.startswith("/cloudsql"):
        return psycopg2.connect(
            dbname=os.getenv("DB_NAME", "parking_db"),
            user=os.getenv("DB_USER", "parking_user"),
            password=db_password,
            host=db_host,    # örn: /cloudsql/project:region:instance
            port=5432
        )

    # Local veya IP
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "parking_db"),
        user=os.getenv("DB_USER", "parking_user"),
        password=db_password,
        host=db_host,
        port=5432,
        connect_timeout=10
    )

# ── ENDPOINT: Yakındaki spotlar ───────────────────────────
@app.get("/api/spots")
def get_nearby_spots(lat: float, lng: float, radius: int = 1000):
    cache_key = f"spots:{lat:.3f}:{lng:.3f}:{radius}"

    if REDIS_AVAILABLE and r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, osm_id, name, lat, lng, capacity,
                   fee, parking_type, district, street, is_available,
                   ST_Distance(location, ST_MakePoint(%s, %s)::geography) as distance_meters
            FROM parking_spots
            WHERE ST_DWithin(
                location,
                ST_MakePoint(%s, %s)::geography,
                %s
            )
            ORDER BY location <-> ST_MakePoint(%s, %s)::geography
            LIMIT 100
        """, (lng, lat, lng, lat, radius, lng, lat))

        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        spots = [dict(zip(columns, row)) for row in rows]
        cur.close()
        conn.close()

        if REDIS_AVAILABLE and r:
            r.setex(cache_key, 60, json.dumps(spots, default=str))

        return spots

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB Hatası: {str(e)}")

# ── ENDPOINT: Kullanıcı raporu ────────────────────────────
class ReportIn(BaseModel):
    spot_id: int
    user_id: str
    is_available: bool
    lat: float
    lng: float

@app.post("/api/reports")
def submit_report(report: ReportIn):
    try:
        conn = get_db()
        cur = conn.cursor()
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
        cur.close()
        conn.close()
        return {"status": "ok", "message": "Rapor alındı, teşekkürler!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rapor hatası: {str(e)}")

# ── ENDPOINT: ML tahmin ───────────────────────────────────
@app.get("/api/predict/{spot_id}")
def predict_availability(spot_id: int, is_raining: bool = False, has_event: bool = False):
    if not MODEL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Model henüz yüklenmedi")

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT district, is_available FROM parking_spots WHERE id = %s",
            (spot_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB Hatası: {str(e)}")

    if not row:
        raise HTTPException(status_code=404, detail="Spot bulunamadı")

    district, current_status = row
    now = datetime.now()

    try:
        district_enc = label_encoder.transform([district])[0]
    except ValueError:
        district_enc = 0

    features = np.array([[
        now.hour, now.weekday(), int(now.weekday() >= 5),
        int(is_raining), int(has_event),
        district_enc, 0.75
    ]])

    start = time.time()
    prob = model.predict_proba(features)[0][1]
    elapsed_ms = round((time.time() - start) * 1000, 2)

    return {
        "spot_id": spot_id,
        "district": district,
        "availability_probability": round(float(prob), 3),
        "prediction": "boş" if prob > 0.5 else "dolu",
        "confidence": "yüksek" if abs(prob - 0.5) > 0.2 else "düşük",
        "current_reported_status": current_status,
        "inference_ms": elapsed_ms,
    }

# ── ENDPOINT: Test verisi ekle ────────────────────────────
@app.post("/api/spots/seed")
def seed_spots():
    spots = [
        (41.0422, 29.0083, "Beşiktaş"),
        (41.0430, 29.0070, "Beşiktaş"),
        (41.0410, 29.0095, "Beşiktaş"),
        (41.0445, 29.0060, "Beşiktaş"),
        (41.0398, 29.0110, "Beşiktaş"),
    ]
    try:
        conn = get_db()
        cur = conn.cursor()
        for lat, lng, district in spots:
            cur.execute("""
                INSERT INTO parking_spots (lat, lng, location, district, is_available)
                VALUES (%s, %s, ST_MakePoint(%s, %s)::geography, %s, TRUE)
            """, (lat, lng, lng, lat, district))
        conn.commit()
        cur.close()
        conn.close()
        return {"added": len(spots)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seed hatası: {str(e)}")

# ── ENDPOINT: Health check ────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "healthy",
        "redis": REDIS_AVAILABLE,
        "model": MODEL_AVAILABLE,
    }