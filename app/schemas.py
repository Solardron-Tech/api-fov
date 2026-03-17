"""Pydantic v2 request/response schemas."""

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class Detection(BaseModel):
    id: Optional[str] = None
    clase: Optional[str] = None
    bbox_xywh: list[float] = Field(
        default_factory=lambda: [0.5, 0.5, 0.1, 0.1],
        description="[x, y, w, h] — normalized (0-1) or pixel coords",
    )


class ImageInput(BaseModel):
    image_id: Optional[str] = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    heading: float = Field(ge=0, lt=360)
    image_width: int = Field(default=4000, ge=1)
    detections: list[Detection] = Field(default_factory=list)


class ComputeRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    heading: float = Field(ge=0, lt=360)
    image_width: int = Field(default=4000, ge=1)
    detections: list[Detection] = Field(default_factory=list)
    fov_degrees: float = Field(default=70.0, gt=0, le=180)
    radius_meters: float = Field(default=1.66, gt=0, le=100)


class BatchRequest(BaseModel):
    images: list[ImageInput] = Field(min_length=1)
    fov_degrees: float = Field(default=70.0, gt=0, le=180)
    radius_meters: float = Field(default=1.66, gt=0, le=100)

    @field_validator("images")
    @classmethod
    def cap_batch_size(cls, v: list) -> list:
        if len(v) > 50_000:
            raise ValueError("Batch size capped at 50,000 images")
        return v


class ByFlightRequest(BaseModel):
    inspection_id: str = Field(min_length=1, description="Inspection UUID (FK → inspections.id)")
    mission: Optional[str] = Field(default=None, description="Mission/folder name (null = all missions)")
    clase: Optional[str] = Field(default=None, description="Filter detections by class (e.g. 'pile', 'mc4')")
    fov_degrees: float = Field(default=70.0, gt=0, le=180)
    radius_meters: float = Field(default=1.66, gt=0, le=100)
