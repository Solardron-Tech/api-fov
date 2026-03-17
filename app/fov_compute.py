"""
Pure FOV & detection ray geometry computation.

All coordinates are WGS84 (EPSG:4326).
Output: GeoJSON-compatible [lon, lat] arrays.
"""

import math
from typing import Optional

DEG_TO_RAD = math.pi / 180
METERS_PER_DEG_LAT = 111_320
DEFAULT_FOV_DEG = 70.0
DEFAULT_RADIUS_M = 1.66
DEFAULT_SEGMENTS = 16
DEFAULT_IMAGE_WIDTH = 4000


def compute_fov_cone(
    lon: float,
    lat: float,
    heading: float,
    radius: float = DEFAULT_RADIUS_M,
    fov_deg: float = DEFAULT_FOV_DEG,
    segments: int = DEFAULT_SEGMENTS,
) -> list[list[float]]:
    """Compute FOV cone polygon ring as [[lon, lat], ...]."""
    center_angle = (90 - heading) * DEG_TO_RAD
    half_fov_rad = (fov_deg / 2) * DEG_TO_RAD
    start_angle = center_angle + half_fov_rad
    end_angle = center_angle - half_fov_rad
    cos_lat = math.cos(lat * DEG_TO_RAD)

    ring: list[list[float]] = [[lon, lat]]  # center

    for i in range(segments + 1):
        angle = start_angle - (i * (start_angle - end_angle) / segments)
        d_lat = (math.sin(angle) * radius) / METERS_PER_DEG_LAT
        d_lon = (math.cos(angle) * radius) / (METERS_PER_DEG_LAT * cos_lat)
        ring.append([lon + d_lon, lat + d_lat])

    ring.append([lon, lat])  # close
    return ring


def compute_detection_ray(
    lon: float,
    lat: float,
    heading: float,
    norm_x: float,
    radius: float = DEFAULT_RADIUS_M,
    fov_deg: float = DEFAULT_FOV_DEG,
) -> list[list[float]]:
    """Compute detection ray as [[lon, lat], [lon, lat]]."""
    center_angle = (90 - heading) * DEG_TO_RAD
    half_fov_rad = (fov_deg / 2) * DEG_TO_RAD
    angle = (center_angle + half_fov_rad) - (norm_x * 2 * half_fov_rad)
    cos_lat = math.cos(lat * DEG_TO_RAD)

    d_lat = (math.sin(angle) * radius) / METERS_PER_DEG_LAT
    d_lon = (math.cos(angle) * radius) / (METERS_PER_DEG_LAT * cos_lat)

    return [[lon, lat], [lon + d_lon, lat + d_lat]]


def normalize_detection_x(
    bbox_xywh: Optional[list[float]],
    image_width: int = DEFAULT_IMAGE_WIDTH,
) -> float:
    """Normalize detection X from bbox to 0-1 range."""
    x = 0.5
    if bbox_xywh and len(bbox_xywh) >= 1:
        x = bbox_xywh[0]
    if x > 1:
        x = x / image_width if image_width > 0 else 0.5
    return max(0.0, min(1.0, x))


def build_image_features(
    image: dict,
    fov_deg: float = DEFAULT_FOV_DEG,
    radius: float = DEFAULT_RADIUS_M,
) -> list[dict]:
    """Build GeoJSON features for a single image (1 cone + N rays)."""
    lon = image["lon"]
    lat = image["lat"]
    heading = image["heading"]
    image_width = image.get("image_width", DEFAULT_IMAGE_WIDTH)
    detections = image.get("detections", [])

    features: list[dict] = []

    # FOV cone
    ring = compute_fov_cone(lon, lat, heading, radius, fov_deg)
    features.append({
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "feature_type": "fov_cone",
            "image_id": image.get("image_id"),
            "heading": heading,
        },
    })

    # Detection rays
    for det in detections:
        norm_x = normalize_detection_x(det.get("bbox_xywh"), image_width)
        line = compute_detection_ray(lon, lat, heading, norm_x, radius, fov_deg)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": line},
            "properties": {
                "feature_type": "detection_ray",
                "image_id": image.get("image_id"),
                "detection_id": det.get("id"),
                "clase": det.get("clase"),
                "norm_x": norm_x,
            },
        })

    return features


def build_feature_collection(
    images: list[dict],
    fov_deg: float = DEFAULT_FOV_DEG,
    radius: float = DEFAULT_RADIUS_M,
) -> dict:
    """Build GeoJSON FeatureCollection from array of images."""
    import time

    t0 = time.monotonic()
    features: list[dict] = []

    for img in images:
        if img.get("lat") is None or img.get("lon") is None or img.get("heading") is None:
            continue
        features.extend(build_image_features(img, fov_deg, radius))

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_images": len(images),
            "total_features": len(features),
            "elapsed_ms": elapsed_ms,
        },
    }
