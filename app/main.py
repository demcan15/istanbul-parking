from fastapi import FastAPI, HTTPException, Depends
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
from dotenv import load_dotenv
import time

# .env dosyasını uygulama ayağa kalkarken yükle
load_dotenv()

# ── Custom Metrikler (Prometheus) ──────────────────────────
prediction_counter = Counter(
    "parking_predictions_total",
    "Toplam tahmin sayısı",
    ["district", "prediction"]
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

# Yapay Zeka Modelini ve Label Encoder'ı Yükle
try:
    model = joblib.load("ml/models/availability_model.pkl")
    label_encoder = joblib.load("ml/models/label_encoder.pkl")
    print("✅ Yapay Zeka modeli başarıyla yüklendi.")
    model_accuracy_gauge.set(0.875) 
except Exception as e:
    model = None
    label_encoder = None
    print("⚠️ Model dosyaları yüklenemedi. Tahmin servisi mock veriye veya pasife düşebilir.")

def get_db():
    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        raise ValueError("❌ Bulut veritabanı şifresi (DB_PASSWORD) ortam değişkenlerinde bulunamadı!")
        
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "parking_db"),
        user=os.getenv("DB_USER", "parking_user"),
        password=db_password,
        host=os.getenv("DB_HOST", "34.79.169.165"),
        port="5432",
        connect_timeout=10
    )

# Redis Önbellek Bağlantısı
try:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=6379,
        decode_responses=True,
        socket_timeout=5
    )
    # Bağlantıyı test et
    r.ping()
    print("🚀 Redis önbellek sunucusuna başarıyla bağlanıldı.")
except Exception as e:
    r = None
    print("ℹ️ Redis aktif değil. API doğrudan canlı veritabanı sorgularıyla devam edecek.")

# --- ENDPOINT: Tahmin (ML Inference) Rotası ---
@app.get("/api/predict/{spot_id}")
def predict_availability(spot_id: int, is_raining: bool = False, has_event: bool = False):
    """Bir otopark spotunun şu an boş olma ihtimalini tahmin eder."""
    start_time = time.time()
        
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
        raise HTTPException(status_code=500, detail=f"Veritabanı bağlantı hatası: {str(e)}")

    if not row:
        raise HTTPException(status_code=404, detail="Otopark spotu bulunamadı.")

    district, current_status = row
    now = datetime.now()

    # Model yüklü değilse akıllı kural bazlı yedek (fallback) tahmini devrreye al
    if not model or not label_encoder:
        prob = 0.65 if now.hour < 8 or now.hour > 20 else 0.35
        if is_raining: prob -= 0.15
        prob = max(0.1, min(0.9, prob))
    else:
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
            0.75  # Varsayılan doluluk oranı katmanı
        ]])
        prob = model.predict_proba(features)[0][1]

    prediction = "boş" if prob > 0.5 else "dolu"
    elapsed = time.time() - start_time
    
    # Prometheus Metriklerini Kaydet
    prediction_latency.observe(elapsed)
    prediction_counter.labels(district=district, prediction=prediction).inc()

    return {
        "spot_id": spot_id,
        "district": district,
        "availability_probability": round(float(prob), 3),
        "prediction": prediction,
        "confidence": "yüksek" if abs(prob - 0.5) > 0.2 else "düşük",
        "current_reported_status": current_status,
        "inference_ms": round(elapsed * 1000, 2)
    }

# --- ENDPOINT: Coğrafi Yakınlık (PostGIS) Sorgusu ---
@app.get("/api/spots")
def get_nearby_spots(lat: float, lng: float, radius: int = 1000):
    """Verilen koordinatın etrafındaki (radius metre) otoparkları PostGIS ile çeker."""
    cache_key = f"spots:{lat:.3f}:{lng:.3f}:{radius}"
    
    if r:
        try:
            cached = r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass # Redis cache miss durumunda DB'ye düşmesi için hatayı yutuyoruz
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Gerçek PostGIS veritabanı şemasına göre optimize edilmiş dinamik SQL sorgusu
        cur.execute("""
            SELECT id, osm_id, name, lat, lng, capacity, fee, parking_type, district, street, is_available,
                   ST_Distance(location, ST_MakePoint(%s, %s)::geography) as distance_meters
            FROM parking_spots
            WHERE ST_DWithin(
                location,
                ST_MakePoint(%s, %s)::geography,
                %s
            )
            ORDER BY location <-> ST_MakePoint(%s, %s)::geography
            LIMIT 100;
        """, (lng, lat, lng, lat, radius, lng, lat))
        
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        spots = [dict(zip(columns, row)) for row in rows]
        
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PostGIS veritabanı sorgulama hatası: {str(e)}")
    
    # Dashboard toplam aktif otopark metriğini güncelle
    active_spots_gauge.set(len(spots))
    
    if r and spots:
        try:
            r.setex(cache_key, 60, json.dumps(spots)) # 60 saniye boyunca önbellekte tut
        except Exception:
            pass
            
    return spots

# --- ENDPOINT: Kullanıcı Raporları Bildirimi ---
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
        
        # İlçe bilgisini doğrula
        cur.execute("SELECT district FROM parking_spots WHERE id = %s", (report.spot_id,))
        dist_row = cur.fetchone()
        district = dist_row[0] if dist_row else "Beşiktaş"

        # Raporu arşive kaydet
        cur.execute("""
            INSERT INTO user_reports (spot_id, user_id, is_available, lat, lng)
            VALUES (%s, %s, %s, %s, %s);
        """, (report.spot_id, report.user_id, report.is_available, report.lat, report.lng))
        
        # Otopark canlı durumunu anlık olarak güncelle
        cur.execute("""
            UPDATE parking_spots
            SET is_available = %s
            WHERE id = %s;
        """, (report.is_available, report.spot_id))
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rapor işlenirken hata oluştu: {str(e)}")

    # Rapor Prometheus Metriğini Artır
    report_counter.labels(district=district, is_available=str(report.is_available)).inc()

    return {"status": "ok", "message": "Canlı durum raporu başarıyla kaydedildi."}

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/api/spots/seed")
def seed_spots():
    """Geliştirme ve test süreçleri için örnek Beşiktaş otoparkları enjekte eder."""
    spots = [
        (41.0422, 29.0083, "Beşiktaş", "Barbaros Blv."),
        (41.0430, 29.0070, "Beşiktaş", "Çırağan Cd."),
        (41.0410, 29.0095, "Beşiktaş", "Şair Nedim Cd."),
        (41.0445, 29.0060, "Beşiktaş", "Ihlamurdere Cd."),
        (41.0398, 29.0110, "Beşiktaş", "Dolmabahçe Cd."),
    ]
    try:
        conn = get_db()
        cur = conn.cursor()
        for lat, lng, district, street in spots:
            cur.execute("""
                INSERT INTO parking_spots (lat, lng, location, district, street, is_available, capacity, fee, parking_type)
                VALUES (%s, %s, ST_MakePoint(%s, %s)::geography, %s, %s, TRUE, 120, 'yes', 'surface')
                ON CONFLICT DO NOTHING;
            """, (lat, lng, lng, lat, district, street))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seeding hatası: {str(e)}")
        
    return {"status": "success", "added": len(spots)}