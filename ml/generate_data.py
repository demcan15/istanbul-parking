import pandas as pd
import numpy as np
import os

np.random.seed(42)
N = 50_000

districts = {
    "Beşiktaş":  {"base_occupancy": 0.85, "event_sensitive": True},
    "Kadıköy":   {"base_occupancy": 0.80, "event_sensitive": False},
    "Şişli":     {"base_occupancy": 0.75, "event_sensitive": False},
    "Üsküdar":   {"base_occupancy": 0.65, "event_sensitive": False},
    "Bakırköy":  {"base_occupancy": 0.70, "event_sensitive": False},
}

rows = []
for _ in range(N):
    district_name = np.random.choice(list(districts.keys()))
    d = districts[district_name]
    hour = np.random.randint(0, 24)
    day_of_week = np.random.randint(0, 7)
    is_weekend = int(day_of_week >= 5)
    is_raining = int(np.random.random() < 0.20)
    has_event = int(d["event_sensitive"] and np.random.random() < 0.15)
    
    base = d["base_occupancy"]
    if 8 <= hour <= 10: base += 0.10
    elif 12 <= hour <= 14: base += 0.05
    elif 17 <= hour <= 20: base += 0.15
    elif 0 <= hour <= 6: base -= 0.35
    
    if is_weekend: base += 0.10
    if is_raining: base += 0.08
    if has_event: base += 0.20
    
    base += np.random.normal(0, 0.05)
    base = np.clip(base, 0, 1)
    
    is_available = int(np.random.random() > base)
    rows.append({
        "hour": hour,
        "day_of_week": day_of_week,
        "is_weekend": is_weekend,
        "is_raining": is_raining,
        "has_event": has_event,
        "district": district_name,
        "base_occupancy": round(d["base_occupancy"], 2),
        "is_available": is_available,
    })

df = pd.DataFrame(rows)
os.makedirs("ml/data", exist_ok=True)
df.to_csv("ml/data/parking_data.csv", index=False)
print(f"✅ {len(df)} satır veri üretildi.")
print(df["is_available"].value_counts())
