"""Configuração do classificador, carregada de YAML e validada com pydantic."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "classification.yaml"


class Radiometry(BaseModel):
    default_scale: float = Field(gt=0)
    default_offset: float
    nodata_dn: int = Field(ge=0)


class Bands(BaseModel):
    blue: int = Field(ge=1)
    green: int = Field(ge=1)
    red: int = Field(ge=1)
    nir: int = Field(ge=1)

    @model_validator(mode="after")
    def _distinct(self) -> "Bands":
        if len({self.blue, self.green, self.red, self.nir}) != 4:
            raise ValueError("as quatro bandas precisam ter índices distintos")
        return self


class Scl(BaseModel):
    keep_classes: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _range(self) -> "Scl":
        if any(not 0 <= c <= 11 for c in self.keep_classes):
            raise ValueError("classes SCL vão de 0 a 11")
        return self


class Indices(BaseModel):
    savi_l: float = Field(ge=0, le=1)
    texture_window: int = Field(ge=3)

    @model_validator(mode="after")
    def _odd(self) -> "Indices":
        if self.texture_window % 2 == 0:
            raise ValueError("texture_window precisa ser ímpar")
        return self


class Rules(BaseModel):
    ndvi_min: float = Field(ge=-1, le=1)
    dense_ndvi_default: float = Field(ge=-1, le=1)
    dense_ndvi_floor: float = Field(ge=-1, le=1)
    dense_ndvi_ceiling: float = Field(ge=-1, le=1)
    otsu_min_separability: float = Field(ge=0, le=1)
    ndwi_max: float = Field(ge=-1, le=1)
    dense_core_min_area_ha: float = Field(ge=0)
    dense_buffer_px: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Rules":
        if not (self.dense_ndvi_floor <= self.dense_ndvi_default <= self.dense_ndvi_ceiling):
            raise ValueError(
                "exigido: dense_ndvi_floor <= dense_ndvi_default <= dense_ndvi_ceiling"
            )
        if self.ndvi_min >= self.dense_ndvi_floor:
            raise ValueError("ndvi_min precisa ser menor que dense_ndvi_floor")
        return self


class Temporal(BaseModel):
    ndvi_min_other: float = Field(ge=-1, le=1)
    max_abs_ndvi_change: float = Field(gt=0, le=2)
    # Desconta do ΔNDVI a mediana do ΔNDVI da vegetação da cena (sazonalidade)
    seasonal_normalization: bool = True
    normalization_min_pixels: int = Field(ge=1)
    cloud_blue_min: float = Field(gt=0)
    min_overlap: float = Field(ge=0, le=1)


class Morphology(BaseModel):
    opening_iterations: int = Field(ge=0)
    min_area_ha: float = Field(ge=0)


class ClassificationConfig(BaseModel):
    radiometry: Radiometry
    bands: Bands
    scl: Scl
    indices: Indices
    rules: Rules
    temporal: Temporal
    morphology: Morphology


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ClassificationConfig:
    with open(path, encoding="utf-8") as f:
        return ClassificationConfig.model_validate(yaml.safe_load(f))
