terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ── Variables ─────────────────────────────────────────────
variable "project_id" {
  default = "istanbul-parking-2026-ad" # <-- Gerçek Proje ID'n buraya sabitlendi
}
variable "region" {
  default = "europe-west1"   # Belçika — İstanbul'a en yakın GCP bölgesi
}
variable "db_password" {
  sensitive = true
}

# ── Artifact Registry (Docker image deposu) ───────────────
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "istanbul-parking"
  format        = "DOCKER"
}

# ── Cloud SQL (PostgreSQL + PostGIS) ──────────────────────
resource "google_sql_database_instance" "postgres" {
  name             = "parking-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = "db-f1-micro"   # En ucuz tier — demo için yeterli
    
    database_flags {
      name  = "cloudsql.enable_pgaudit"
      value = "off"
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "database" {
  name     = "parking_db"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "user" {
  name     = "parking_user"
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}

# ── Redis (Memorystore) ───────────────────────────────────
resource "google_redis_instance" "cache" {
  name           = "parking-cache"
  tier           = "BASIC"
  memory_size_gb = 1
  region         = var.region
}

# ── Cloud Run (API) ───────────────────────────────────────
resource "google_cloud_run_v2_service" "api" {
  name     = "parking-api"
  location = var.region

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/istanbul-parking/api:latest"

      env {
        name  = "DB_HOST"
        value = google_sql_database_instance.postgres.ip_address[0].ip_address
      }
      env {
        name  = "DB_NAME"
        value = "parking_db"
      }
      env {
        name  = "DB_USER"
        value = "parking_user"
      }
      env {
        name  = "REDIS_HOST"
        value = google_redis_instance.cache.host
      }
      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0   # Scale to zero — para ödemezsin boştayken
      max_instance_count = 3
    }
  }
}

# Public erişim
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Run (Frontend) ──────────────────────────────────
resource "google_cloud_run_v2_service" "frontend" {
  name     = "parking-frontend"
  location = var.region

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/istanbul-parking/frontend:latest"

      env {
        name  = "REACT_APP_API_URL"
        value = google_cloud_run_v2_service.api.uri
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Secret Manager ────────────────────────────────────────
resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password"
  replication {
    auto {}
  }
}

# ── Outputs ───────────────────────────────────────────────
output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}
output "frontend_url" {
  value = google_cloud_run_v2_service.frontend.uri
}
output "db_host" {
  value = google_sql_database_instance.postgres.ip_address[0].ip_address
}