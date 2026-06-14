import { useState } from "react";
import axios from "axios";

const API = "http://localhost:8000";

export default function ReportModal({ spot, onSuccess }) {
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  const report = async (isAvailable) => {
    setSending(true);
    try {
      await axios.post(`${API}/api/reports`, {
        spot_id: spot.id,
        user_id: "user_" + Math.random().toString(36).slice(2, 8),
        is_available: isAvailable,
        lat: spot.lat,
        lng: spot.lng,
      });
      setDone(true);
      setTimeout(() => {
        setDone(false);
        onSuccess({ lat: spot.lat, lng: spot.lng });
      }, 1500);
    } catch (err) {
      alert("Rapor gönderilemedi.");
    } finally {
      setSending(false);
    }
  };

  if (done) return <p style={{ color: "green", fontSize: 13 }}>✅ Teşekkürler!</p>;

  return (
    <div>
      <p style={{ fontSize: 12, marginBottom: 6 }}>Bu yeri güncelle:</p>
      <div style={{ display: "flex", gap: 6 }}>
        <button
          onClick={() => report(true)}
          disabled={sending}
          style={{
            flex: 1, padding: "6px 0", background: "#22c55e",
            color: "white", border: "none", borderRadius: 6,
            cursor: "pointer", fontSize: 12
          }}
        >
          🟢 Boşaldı
        </button>
        <button
          onClick={() => report(false)}
          disabled={sending}
          style={{
            flex: 1, padding: "6px 0", background: "#ef4444",
            color: "white", border: "none", borderRadius: 6,
            cursor: "pointer", fontSize: 12
          }}
        >
          🔴 Doldu
        </button>
      </div>
    </div>
  );
}