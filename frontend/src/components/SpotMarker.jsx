import { Marker, Popup } from "react-leaflet";
import L from "leaflet";
import ReportModal from "./ReportModal";

// Boş = yeşil, Dolu = kırmızı, Belirsiz = turuncu
function getIcon(spot) {
  const color = spot.is_available
    ? "#22c55e"
    : spot.availability_score > 0.4
    ? "#f97316"
    : "#ef4444";

  return L.divIcon({
    className: "",
    html: `
      <div style="
        width: 16px; height: 16px;
        background: ${color};
        border: 2px solid white;
        border-radius: 50%;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
      "></div>
    `,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

export default function SpotMarker({ spot, onReport }) {
  return (
    <Marker position={[spot.lat, spot.lng]} icon={getIcon(spot)}>
      <Popup>
        <div style={{ minWidth: 180 }}>
          <strong>{spot.district || "Park Yeri"}</strong>
          <p style={{ margin: "6px 0", fontSize: 13 }}>
            Durum:{" "}
            <span style={{ color: spot.is_available ? "green" : "red" }}>
              {spot.is_available ? "✅ Boş" : "🔴 Dolu"}
            </span>
          </p>
          <p style={{ margin: "0 0 8px", fontSize: 12, color: "#666" }}>
            Tahmin skoru: {(spot.score * 100).toFixed(0)}%
          </p>
          <ReportModal spot={spot} onSuccess={onReport} />
        </div>
      </Popup>
    </Marker>
  );
}