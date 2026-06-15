"""
Günlük çalışır — son 24 saatin tahminlerini referans veriyle karşılaştırır.
Drift tespit edilirse Slack'e uyarı gönderir.
"""
import pandas as pd
import numpy as np
import os
from datetime import datetime

def load_reference_data():
    """Eğitim verisinin bir örneği — referans dağılım"""
    if not os.path.exists("ml/data/parking_data.csv"):
        # Eğer eğitim verisi yoksa boş bir dataframe üretelim çökmesin
        return pd.DataFrame({"hour": np.random.randint(0, 24, 1000), "is_available": np.random.randint(0, 2, 1000)})
    df = pd.read_csv("ml/data/parking_data.csv")
    return df.sample(n=1000, random_state=42)

def load_current_data():
    """Gerçekte: DB'den son 24 saatin tahminlerini çeker."""
    ref = load_reference_data()
    current = ref.copy()

    # Akşam saatlerinde ani doluluk artışı simüle et (drift!)
    current.loc[current["hour"].between(17, 20), "is_available"] = 0
    current["hour"] = current["hour"] + np.random.randint(-1, 2, size=len(current))
    current["hour"] = current["hour"].clip(0, 23)
    return current

def calculate_drift(ref_col, curr_col):
    """İki kolon arasındaki ortalama farkı ölçen basit drift algoritması"""
    ref_mean = ref_col.mean()
    curr_mean = curr_col.mean()
    # Oransal fark %20'den büyükse drift kabul et
    if ref_mean == 0: return 0
    diff = abs(ref_mean - curr_mean) / ref_mean
    return diff

def run_monitoring():
    print(f"\n🔍 Monitoring çalışıyor: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    reference = load_reference_data()
    current = load_current_data()

    # Kolonları tek tek kontrol et
    drifted_columns = []
    for col in ["hour", "is_available"]:
        diff_ratio = calculate_drift(reference[col], current[col])
        if diff_ratio > 0.15:  # %15'ten fazla sapma varsa
            drifted_columns.append(col)

    n_drifted = len(drifted_columns)
    n_total = 2
    drift_ratio = n_drifted / n_total

    # Raporu HTML olarak simüle et
    os.makedirs("ml/reports", exist_ok=True)
    report_path = f"ml/reports/drift_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"<h1>Istanbul Parking - Drift Raporu</h1>")
        f.write(f"<p>Tarih: {datetime.now()}</p>")
        f.write(f"<p>Drift Oranı: %{drift_ratio*100:.1f}</p>")
        f.write(f"<p>Kayma Saptanan Kolonlar: {', '.join(drifted_columns) if drifted_columns else 'Yok'}</p>")

    print(f"✅ Drift raporu kaydedildi: {report_path}")
    print(f"   Drift olan kolon: {n_drifted}/{n_total}")
    print(f"   Drift oranı: {drift_ratio:.1%}")

    if drift_ratio > 0.3:
        send_alert(drift_ratio, report_path)

    return drift_ratio

def send_alert(drift_ratio, report_path):
    """Slack webhook ile uyarı gönder"""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print(f"⚠️  UYARI: Drift oranı %{drift_ratio*100:.0f} — Slack URL tanımlı değil")
        return

    import urllib.request, json
    message = {
        "text": (
            f"🚨 *Istanbul Parking — Model Drift Uyarısı*\n"
            f"Drift oranı: *%{drift_ratio*100:.0f}*\n"
            f"Rapor: `{report_path}`\n"
            f"Aksiyon: Modeli yeniden eğitmek gerekebilir."
        )
    }
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(message).encode(),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req)
        print("✅ Slack uyarısı gönderildi")
    except Exception as e:
        print(f"⚠️ Slack gönderilemedi: {e}")

if __name__ == "__main__":
    run_monitoring()