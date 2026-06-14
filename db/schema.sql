CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE parking_spots (
    id SERIAL PRIMARY KEY,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    location GEOGRAPHY(POINT, 4326),
    district VARCHAR(100),
    street VARCHAR(200),
    is_available BOOLEAN DEFAULT TRUE,
    availability_score FLOAT DEFAULT 0.5,
    last_reported_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE user_reports (
    id SERIAL PRIMARY KEY,
    spot_id INTEGER REFERENCES parking_spots(id),
    user_id VARCHAR(100),
    is_available BOOLEAN NOT NULL,
    credibility_score FLOAT DEFAULT 0.5,
    reported_at TIMESTAMP DEFAULT NOW(),
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION
);

-- Konum bazlı hızlı sorgu için index
CREATE INDEX idx_spots_location ON parking_spots USING GIST(location);