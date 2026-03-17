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
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Fetch image coordinates by inspection_id (+ optional mission)
        params: dict[str, str] = {
            "inspection_id": req.inspection_id,
            "limit": "10000",
            "include_metadata_raw": "false",
        }
        if req.mission:
            params["mission"] = req.mission

        img_resp = await client.get(f"{POSTGRES_BASE}/imagenes/", params=params)
        if img_resp.status_code != 200:
            raise HTTPException(502, f"imagenes API returned {img_resp.status_code}")

        img_data = img_resp.json()
        items = img_data.get("items", [])
        if not items:
            return {
                "type": "FeatureCollection",
                "features": [],
                "metadata": {"total_images": 0, "total_features": 0, "elapsed_ms": 0},
            }

        # Parse DB rows → coordinate map, keyed by gs_path
        coords_by_gs: dict[str, dict] = {}
        flight_paths: set[str] = set()

        for item in items:
            geom = item.get("geom")
            gs_path = item.get("gs_path", "")
            if not geom or not geom.get("coordinates") or not gs_path:
                continue

            heading = item.get("yaw")
            roll = item.get("roll")
            if heading is not None and roll is not None:
                norm_roll = ((roll + 180) % 360) - 180
                if abs(norm_roll) > 90:
                    heading = (heading + 180) % 360
            if heading is None:
                continue

            # Only visual images (FOV applies to RGB camera)
            sensor = (item.get("tipo_sensor") or "").upper()
            w = item.get("resolucion_ancho") or 0
            is_visual = sensor in ("RGB", "VISUAL") or w >= 3000
            if not is_visual:
                continue

            coords_by_gs[gs_path] = {
                "lat": geom["coordinates"][1],
                "lon": geom["coordinates"][0],
                "heading": heading,
                "image_width": w or 4000,
                "file": item.get("nombre_archivo", gs_path.rsplit("/", 1)[-1]),
            }

            # Derive flight_path (directory) for inference lookup
            # gs://bucket/prefix/mission/image.jpg → gs://bucket/prefix/mission/
            dir_path = gs_path.rsplit("/", 1)[0] + "/"
            flight_paths.add(dir_path)

        # 2. Fetch inferences for each unique flight_path
        inferences_by_uri: dict[str, list] = {}
        for fp in flight_paths:
            inf_resp = await client.get(
                f"{POSTGRES_BASE}/inferencias/by-flight/",
                params={"flight_path": fp, "limit": "50000"},
            )
            if inf_resp.status_code == 200:
                inf_data = inf_resp.json()
                inf_items = inf_data if isinstance(inf_data, list) else inf_data.get("items", [])
                for inf in inf_items:
                    uri = inf.get("uri_imagen", "")
                    inferences_by_uri.setdefault(uri, []).append(inf)

        # 3. Build images with detections
        images = []
        for gs_path, coord in coords_by_gs.items():
            infs = inferences_by_uri.get(gs_path, [])
            images.append({
                "image_id": coord["file"],
                "lat": coord["lat"],
                "lon": coord["lon"],
                "heading": coord["heading"],
                "image_width": coord["image_width"],
                "detections": [
                    {"id": str(inf.get("id", "")), "bbox_xywh": inf.get("bbox_xywh", [])}
                    for inf in infs
                ],
            })

        # 4. Compute
        result = build_feature_collection(images, req.fov_degrees, req.radius_meters)
        result["metadata"]["source"] = "database"
        result["metadata"]["inspection_id"] = req.inspection_id
        result["metadata"]["mission"] = req.mission or "all"
        result["metadata"]["flight_paths"] = list(flight_paths)
        return result
