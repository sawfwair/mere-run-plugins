from __future__ import annotations

MODEL_ID = "ibm-esa-geospatial/TerraMind-base-Flood"
MODEL_REVISION = "1e4b2429d17234922f8d92beb0d725af4db85c08"
MODEL_CHECKPOINT = "TerraMind_v1_base_ImpactMesh_flood.pt"
MODEL_CHECKPOINT_SHA256 = "22627584c2db618c2f6ddb64b411a95762a893becb25104e3f66bfebecaa71e9"
MODEL_CONFIG_SHA256 = "d6c74ef58085a6d3f27bca2d570d84b9256100b885e7c51521c9d0cf7f335282"
NATIVE_MODEL_ID = "vision-flood-terramind-base"
NATIVE_WEIGHTS_SHA256 = "4940ad94df06a923e3a919f944a71ad01892872e89c428abe718eefc44d0f95a"

FIRE_MODEL_ID = "ibm-esa-geospatial/TerraMind-base-Fire"
FIRE_MODEL_REVISION = "6eb5178aac4f8a4191796258ae26e796195cc00d"
FIRE_MODEL_CHECKPOINT = "TerraMind_v1_base_ImpactMesh_fire.pt"
FIRE_MODEL_CHECKPOINT_SHA256 = "c16c070d95e9944c4b1a14c56cdd16f7821b133c8f2521985b579d08c2d8c72e"
FIRE_MODEL_CONFIG_SHA256 = "0ccbd6b9464f5a95198204b31dda77a1e7637611bb69bff7d569315f8ccc863f"
FIRE_NATIVE_MODEL_ID = "vision-fire-terramind-base"
FIRE_NATIVE_WEIGHTS_SHA256 = "7ebd587e684285112554743a27d50de596e807746c4ea38cfab34999c0adf21a"

TESSERA_MODELS = {
    "nano": {
        "id": "vision-embed-tessera-v2-nano",
        "repository": "geotessera/TESSERA-V-2.0-2B-N",
        "revision": "9645033fdcd5c0686bab00720e5553ce307629cf",
        "weights_sha256": "a1125fbe82dd83e0377bd66dae8c67df1c2bd1d1873cb0c86d1befd22fbd4fa6",
        "dimensions": 128,
    },
    "small": {
        "id": "vision-embed-tessera-v2-small",
        "repository": "geotessera/TESSERA-V-2.0-2B-S",
        "revision": "21760b27ff16ca7aab01986b7b3460e3027b19c6",
        "weights_sha256": "f8be74a820e97791e3c27127e581c089b4300d886b6d03dcbe576a95227dda6c",
        "dimensions": 128,
    },
    "medium": {
        "id": "vision-embed-tessera-v2-medium",
        "repository": "geotessera/TESSERA-V-2.0-2B-M",
        "revision": "41db8ee5ddfcf6867f965526c2097d70c3c55c31",
        "weights_sha256": "535ab12bc548a281dfa5e64f0b7cc3dc60691df0b55d99525e6cd8f4d4420d34",
        "dimensions": 128,
    },
    "large": {
        "id": "vision-embed-tessera-v2-large",
        "repository": "geotessera/TESSERA-V-2.0-2B-L",
        "revision": "b45f24463acf3fcfe030f94735d3e817b24100d0",
        "weights_sha256": "0fe8a10f0aca102e39f54206efa3f71992c6523a0d4113b23ba1552495b9c640",
        "dimensions": 128,
    },
    "teacher": {
        "id": "vision-embed-tessera-v2-teacher",
        "repository": "geotessera/TESSERA-V-2.0-2B-Teacher",
        "revision": "262170691f167085a7f86750066066e3d6ab6e10",
        "weights_sha256": "f89af4788204c7a5c8e15fbefcbc448425694914901ed970e6b7a04546e139d2",
        "dimensions": 1024,
    },
}

OLMOEARTH_MODELS = {
    "nano": {
        "id": "vision-embed-olmoearth-v12-nano",
        "repository": "allenai/OlmoEarth-v1_2-Nano",
        "revision": "e1f693ae2a7d5b57871a978e9d09e22d05206747",
        "weights_sha256": "7f910264cf5f09f1853d9303c9f2c4b5e0f383d503b9d5800a9823ffa110dec1",
        "dimensions": 128,
    },
    "tiny": {
        "id": "vision-embed-olmoearth-v12-tiny",
        "repository": "allenai/OlmoEarth-v1_2-Tiny",
        "revision": "12a9fdbfeff905d7e147e7497f9f7a95c518eefc",
        "weights_sha256": "308a98d482c5ddaec1c2552721a97802a9d2a144e84fcbb58b4dedbfa98f53b2",
        "dimensions": 192,
    },
    "small": {
        "id": "vision-embed-olmoearth-v12-small",
        "repository": "allenai/OlmoEarth-v1_2-Small",
        "revision": "a207c9a789483f95de1e9fb06acadb3da3775863",
        "weights_sha256": "a967dc27611e2effed4a7f74db82f6fcd1b561f58441430d5d7aed15dd2fdf6d",
        "dimensions": 384,
    },
    "base": {
        "id": "vision-embed-olmoearth-v12-base",
        "repository": "allenai/OlmoEarth-v1_2-Base",
        "revision": "581aa9baaa7aed4348c0903617eb92ee9f89e2ec",
        "weights_sha256": "0f34899dc1b6e4ec9d436c2aa26f092dbd54dbb846098a3cc11661d5b00dcd29",
        "dimensions": 768,
    },
}

THOR_MODEL_ID = "FM4CS/THOR-1.0-base"
THOR_REVISION = "823c265cbb941a3e1b9054910a65dbe190c11f11"
THOR_CHECKPOINT_BYTES = 376_628_228

TEMPORAL_ROLES = ["pre_month", "pre_event", "event", "post_event"]
S2_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]
S1_BANDS = ["vv", "vh"]
TESSERA_S2_BANDS = ["B04", "B02", "B03", "B08", "B8A", "B05", "B06", "B07", "B11", "B12"]
OLMOEARTH_S2_BANDS = ["B02", "B03", "B04", "B08", "B05", "B06", "B07", "B8A", "B11", "B12", "B01", "B09"]
OLMOEARTH_LANDSAT_BANDS = ["B8", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B9", "B10", "B11"]
OLMOEARTH_LANDSAT_SOURCE_CONTRACT = "landsat-oli-tirs-level1-dn-v1"
PLANETARY_COMPUTER_STAC_ENDPOINT = "https://planetarycomputer.microsoft.com/api/stac/v1"
USGS_LANDSAT_STAC_ENDPOINT = "https://landsatlook.usgs.gov/stac-server"
USGS_LANDSAT_COLLECTION = "landsat-c2l1"
USGS_LANDSAT_AWS_REGION = "us-west-2"
USGS_LANDSAT_ASSETS = {
    "B8": "pan",
    "B1": "coastal",
    "B2": "blue",
    "B3": "green",
    "B4": "red",
    "B5": "nir08",
    "B6": "swir16",
    "B7": "swir22",
    "B9": "cirrus",
    "B10": "lwir11",
    "B11": "lwir12",
}

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

FIRE_MEANS = {
    "S2L2A": [
        801.325,
        861.655,
        991.636,
        1019.702,
        1366.43,
        2000.191,
        2255.338,
        2354.884,
        2481.838,
        2747.908,
        2185.777,
        1495.209,
    ],
    "S1RTC": [-9.838, -15.465],
    "DEM": [412.745],
}
FIRE_STDS = {
    "S2L2A": [
        1960.514,
        1732.936,
        1494.812,
        1384.473,
        1385.129,
        1309.367,
        1322.601,
        1352.448,
        1336.39,
        2379.374,
        1145.593,
        991.566,
    ],
    "S1RTC": [3.505, 3.422],
    "DEM": [354.58],
}
