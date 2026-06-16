from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

app = FastAPI(title="Istanbul Parking API - Cloud SQL Fix")

# CORS Ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        raise ValueError("❌ DB_PASSWORD ortam değişkenlerinde bulunamadı!")
        
    db_host = os.getenv("DB_HOST", "34.79.169.165")
    
    # EĞER CLOUD RUN ÜZERİNDEKİ UNIX SOKET YOLUNDAYSAK
    if db_host.startswith("/cloudsql"):
        # psycopg2'nin sonuna otomatik .s.PGSQL.5432 eklemesini düzeltmek için:
        # host kısmına sadece '/cloudsql' klasörünü, port kısmına ise instance adını paslıyoruz.
        # PostgreSQL Unix soket standartlarında bağlantı bu şekilde kurulur.
        instance_name = db_host.replace("/cloudsql/", "")
        return psycopg2.connect(
            dbname=os.getenv("DB_NAME", "parking_db"),
            user=os.getenv("DB_USER", "parking_user"),
            password=db_password,
            host="/cloudsql",
            port=instance_name
        )
        
    # YEREL BİLGİSAYARDAYKEN (Normal IP Bağlantısı)
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "parking_db"),
        user=os.getenv("DB_USER", "parking_user"),
        password=db_password,
        host=db_host,
        port="5432",
        connect_timeout=10
    )

# --- ENDPOINT: Coğrafi Yakınlık (PostGIS) Sorgusu ---
@app.get("/api/spots")
def get_nearby_spots(lat: float, lng: float, radius: int = 1000):
    try:
        conn = get_db()
        cur = conn.cursor()
        
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
        return spots
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PostGIS Veritabanı Hatası: {str(e)}")

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
        
        cur.execute("""
            INSERT INTO user_reports (spot_id, user_id, is_available, lat, lng)
            VALUES (%s, %s, %s, %s, %s);
        """, (report.spot_id, report.user_id, report.is_available, report.lat, report.lng))
        
        cur.execute("""
            UPDATE parking_spots
            SET is_available = %s
            WHERE id = %s;
        """, (report.is_available, report.spot_id))
        
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "message": "Canlı durum raporu başarıyla kaydedildi."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rapor işlenirken hata oluştu: {str(e)}")

@app.get("/health")
def health():
    return {"status": "healthy"}