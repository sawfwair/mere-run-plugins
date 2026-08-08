from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]
UInt8Array = NDArray[np.uint8]
Int32Array = NDArray[np.int32]
Int64Array = NDArray[np.int64]
NumericArray = NDArray[np.generic]


class StacAsset(Protocol):
    href: str
    extra_fields: Mapping[str, object]


class StacItem(Protocol):
    assets: Mapping[str, StacAsset]
    datetime: datetime | None
    collection_id: str
    id: str


class StacCollection(Protocol):
    def get_item(self, item_id: str) -> StacItem | None: ...


class StacCatalog(Protocol):
    def get_collection(self, collection_id: str) -> StacCollection | None: ...


class ResamplingNamespace(Protocol):
    bilinear: object
    nearest: object
