from __future__ import annotations

from typing import cast

import numpy as np

from .external_types import BoolArray


def aoi_validity_mask(
    bounds_wgs84: list[float],
    crs: str,
    transform: object,
    height: int,
    width: int,
) -> BoolArray:
    """Return pixels whose centers fall inside the exact requested WGS84 footprint."""
    from rasterio.features import geometry_mask
    from rasterio.warp import transform as transform_coordinates

    west, south, east, north = bounds_wgs84
    samples = 32
    bottom = [(x, south) for x in np.linspace(west, east, samples, endpoint=False)]
    right = [(east, y) for y in np.linspace(south, north, samples, endpoint=False)]
    top = [(x, north) for x in np.linspace(east, west, samples, endpoint=False)]
    left = [(west, y) for y in np.linspace(north, south, samples, endpoint=False)]
    ring = [*bottom, *right, *top, *left]
    ring.append(ring[0])
    xs, ys = transform_coordinates(
        "EPSG:4326",
        crs,
        [point[0] for point in ring],
        [point[1] for point in ring],
    )
    geometry = {"type": "Polygon", "coordinates": [[*zip(xs, ys)]]}
    return cast(
        BoolArray,
        geometry_mask(
            [geometry],
            out_shape=(height, width),
            transform=transform,
            all_touched=False,
            invert=True,
        ),
    )
