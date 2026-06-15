import { useEffect, useState } from "react";
import { MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import SpotMarker from "./SpotMarker";
import axios from "axios";

const API = "http://localhost:8000";

// Harita hareket edince yeni spot'ları çek
function MapEventHandler({ onMoveEnd }) {
  useMapEvents({ moveend: (e) => onMoveEnd(e.target.getCenter()) });
  return null;
}

export default function Map() {
  const [spots, setSpots] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchSpots = async (center) => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/spots`, {
        params: { lat: center.lat, lng: center.lng, radius: 1000 }
      });
      setSpots(res.data);
    } catch (err) {
      console.error("Spot'lar yüklenemedi:", err);
    } finally {
      setLoading(false);
    }
  };

  // İlk yüklemede Beşiktaş merkezi
  useEffect(() => {
    fetchSpots({ lat: 41.0422, lng: 29.0083 });
  }, []);

  return (
    <div style={{ position: "relative" }}>
      {loading && (
        <div style={{
          position: "absolute", top: 10, left: "50%",
          transform: "translateX(-50%)", zIndex: 1000,
          background: "white", padding: "6px 14px",
          borderRadius: 20, boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
          fontSize: 13
        }}>
          Yükleniyor...
        </div>
      )}

      <MapContainer
        center={[41.0422, 29.0083]}
        zoom={15}
        style={{ height: "100vh", width: "100%" }}
      >
        <TileLayer
          attribution='© OpenStreetMap'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapEventHandler onMoveEnd={fetchSpots} />

        {spots.map(spot => (
          <SpotMarker key={spot.id} spot={spot} onReport={fetchSpots} />
        ))}
      </MapContainer>
    </div>
  );
}