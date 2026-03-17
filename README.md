# api-fov

**FOV & Detection Ray API** — Computes field of view cones and detection rays as standard GeoJSON for drone imagery inspections.

## Overview

Given a drone image's GPS position, heading, and detection bounding boxes, this API computes:

- **FOV Cone**: A polygon representing the camera's field of view projected onto the ground
- **Detection Rays**: Lines from the camera to each detected object within the FOV

Output is **standard GeoJSON** (WGS84 / EPSG:4326), directly consumable by OpenLayers, QGIS, Leaflet, or any GIS tool.

## Endpoints

Base URL: `https://api-fov-{PROJECT_NUMBER}.europe-west1.run.app`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI (interactive documentation) |
| `POST` | `/compute` | Compute FOV + rays for a single image |
| `POST` | `/batch` | Compute FOV + rays for up to 50,000 images |
| `POST` | `/by-flight` | Fetch image data from DB, then compute |

---

### `POST /compute` — Single image

Compute FOV cone and detection rays for one image.

**Request:**

```json
{
  "lat": 55.8234,
  "lon": -3.4567,
  "heading": 135.5,
  "image_width": 4000,
  "detections": [
    { "id": "inf_123", "bbox_xywh": [0.3, 0.5, 0.1, 0.2] },
    { "id": "inf_456", "bbox_xywh": [2800, 2000, 400, 600] }
  ],
  "fov_degrees": 70,
  "radius_meters": 1.66
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lat` | float | **required** | Latitude (-90 to 90) |
| `lon` | float | **required** | Longitude (-180 to 180) |
| `heading` | float | **required** | GPS heading in degrees (0=North, 90=East, clockwise) |
| `image_width` | int | 4000 | Image width in pixels (for normalizing pixel bboxes) |
| `detections` | array | [] | List of detected objects with bounding boxes |
| `detections[].id` | string | null | Detection identifier |
| `detections[].bbox_xywh` | float[4] | [0.5,0.5,0.1,0.1] | Bounding box [x_center, y_center, width, height]. Can be normalized (0-1) or pixel coordinates — auto-detected |
| `fov_degrees` | float | 70 | Total field of view angle in degrees |
| `radius_meters` | float | 1.66 | Projection distance in meters |

**Response:** GeoJSON FeatureCollection

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [[[lon,lat], ...]] },
      "properties": {
        "feature_type": "fov_cone",
        "image_id": null,
        "heading": 135.5
      }
    },
    {
      "type": "Feature",
      "geometry": { "type": "LineString", "coordinates": [[lon1,lat1], [lon2,lat2]] },
      "properties": {
        "feature_type": "detection_ray",
        "image_id": null,
        "detection_id": "inf_123",
        "norm_x": 0.3
      }
    }
  ]
}
```

---

### `POST /batch` — Multiple images

Compute FOV + rays for an array of images. All results are returned in a single flat FeatureCollection.

**Request:**

```json
{
  "images": [
    {
      "image_id": "DJI_0001.JPG",
      "lat": 55.8234,
      "lon": -3.4567,
      "heading": 135.5,
      "image_width": 4000,
      "detections": [
        { "id": "inf_123", "bbox_xywh": [0.3, 0.5, 0.1, 0.2] }
      ]
    }
  ],
  "fov_degrees": 70,
  "radius_meters": 1.66
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `images` | array | **required** | Array of image objects (max 50,000) |
| `images[].image_id` | string | null | Identifier for the image |
| `images[].lat` | float | **required** | Latitude |
| `images[].lon` | float | **required** | Longitude |
| `images[].heading` | float | **required** | GPS heading |
| `images[].image_width` | int | 4000 | Image width in pixels |
| `images[].detections` | array | [] | Detections for this image |
| `fov_degrees` | float | 70 | FOV angle (shared for all images) |
| `radius_meters` | float | 1.66 | Projection distance (shared) |

**Response:** GeoJSON FeatureCollection with metadata

```json
{
  "type": "FeatureCollection",
  "features": [ ... ],
  "metadata": {
    "total_images": 1500,
    "total_features": 4200,
    "elapsed_ms": 45
  }
}
```

Each feature has `properties.image_id` linking it back to its source image.

---

### `POST /by-flight` — From database

Fetches image coordinates and inferences from the PostgreSQL API, then computes FOV + rays.

**Request:**

```json
{
  "informe_id": "rbyUchz5DeuXIs97dTct",
  "mission": "DJI_202503011230_001",
  "bucket": "sentinel-reports",
  "bucket_prefix": "rbyUchz5DeuXIs97dTct_stillhouse/flight-validated/",
  "fov_degrees": 70,
  "radius_meters": 1.66
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `informe_id` | string | **required** | Informe ID for the flight |
| `mission` | string | null | Mission/folder name (null = all missions) |
| `bucket` | string | null | GCS bucket name (needed for inference matching) |
| `bucket_prefix` | string | null | GCS bucket prefix |
| `fov_degrees` | float | 70 | FOV angle |
| `radius_meters` | float | 1.66 | Projection distance |

**Response:** Same as batch, with additional metadata:

```json
{
  "type": "FeatureCollection",
  "features": [ ... ],
  "metadata": {
    "total_images": 850,
    "total_features": 2400,
    "elapsed_ms": 120,
    "source": "database",
    "informe_id": "rbyUchz5DeuXIs97dTct",
    "mission": "DJI_202503011230_001"
  }
}
```

---

## Feature Properties

All GeoJSON features include typed properties for filtering and styling:

### FOV Cone (`Polygon`)

| Property | Type | Description |
|----------|------|-------------|
| `feature_type` | string | Always `"fov_cone"` |
| `image_id` | string | Source image identifier |
| `heading` | float | Camera heading in degrees |

### Detection Ray (`LineString`)

| Property | Type | Description |
|----------|------|-------------|
| `feature_type` | string | Always `"detection_ray"` |
| `image_id` | string | Source image identifier |
| `detection_id` | string | Detection/inference identifier |
| `norm_x` | float | Normalized X position in image (0=left, 1=right) |

---

## Geometry Model

The FOV computation uses a flat-earth approximation (valid for distances < 100m):

- **Heading conversion**: GPS heading (0=N, clockwise) → math angle (0=E, counter-clockwise): `angle = 90° - heading`
- **FOV cone**: Circular sector with `segments=16` arc points, swept from `heading - fov/2` to `heading + fov/2`
- **Detection ray**: Single line from camera center to a point at `radius` meters, at an angle interpolated from the detection's X position within the FOV
- **Coordinate offsets**: `dLat = sin(angle) × radius / 111320`, `dLon = cos(angle) × radius / (111320 × cos(lat))`

Constants:
- `FOV_DEGREES = 70` (total angle)
- `RADIUS_METERS = 1.66` (projection distance)
- `METERS_PER_DEG_LAT = 111,320`

---

## Performance

Pure trigonometry — no I/O, no image processing:

| Scale | Features | Time |
|-------|----------|------|
| 1 image, 2 detections | 3 | < 1ms |
| 100 images | 300 | ~1ms |
| 1,000 images | 3,000 | ~10ms |
| 10,000 images | 30,000 | ~330ms |
| 50,000 images | 150,000 | ~1.5s |

---

## Development

```bash
# Clone
git clone https://github.com/Solardron-Tech/api-fov.git
cd api-fov

# Run locally with Docker (hot-reload)
cp .env.example .env
docker compose up --build
# → http://localhost:8080/docs

# Run without Docker
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

## Deployment

Deployed on **Google Cloud Run** (europe-west1, 256Mi RAM).

Push to `main` triggers Cloud Build via `cloudbuild.yaml`.

## Tech Stack

- **Python 3.12** + **FastAPI**
- **Pydantic v2** for request/response validation
- **httpx** for async HTTP calls to PostgreSQL API
- **Docker** + **Cloud Run**
