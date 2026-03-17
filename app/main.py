"""
FOV & Detection Ray API

Computes Field of View cones and detection rays as GeoJSON
for drone imagery used in solar panel inspections.

Endpoints:
    POST /compute      — single image
    POST /batch        — array of images
    POST /by-flight    — fetch from DB, then compute
"""

import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.fov_compute import build_image_features, build_feature_collection
from app.schemas import ComputeRequest, BatchRequest, ByFlightRequest

POSTGRES_BASE = os.getenv(
    "POSTGRES_API_URL",
    "https://api-postgres-229404593483.europe-west1.run.app",
)

app = FastAPI(
    title="FOV & Detection Ray API",
    description="Computes field of view cones and detection rays as GeoJSON for drone imagery.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ─── POST /compute — single image ─────────────────────────────────

@app.post("/compute")
def compute(req: ComputeRequest):
    image = {
        "lat": req.lat,
        "lon": req.lon,
        "heading": req.heading,
        "image_width": req.image_width,
        "detections": [d.model_dump() for d in req.detections],
    }
    features = build_image_features(image, req.fov_degrees, req.radius_meters)
    return {"type": "FeatureCollection", "features": features}


# ─── POST /batch — array of images ────────────────────────────────

@app.post("/batch")
def batch(req: BatchRequest):
    images = [
        {
            "image_id": img.image_id,
            "lat": img.lat,
            "lon": img.lon,
            "heading": img.heading,
            "image_width": img.image_width,
            "detections": [d.model_dump() for d in img.detections],
        }
        for img in req.images
    ]
    return build_feature_collection(images, req.fov_degrees, req.radius_meters)


# ─── POST /by-flight — fetch from DB, then compute ────────────────

@app.post("/by-flight")
async def by_flight(req: ByFlightRequest):
    """
    Fetch images + inferences via the viewer endpoint, then compute FOV.
    Only includes images that have detections (optionally filtered by clase).
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Get missions summary to know which missions have inferences
        summary_url = f"{POSTGRES_BASE}/inferencias/viewer/inspections/{req.inspection_id}/missions-summary"
        summary_resp = await client.get(summary_url)
        if summary_resp.status_code != 200:
            raise HTTPException(502, f"missions-summary returned {summary_resp.status_code}")

        summary = summary_resp.json()
        missions = summary.get("missions", [])
        if not missions:
            return {
                "type": "FeatureCollection",
                "features": [],
                "metadata": {"total_images": 0, "total_features": 0, "elapsed_ms": 0},
            }

        # Filter missions if specified
        if req.mission:
            missions = [m for m in missions if m["mission"] == req.mission]

        # Only missions with inferences
        missions = [m for m in missions if m.get("inferencia_count", 0) > 0]

        # 2. For each mission, fetch images with their inferences via viewer endpoint
        # Also fetch image metadata (coordinates, yaw) from imagenes API
        images_for_fov: list[dict] = []

        for m in missions:
            mission_name = m["mission"]

            # Fetch ALL images + inferences with pagination
            viewer_base = (
                f"{POSTGRES_BASE}/inferencias/viewer/inspections/"
                f"{req.inspection_id}/missions/{mission_name}/imagenes-inferencias"
            )
            viewer_items: list = []
            offset = 0
            page_size = 500
            while True:
                viewer_resp = await client.get(
                    viewer_base, params={"limit": str(page_size), "offset": str(offset)}
                )
                if viewer_resp.status_code != 200:
                    break
                page_data = viewer_resp.json()
                page_items = page_data.get("items", [])
                viewer_items.extend(page_items)
                if len(page_items) < page_size:
                    break
                offset += page_size

            # Fetch image coordinates for this mission
            img_params: dict[str, str] = {
                "inspection_id": req.inspection_id,
                "mission": mission_name,
                "limit": "10000",
            }
            img_resp = await client.get(f"{POSTGRES_BASE}/imagenes/", params=img_params)
            if img_resp.status_code != 200:
                continue

            img_data = img_resp.json()
            # Build lookup: image_id → {lat, lon, heading, width}
            coords_by_id: dict[int, dict] = {}
            for item in img_data.get("items", []):
                geom = item.get("geom")
                if not geom or not geom.get("coordinates"):
                    continue

                heading = item.get("yaw")
                roll = item.get("roll")
                if heading is not None and roll is not None:
                    norm_roll = ((roll + 180) % 360) - 180
                    if abs(norm_roll) > 90:
                        heading = (heading + 180) % 360
                if heading is None:
                    continue

                # Only visual images
                sensor = (item.get("tipo_sensor") or "").upper()
                w = item.get("resolucion_ancho") or 0
                if sensor not in ("RGB", "VISUAL") and w < 3000:
                    continue

                coords_by_id[item["id"]] = {
                    "lat": geom["coordinates"][1],
                    "lon": geom["coordinates"][0],
                    "heading": heading,
                    "image_width": w or 4000,
                }

            # 3. Build FOV input: only images with detections
            for img in viewer_items:
                image_id = img.get("id")
                coord = coords_by_id.get(image_id)
                if not coord:
                    continue

                infs = img.get("inferencias", [])
                # Filter by clase if specified
                if req.clase:
                    infs = [inf for inf in infs if inf.get("clase") == req.clase]

                if not infs:
                    continue  # Skip images without matching detections

                images_for_fov.append({
                    "image_id": str(image_id),
                    "lat": coord["lat"],
                    "lon": coord["lon"],
                    "heading": coord["heading"],
                    "image_width": coord["image_width"],
                    "detections": [
                        {
                            "id": str(inf.get("id", "")),
                            "bbox_xywh": inf.get("bbox_xywh", []),
                        }
                        for inf in infs
                    ],
                })

        # 4. Compute FOV
        result = build_feature_collection(images_for_fov, req.fov_degrees, req.radius_meters)
        result["metadata"]["source"] = "database"
        result["metadata"]["inspection_id"] = req.inspection_id
        result["metadata"]["mission"] = req.mission or "all"
        if req.clase:
            result["metadata"]["clase"] = req.clase
        return result
