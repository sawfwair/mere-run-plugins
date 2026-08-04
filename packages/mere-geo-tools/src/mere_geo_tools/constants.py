from __future__ import annotations

MODEL_ID = "ibm-esa-geospatial/TerraMind-base-Flood"
MODEL_REVISION = "1e4b2429d17234922f8d92beb0d725af4db85c08"
MODEL_CONFIG = "terramind_v1_base_impactmesh_flood.yaml"
MODEL_CHECKPOINT = "TerraMind_v1_base_ImpactMesh_flood.pt"

THOR_MODEL_ID = "FM4CS/THOR-1.0-base"
THOR_REVISION = "823c265cbb941a3e1b9054910a65dbe190c11f11"
THOR_CHECKPOINT_BYTES = 376_628_228

TEMPORAL_ROLES = ["pre_month", "pre_event", "event", "post_event"]
S2_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]
S1_BANDS = ["vv", "vh"]

FLOOD_MEANS = {
    "S2L2A": [
        1223.128,
        1251.355,
        1423.443,
        1408.984,
        1786.818,
        2448.316,
        2685.642,
        2745.795,
        2817.936,
        3194.081,
        1964.659,
        1399.317,
    ],
    "S1RTC": [-9.98, -15.968],
    "DEM": [141.786],
}
FLOOD_STDS = {
    "S2L2A": [
        2358.709,
        2227.598,
        2082.363,
        2068.519,
        2086.682,
        2003.085,
        2019.494,
        2060.309,
        2014.732,
        2992.644,
        1414.951,
        1218.357,
    ],
    "S1RTC": [4.24, 4.105],
    "DEM": [189.363],
}
