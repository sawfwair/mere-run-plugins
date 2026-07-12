from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from PIL import Image, ImageDraw

from mere_vfx_tools import cli


def write_image(path: pathlib.Path, color: tuple[int, int, int, int] = (20, 220, 30, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (32, 24), color)
    ImageDraw.Draw(image).rectangle((8, 5, 23, 20), fill=(220, 40, 30, color[3]))
    image.save(path)


def write_request(path: pathlib.Path, inputs: dict[str, object], options: dict[str, object] | None = None) -> None:
    path.write_text(json.dumps({"inputs": inputs, "options": options or {}}))


def write_fake_mere_run(
    path: pathlib.Path,
    triposr_fault: str = "",
    instantmesh_fault: str = "",
    da3_fault: str = "",
    geometry_fault: str = "",
    vda_fault: str = "",
) -> None:
    path.write_text(
        "import hashlib, json, pathlib, sys\n"
        "from PIL import Image, ImageDraw\n"
        "args = sys.argv[1:]\n"
        f"triposr_fault = {triposr_fault!r}\n"
        f"instantmesh_fault = {instantmesh_fault!r}\n"
        f"da3_fault = {da3_fault!r}\n"
        f"geometry_fault = {geometry_fault!r}\n"
        f"vda_fault = {vda_fault!r}\n"
        "def value(flag): return args[args.index(flag) + 1]\n"
        "def checksum(path): return hashlib.sha256(path.read_bytes()).hexdigest()\n"
        "def artifact(kind, path, root, media_type, view_index=None):\n"
        "    item = {'kind': kind, 'relativePath': str(path.relative_to(root)), 'mediaType': media_type, 'byteCount': path.stat().st_size, 'sha256': checksum(path)}\n"
        "    if view_index is not None: item['viewIndex'] = view_index\n"
        "    return item\n"
        "if args[:2] == ['vision', 'track']:\n"
        "    pathlib.Path(value('--output')).write_bytes(b'review')\n"
        "    raw = pathlib.Path(value('--mask-output-dir'))\n"
        "    frames = []\n"
        "    for index in range(2):\n"
        "        frame_dir = raw / f'frame-{index:06d}'\n"
        "        frame_dir.mkdir(parents=True, exist_ok=True)\n"
        "        mask_path = frame_dir / 'actor.png'\n"
        "        mask = Image.new('L', (32, 24), 0)\n"
        "        ImageDraw.Draw(mask).rectangle((7 + index, 4, 24, 21), fill=255)\n"
        "        mask.save(mask_path)\n"
        "        frames.append({'frameIndex': index, 'detections': [{'objectID': 'actor-1', 'label': 'actor', 'visible': True, 'box': [7 + index, 4, 17, 17], 'maskPath': str(mask_path)}]})\n"
        "    pathlib.Path(value('--json-output')).write_text(json.dumps({'fps': 24, 'frames': frames}))\n"
        "elif args[:2] == ['vision', 'pose']:\n"
        "    output = pathlib.Path(value('--json-output'))\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    output.write_text(json.dumps({'schemaVersion': 1, 'imageWidth': 32, 'imageHeight': 24, 'coordinateSpace': 'normalized-bottom-left', 'subjects': [{'kind': 'body', 'index': 0, 'confidence': 0.9, 'points': [{'name': 'head_joint', 'x': 0.5, 'y': 0.75, 'confidence': 0.8}]}, {'kind': 'hand', 'index': 0, 'confidence': 0.7, 'points': [{'name': 'wrist', 'x': 0.6, 'y': 0.4, 'confidence': 0.6}]}]}))\n"
        "elif args[:2] == ['vision', 'flow']:\n"
        "    flow = pathlib.Path(value('--output'))\n"
        "    metadata = pathlib.Path(value('--json-output'))\n"
        "    flow.parent.mkdir(parents=True, exist_ok=True)\n"
        "    flow.write_bytes(b'PIEH' + bytes(32))\n"
        "    metadata.write_text(json.dumps({'schemaVersion': 1, 'width': 32, 'height': 24, 'vectorCount': 768, 'meanMagnitude': 1.25, 'maximumMagnitude': 3.5, 'accuracy': value('--accuracy')}))\n"
        "elif args[:2] == ['vision', 'geometry']:\n"
        "    source = pathlib.Path(args[2]).resolve()\n"
        "    root = pathlib.Path(value('--output')).resolve()\n"
        "    root.mkdir(parents=True, exist_ok=True)\n"
        "    depth_exr = root / 'geometry-depth.exr'; depth_exr.write_bytes(b'fake-metric-depth')\n"
        "    depth_png = root / 'geometry-depth.png'; Image.new('L', (32, 24), 128).save(depth_png)\n"
        "    normal_exr = root / 'geometry-normal.exr'; normal_exr.write_bytes(b'fake-camera-normals')\n"
        "    normal_png = root / 'geometry-normal.png'; Image.new('RGB', (32, 24), (128, 128, 255)).save(normal_png)\n"
        "    validity = root / 'geometry-validity.png'; Image.new('L', (32, 24), 255).save(validity)\n"
        "    points = root / 'geometry-points.ply'; points.write_text('ply\\nformat ascii 1.0\\nelement vertex 0\\nend_header\\n')\n"
        "    camera = root / 'geometry-camera.json'; camera.write_text(json.dumps({'intrinsics': {'imageWidth': 32, 'imageHeight': 24, 'normalizedFX': 1.0, 'normalizedFY': 1.0, 'normalizedCX': 0.5, 'normalizedCY': 0.5}, 'extrinsics': None}))\n"
        "    artifacts = [artifact('depth-exr', depth_exr, root, 'image/x-exr'), artifact('depth-preview', depth_png, root, 'image/png'), artifact('normal-exr', normal_exr, root, 'image/x-exr'), artifact('normal-preview', normal_png, root, 'image/png'), artifact('validity-mask', validity, root, 'image/png'), artifact('point-cloud', points, root, 'application/ply'), artifact('camera', camera, root, 'application/json')]\n"
        "    native_manifest = root / 'geometry-manifest.json'\n"
        "    geometry_model = {'modelID': 'vision-geometry-moge2-small', 'upstreamRepository': 'Ruicheng/moge-2-vits-normal-onnx', 'upstreamRevision': 'e50ffda41565591092adea54c6ac83d6212e1e23', 'license': 'MIT', 'weightsSHA256': '24eacb5dc7a2c54c7bc98f7de085ffbed79ad006ea5b664c2c2cdc02ff3a52f0', 'inferenceBackend': 'mere.run-native-mlx'}\n"
        "    if geometry_fault == 'model-sha': geometry_model['weightsSHA256'] = '0' * 64\n"
        "    geometry_input_path = str(root / 'wrong.png') if geometry_fault == 'input-path' else str(source)\n"
        "    geometry_input_bytes = source.stat().st_size + (1 if geometry_fault == 'input-byte-count' else 0)\n"
        "    if geometry_fault == 'input-sha': geometry_input_sha = '0' * 64\n"
        "    else: geometry_input_sha = checksum(source)\n"
        "    native_manifest.write_text(json.dumps({'schemaVersion': 1 if geometry_fault == 'schema' else 2, 'inputPath': geometry_input_path, 'inputByteCount': geometry_input_bytes, 'inputSHA256': geometry_input_sha, 'outputDirectory': str(root), 'width': 32, 'height': 24, 'units': 'meters', 'coordinateSystem': 'camera-x-right-y-down-z-forward', 'model': geometry_model, 'camera': json.loads(camera.read_text()), 'artifacts': artifacts}))\n"
        "    print(json.dumps({'schemaVersion': 1, 'status': 'completed', 'manifestPath': str(native_manifest), 'modelID': 'vision-geometry-moge2-small', 'width': 32, 'height': 24, 'units': 'meters', 'artifacts': artifacts}))\n"
        "elif args[:2] == ['vision', 'depth-video']:\n"
        "    source = pathlib.Path(args[2]).resolve()\n"
        "    root = pathlib.Path(value('--output')).resolve()\n"
        "    frames_root = root / 'frames'; frames_root.mkdir(parents=True, exist_ok=True)\n"
        "    frames = []\n"
        "    for index in range(2):\n"
        "        depth = frames_root / f'{index:06d}-depth.exr'; depth.write_bytes(b'fake-video-depth-' + bytes([index]))\n"
        "        preview = frames_root / f'{index:06d}-depth.png'; Image.new('L', (32, 24), 70 + index * 30).save(preview)\n"
        "        items = [artifact('depth-exr', depth, root, 'image/x-exr'), artifact('depth-preview', preview, root, 'image/png')]\n"
        "        frames.append({'index': index, 'timeSeconds': index / 12, 'depthPath': str(depth.relative_to(root)), 'previewPath': str(preview.relative_to(root)), 'confidencePath': None, 'intrinsics': None, 'artifacts': items})\n"
        "    native_manifest = root / 'depth-sequence-manifest.json'\n"
        "    vda_model = {'modelID': 'vision-depth-vda-small', 'upstreamRepository': 'depth-anything/Video-Depth-Anything-Small', 'upstreamRevision': '256875362cff76724b920335dfb4b29dd611f66e', 'license': 'Apache-2.0', 'weightsSHA256': '13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609', 'inferenceBackend': 'mere.run-native-mlx'}\n"
        "    if vda_fault == 'model-sha': vda_model['weightsSHA256'] = '0' * 64\n"
        "    vda_input_path = str(root / 'wrong.mov') if vda_fault == 'input-path' else str(source)\n"
        "    vda_input_bytes = source.stat().st_size + (1 if vda_fault == 'input-byte-count' else 0)\n"
        "    vda_input_sha = '0' * 64 if vda_fault == 'input-sha' else checksum(source)\n"
        "    native_manifest.write_text(json.dumps({'schemaVersion': 1 if vda_fault == 'schema' else 2, 'inputPath': vda_input_path, 'inputByteCount': vda_input_bytes, 'inputSHA256': vda_input_sha, 'outputDirectory': str(root), 'width': 32, 'height': 24, 'fps': 12, 'frameCount': 2, 'semantics': 'affine-relative', 'model': vda_model, 'temporalWindowLength': 32, 'temporalOverlap': 10, 'frames': frames}))\n"
        "    review = root / 'depth-review.mp4'; review.write_bytes(b'fake-depth-review')\n"
        "    print(json.dumps({'schemaVersion': 1, 'status': 'completed', 'manifestPath': str(native_manifest), 'reviewVideo': artifact('depth-review-video', review, root, 'video/mp4'), 'modelID': 'vision-depth-vda-small', 'checkpointSHA256': vda_model['weightsSHA256'], 'semantics': 'affine-relative', 'width': 32, 'height': 24, 'fps': 12, 'frameCount': 2, 'windowCount': 1, 'temporalWindowLength': 32, 'temporalOverlap': 10, 'streamsFinalizedFrames': True, 'hasConfidence': False, 'hasCameraIntrinsics': False, 'hasPointCloud': False}))\n"
        "elif args[:2] == ['vision', 'geometry-multiview']:\n"
        "    root = pathlib.Path(value('--output')).resolve()\n"
        "    views_root = root / 'views'; views_root.mkdir(parents=True, exist_ok=True)\n"
        "    image_args = [str(pathlib.Path(item).resolve()) for item in args[2:args.index('--output')]]\n"
        "    process_resolution = int(value('--process-resolution')); reference_view = value('--reference-view')\n"
        "    confidence_percentile = float(value('--confidence-percentile')); maximum_point_count = int(value('--max-points'))\n"
        "    checkpoint = {'modelID': 'vision-geometry-da3-small', 'repository': 'depth-anything/DA3-SMALL', 'revision': 'a' * 40, 'sourceRepository': 'ByteDance-Seed/Depth-Anything-3', 'sourceRevision': 'b' * 40, 'license': 'Apache-2.0', 'weightsByteCount': 100, 'weightsSHA256': 'c' * 64, 'configurationByteCount': 200, 'configurationSHA256': 'd' * 64, 'inferenceBackend': 'mere.run-native-mlx'}\n"
        "    if da3_fault == 'checkpoint-model': checkpoint['modelID'] = 'bad model!'\n"
        "    if da3_fault == 'checkpoint-revision': checkpoint['revision'] = 'not-a-revision'\n"
        "    if da3_fault == 'checkpoint-config-sha': checkpoint['configurationSHA256'] = 'not-a-sha'\n"
        "    if da3_fault == 'checkpoint-weights-sha': checkpoint['weightsSHA256'] = 'not-a-sha'\n"
        "    artifacts = []; views = []\n"
        "    for index, source in enumerate(image_args):\n"
        "        source_path = pathlib.Path(source)\n"
        "        depth = views_root / f'{index:06d}-depth.exr'; depth.write_bytes(b'depth-' + bytes([index]))\n"
        "        confidence = views_root / f'{index:06d}-confidence.exr'; confidence.write_bytes(b'confidence-' + bytes([index]))\n"
        "        preview = views_root / f'{index:06d}-depth.png'; Image.new('L', (32, 24), 90 + index).save(preview)\n"
        "        rgb = views_root / f'{index:06d}-rgb.png'; Image.new('RGB', (32, 24), (20 + index, 40, 80)).save(rgb)\n"
        "        artifacts.extend([artifact('depth-exr', depth, root, 'image/x-exr', index), artifact('confidence-exr', confidence, root, 'image/x-exr', index), artifact('depth-preview', preview, root, 'image/png', index), artifact('processed-image', rgb, root, 'image/png', index)])\n"
        "        views.append({'index': index, 'sourcePath': source, 'sourceByteCount': source_path.stat().st_size, 'sourceSHA256': checksum(source_path), 'width': 32, 'height': 24, 'preprocessing': {'processResolution': process_resolution}, 'camera': {}, 'depthPath': str(depth.relative_to(root)), 'confidencePath': str(confidence.relative_to(root)), 'previewPath': str(preview.relative_to(root)), 'processedImagePath': str(rgb.relative_to(root)), 'selectedPointCount': 12})\n"
        "    if da3_fault == 'source-path': views[0]['sourcePath'] = str(root / 'wrong.png')\n"
        "    if da3_fault == 'source-byte-count': views[0]['sourceByteCount'] += 1\n"
        "    if da3_fault == 'source-sha': views[0]['sourceSHA256'] = '0' * 64\n"
        "    ply = root / 'scene.ply'; ply.write_text('ply\\nformat ascii 1.0\\nelement vertex 0\\nend_header\\n')\n"
        "    glb = root / 'scene.glb'; glb.write_bytes(b'glTF-fake-points')\n"
        "    cameras = root / 'cameras.json'; cameras.write_text(json.dumps({'schemaVersion': 1, 'views': views}))\n"
        "    transforms = root / 'transforms.json'; transforms.write_text(json.dumps({'camera_model': 'OPENCV', 'frames': views, 'ply_file_path': 'scene.ply'}))\n"
        "    artifacts.extend([artifact('point-cloud-ply', ply, root, 'application/ply'), artifact('point-cloud-glb', glb, root, 'model/gltf-binary'), artifact('cameras-json', cameras, root, 'application/json'), artifact('3dgs-transforms-json', transforms, root, 'application/json')])\n"
        "    pose_conditioned = '--cameras' in args\n"
        "    handoff = {'kind': 'nerfstudio-transforms-plus-colored-point-cloud', 'transformsPath': 'transforms.json', 'pointCloudPath': 'scene.ply', 'containsGaussianParameters': False, 'note': 'initialization only'}\n"
        "    manifest_process_resolution = process_resolution + 1 if da3_fault == 'process-resolution' else process_resolution\n"
        "    manifest_reference_view = 'first' if da3_fault == 'reference-view' and reference_view != 'first' else ('middle' if da3_fault == 'reference-view' else reference_view)\n"
        "    manifest_confidence_percentile = confidence_percentile + 1 if da3_fault == 'confidence-percentile' else confidence_percentile\n"
        "    manifest_maximum_point_count = maximum_point_count + 1 if da3_fault == 'max-points' else maximum_point_count\n"
        "    native_manifest = root / 'scene-manifest.json'\n"
        "    native_manifest.write_text(json.dumps({'schemaVersion': 1 if da3_fault == 'schema-version' else 2, 'createdAt': '2026-07-12T00:00:00Z', 'outputDirectory': str(root), 'model': {'modelID': 'vision-geometry-da3-small'}, 'checkpoint': checkpoint, 'units': 'relative', 'coordinateSystem': 'world-from-cameras-x-right-y-down-z-forward', 'poseConditioned': pose_conditioned, 'cameraSemantics': 'supplied-pose-conditioned' if pose_conditioned else 'predicted-relative', 'cameraScaleAlignment': 'relative', 'depthScaleDivisor': 1.0, 'processResolution': manifest_process_resolution, 'referenceViewStrategy': manifest_reference_view, 'confidenceThreshold': 0.5, 'confidencePercentile': manifest_confidence_percentile, 'maximumPointCount': manifest_maximum_point_count, 'pointSamplingPolicy': 'global-valid-row-major-stride-capped', 'pointCount': 24, 'pointBounds': {'minimum': [0, 0, 0], 'maximum': [1, 1, 1]}, 'pointCloudRepresentation': 'colored-points-not-mesh', 'threeDGaussianHandoff': handoff, 'views': views, 'artifacts': artifacts}))\n"
        "    print(json.dumps({'schemaVersion': 1, 'status': 'completed', 'manifestPath': str(native_manifest), 'manifestSHA256': checksum(native_manifest), 'modelID': 'vision-geometry-da3-small', 'checkpointSHA256': 'c' * 64, 'viewCount': len(views), 'width': 32, 'height': 24, 'depthUnits': 'relative', 'cameraSemantics': 'supplied-pose-conditioned' if pose_conditioned else 'predicted-relative', 'cameraScaleAlignment': 'relative', 'poseConditioned': pose_conditioned, 'referenceViewStrategy': reference_view, 'pointCount': 24, 'pointCloudRepresentation': 'colored-points-not-mesh', 'containsGaussianParameters': False, 'artifacts': artifacts}))\n"
        "elif args[:2] == ['image', 'reconstruct-3d-multiview']:\n"
        "    root = pathlib.Path(value('--output')).resolve(); root.mkdir(parents=True, exist_ok=True)\n"
        "    views = [str(pathlib.Path(args[index + 1]).resolve()) for index, item in enumerate(args) if item == '--view']\n"
        "    obj = root / 'instantmesh-asset.obj'; obj.write_text('v 0 0 0 1 0 0\\nv 1 0 0 0 1 0\\nv 0 1 0 0 0 1\\nf 1 2 3\\n')\n"
        "    ply = root / 'instantmesh-asset.ply'; ply.write_bytes(b'ply-fake-instantmesh')\n"
        "    glb = root / 'instantmesh-asset.glb'; glb.write_bytes(b'glTF-fake-instantmesh')\n"
        "    mesh_artifacts = [artifact('obj', obj, root, 'model/obj'), artifact('ply', ply, root, 'application/ply'), artifact('glb', glb, root, 'model/gltf-binary')]\n"
        "    bounds = {'minimum': [-0.5, -0.5, -0.5], 'maximum': [0.5, 0.5, 0.5]}\n"
        "    checkpoint = {'modelID': 'image-3d-instantmesh-base', 'repository': 'TencentARC/InstantMesh', 'revision': 'b785b4ecfb6636ef34a08c748f96f6a5686244d0', 'sourceRepository': 'TencentARC/InstantMesh', 'sourceRevision': '08822c52fdc399b93ea00e4fa9e596344ed52ccc', 'license': 'Apache-2.0 reconstruction weights; view generation excluded', 'format': 'verified-converted-safetensors', 'weightsByteCount': 1253463832, 'weightsSHA256': '2380601d17f6a817de0bf5328188ccea397af9d75c07b4b3cc476322dcca76af', 'sourceSHA256': '22701cd25201d624ebb1568b93cf91b43a2c32006835c08fe73e1f3c9f6c44b5', 'configurationSHA256': '33f89581172ab2d46759a1632b6e57ca9f9f1c6c23567468157cb4b48a3bc781', 'sourceManifestSHA256': '74787d99b53952df12722323521b16056bb91d7ed708cb757b7efff519ee39fa', 'viewGenerationIncluded': False}\n"
        "    mesh_model = {'modelID': checkpoint['modelID'], 'upstreamRepository': checkpoint['repository'], 'upstreamRevision': checkpoint['revision'], 'license': checkpoint['license'], 'weightsSHA256': checkpoint['weightsSHA256'], 'inferenceBackend': 'mere.run-native-mlx'}\n"
        "    if instantmesh_fault == 'mesh-provenance': mesh_model['inferenceBackend'] = 'python-sidecar'\n"
        "    mesh_manifest = root / 'instantmesh-asset-manifest.json'\n"
        "    mesh_manifest.write_text(json.dumps({'schemaVersion': 1, 'createdAt': '2026-07-11T00:00:00Z', 'inputPaths': views, 'outputDirectory': str(root), 'model': mesh_model, 'coordinateSystem': 'model-x-right-y-up-z-forward', 'units': 'normalized-object-space', 'inferredUnseenGeometry': True, 'vertexCount': 3, 'triangleCount': 1, 'bounds': bounds, 'artifacts': mesh_artifacts}))\n"
        "    artifacts = mesh_artifacts + [artifact('mesh-manifest', mesh_manifest, root, 'application/json')]\n"
        "    if instantmesh_fault == 'artifact-checksum': artifacts[0]['sha256'] = '0' * 64\n"
        "    if instantmesh_fault == 'byte-count': artifacts[0]['byteCount'] += 1\n"
        "    official_rig = '--cameras' not in args\n"
        "    camera_conditioning = 'official-deterministic-conditioning-rig' if official_rig else 'supplied-c2w-intrinsics'\n"
        "    if instantmesh_fault == 'camera-rig': camera_conditioning = 'supplied-c2w-intrinsics' if official_rig else 'official-deterministic-conditioning-rig'\n"
        "    camera_values = [[[1.0, 0.0, 0.0, float(index), 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.8, 0.8, 0.5, 0.5][item] for item in range(16)] for index in range(len(views))] if official_rig else json.loads(pathlib.Path(value('--cameras')).read_text())['cameras']\n"
        "    if instantmesh_fault == 'camera-count': camera_values = camera_values[:-1]\n"
        "    if instantmesh_fault == 'camera-width': camera_values[0] = camera_values[0][:-1]\n"
        "    if instantmesh_fault == 'camera-nonfinite': camera_values[0][0] = 'not-finite'\n"
        "    if instantmesh_fault == 'camera-document-mismatch': camera_values[0][0] += 0.25\n"
        "    ordered = [{'index': index, 'path': source, 'byteCount': pathlib.Path(source).stat().st_size, 'sha256': checksum(pathlib.Path(source)), 'sourceWidth': 32, 'sourceHeight': 24, 'preparedWidth': 320, 'preparedHeight': 320} for index, source in enumerate(views)]\n"
        "    if instantmesh_fault == 'view-order': ordered[0]['path'], ordered[1]['path'] = ordered[1]['path'], ordered[0]['path']\n"
        "    native_input = {'viewCount': len(views), 'userSuppliedViews': True, 'cameraConditioning': camera_conditioning, 'cameras': camera_values, 'orderedViews': ordered}\n"
        "    if instantmesh_fault == 'camera-missing': native_input.pop('cameras')\n"
        "    boundary = {'viewGenerationIncluded': False, 'zero123PlusPlusIncluded': False, 'runtimePython': False, 'proprietaryFlexiCubesIncluded': False}\n"
        "    if instantmesh_fault == 'boundary': boundary['zero123PlusPlusIncluded'] = True\n"
        "    includes_colors = '--no-vertex-colors' not in args\n"
        "    repair_applied = 'yes' if instantmesh_fault == 'repair-type' else True\n"
        "    extraction = {'resolution': int(value('--resolution')), 'includesVertexColors': includes_colors, 'algorithm': 'native-marching-tetrahedra', 'topologyCompatibility': 'learned-field-parity-no-topology-parity-with-upstream-flexicubes', 'upstreamEmptyFieldRepairApplied': repair_applied}\n"
        "    mesh = {'coordinateSystem': 'model-x-right-y-up-z-forward', 'units': 'normalized-object-space', 'inferredUnseenGeometry': True, 'vertexCount': 3, 'triangleCount': 1, 'bounds': bounds}\n"
        "    native_manifest = root / 'instantmesh-asset-run-manifest.json'\n"
        "    native_manifest.write_text(json.dumps({'schemaVersion': 1, 'createdAt': '2026-07-11T00:00:00Z', 'outputDirectory': str(root), 'checkpoint': checkpoint, 'input': native_input, 'boundary': boundary, 'extraction': extraction, 'mesh': mesh, 'artifacts': artifacts}))\n"
        "    source_dimensions = [{'width': item['sourceWidth'], 'height': item['sourceHeight']} for item in ordered]\n"
        "    payload_repair_applied = False if instantmesh_fault == 'repair-mismatch' else repair_applied\n"
        "    payload = {'schemaVersion': 1, 'status': 'failed' if instantmesh_fault == 'status' else 'completed', 'manifestPath': str(root.parent / 'escaped-run.json') if instantmesh_fault == 'path-escape' else str(native_manifest), 'manifestSHA256': '0' * 64 if instantmesh_fault == 'manifest-checksum' else checksum(native_manifest), 'meshManifestPath': str(mesh_manifest), 'meshManifestSHA256': '0' * 64 if instantmesh_fault == 'mesh-manifest-checksum' else checksum(mesh_manifest), 'modelID': checkpoint['modelID'], 'checkpointFormat': checkpoint['format'], 'checkpointSHA256': checkpoint['weightsSHA256'], 'sourceCheckpointSHA256': checkpoint['sourceSHA256'], 'sourceManifestSHA256': checkpoint['sourceManifestSHA256'], 'sourceDimensions': source_dimensions, 'viewCount': len(views), 'userSuppliedViews': True, 'usedOfficialCameraRig': official_rig, 'viewGenerationIncluded': False, 'zero123PlusPlusIncluded': boundary['zero123PlusPlusIncluded'], 'runtimePython': False, 'proprietaryFlexiCubesIncluded': False, 'extractionResolution': extraction['resolution'], 'includesVertexColors': includes_colors, 'meshExtractionAlgorithm': extraction['algorithm'], 'upstreamEmptyFieldRepairApplied': payload_repair_applied, 'topologyMatchesUpstreamFlexiCubes': False, 'coordinateSystem': mesh['coordinateSystem'], 'units': mesh['units'], 'inferredUnseenGeometry': True, 'vertexCount': 3, 'triangleCount': 1, 'bounds': bounds, 'artifacts': artifacts}\n"
        "    print(json.dumps(payload))\n"
        "elif args[:2] == ['image', 'reconstruct-3d']:\n"
        "    root = pathlib.Path(value('--output')).resolve(); root.mkdir(parents=True, exist_ok=True)\n"
        "    source = str(pathlib.Path(args[2]).resolve())\n"
        "    obj = root / 'triposr-asset.obj'; obj.write_text('v 0 0 0 1 0 0\\nv 1 0 0 0 1 0\\nv 0 1 0 0 0 1\\nf 1 2 3\\n')\n"
        "    ply = root / 'triposr-asset.ply'; ply.write_bytes(b'ply-fake-binary-mesh')\n"
        "    glb = root / 'triposr-asset.glb'; glb.write_bytes(b'glTF-fake-indexed-mesh')\n"
        "    mesh_artifacts = [artifact('obj', obj, root, 'model/obj'), artifact('ply', ply, root, 'application/ply'), artifact('glb', glb, root, 'model/gltf-binary')]\n"
        "    bounds = {'minimum': [-0.5, -0.5, -0.5], 'maximum': [0.5, 0.5, 0.5]}\n"
        "    mesh_model = {'modelID': 'image-3d-triposr', 'upstreamRepository': 'stabilityai/TripoSR', 'upstreamRevision': '5b521936b01fbe1890f6f9baed0254ab6351c04a', 'license': 'MIT', 'weightsSHA256': '429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee', 'inferenceBackend': 'mere.run-native-mlx'}\n"
        "    mesh_manifest = root / 'triposr-asset-manifest.json'\n"
        "    mesh_manifest.write_text(json.dumps({'schemaVersion': 1, 'createdAt': '2026-07-11T00:00:00Z', 'inputPaths': [source], 'outputDirectory': str(root), 'model': mesh_model, 'coordinateSystem': 'model-x-right-y-up-z-forward', 'units': 'normalized-object-space', 'inferredUnseenGeometry': True, 'vertexCount': 3, 'triangleCount': 1, 'bounds': bounds, 'artifacts': mesh_artifacts}))\n"
        "    artifacts = mesh_artifacts + [artifact('mesh-manifest', mesh_manifest, root, 'application/json')]\n"
        "    if triposr_fault == 'artifact-checksum': artifacts[0]['sha256'] = '0' * 64\n"
        "    if triposr_fault == 'byte-count': artifacts[0]['byteCount'] += 1\n"
        "    checkpoint = {'modelID': 'image-3d-triposr', 'repository': 'stabilityai/TripoSR', 'revision': '5b521936b01fbe1890f6f9baed0254ab6351c04a', 'sourceRepository': 'VAST-AI-Research/TripoSR', 'sourceRevision': '107cefdc244c39106fa830359024f6a2f1c78871', 'license': 'MIT', 'format': 'pinned-pytorch-state-dict', 'weightsByteCount': 1677246742, 'weightsSHA256': '429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee', 'sourceSHA256': '429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee', 'configurationSHA256': '74ca708ce086bf68e97709ea6b3d91f14717921c04691e84043f0eb8fcc68e62'}\n"
        "    already_framed = '--already-framed' in args; includes_colors = '--no-vertex-colors' not in args\n"
        "    native_input = {'path': source, 'sourceWidth': 32, 'sourceHeight': 24, 'preparedWidth': 512, 'preparedHeight': 512, 'foregroundPolicy': 'already-framed' if already_framed else 'automatic-transparent-alpha', 'foregroundRatio': None if already_framed else float(value('--foreground-ratio')), 'croppedTransparentForeground': False}\n"
        "    extraction = {'resolution': int(value('--resolution')), 'densityThreshold': float(value('--density-threshold')), 'includesVertexColors': includes_colors, 'algorithm': 'native-marching-tetrahedra', 'topologyCompatibility': 'same-sampled-isosurface-not-byte-topology-parity-with-torchmcubes'}\n"
        "    mesh = {'coordinateSystem': 'model-x-right-y-up-z-forward', 'units': 'normalized-object-space', 'inferredUnseenGeometry': True, 'vertexCount': 3, 'triangleCount': 1, 'bounds': bounds}\n"
        "    native_manifest = root / 'triposr-asset-run-manifest.json'\n"
        "    native_manifest.write_text(json.dumps({'schemaVersion': 1, 'createdAt': '2026-07-11T00:00:00Z', 'outputDirectory': str(root), 'checkpoint': checkpoint, 'input': native_input, 'extraction': extraction, 'mesh': mesh, 'artifacts': artifacts}))\n"
        "    payload = {'schemaVersion': 1, 'status': 'failed' if triposr_fault == 'status' else 'completed', 'manifestPath': str(root.parent / 'escaped-run.json') if triposr_fault == 'path-escape' else str(native_manifest), 'manifestSHA256': '0' * 64 if triposr_fault == 'manifest-checksum' else checksum(native_manifest), 'meshManifestPath': str(mesh_manifest), 'meshManifestSHA256': checksum(mesh_manifest), 'modelID': 'image-3d-triposr', 'checkpointSHA256': checkpoint['weightsSHA256'], 'sourceCheckpointSHA256': checkpoint['sourceSHA256'], 'sourceWidth': 32, 'sourceHeight': 24, 'preparedWidth': 512, 'preparedHeight': 512, 'foregroundPolicy': native_input['foregroundPolicy'], 'foregroundRatio': native_input['foregroundRatio'], 'croppedTransparentForeground': False, 'extractionResolution': extraction['resolution'], 'densityThreshold': extraction['densityThreshold'], 'includesVertexColors': includes_colors, 'meshExtractionAlgorithm': extraction['algorithm'], 'coordinateSystem': mesh['coordinateSystem'], 'units': mesh['units'], 'inferredUnseenGeometry': True, 'vertexCount': 3, 'triangleCount': 1, 'bounds': bounds, 'artifacts': artifacts}\n"
        "    print(json.dumps(payload))\n"
        "elif args[:2] == ['video', 'generate']:\n"
        "    pathlib.Path(value('--output')).write_bytes(b'video')\n"
        "elif args[:2] == ['image', 'generate']:\n"
        "    output = pathlib.Path(value('--output'))\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    Image.new('RGB', (32, 24), (80, 100, 140)).save(output)\n"
        "else:\n"
        "    raise SystemExit('unexpected mere.run args: ' + repr(args))\n"
    )


def write_fake_ffmpeg(path: pathlib.Path) -> None:
    path.write_text(
        "import pathlib, sys\n"
        "from PIL import Image\n"
        "output = pathlib.Path(sys.argv[-1])\n"
        "if '%' in output.name:\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    for index in range(1, 3):\n"
        "        target = pathlib.Path(str(output).replace('%06d', f'{index:06d}'))\n"
        "        Image.new('RGB', (32, 24), (20 * index, 40, 80)).save(target)\n"
        "else:\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    output.write_bytes(b'encoded')\n"
    )


class MereVFXToolsTests(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, dict[str, object], str]:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        payload = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return code, payload, stderr.getvalue()

    def test_manifest_and_plan_contract(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue(set(cli.TOOLS).issubset(names))
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            image = root / "mask.png"
            request = root / "request.json"
            write_image(image)
            write_request(request, {"masks": str(image)})
            code, payload, _ = self.invoke([
                "plan", "--tool", "matte-refine", "--request-json", str(request),
                "--output-dir", str(root / "out"), "--run-id", "vfx-plan",
                "--mere-run-command", "fake-mere", "--ffmpeg-command", "fake-ffmpeg",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["tool"]["name"], "matte-refine")
            self.assertTrue((root / "out" / "run.json").is_file())

    def test_matte_refine_key_and_qc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root / "frames"
            write_image(frames / "a.png", (0, 255, 0, 255))
            write_image(frames / "b.png", (250, 250, 250, 20))

            refine_request = root / "refine.json"
            write_request(refine_request, {"masks": str(frames)}, {"growPixels": 1, "chokePixels": 1, "featherRadius": 1.5})
            code, payload, _ = self.invoke([
                "matte-refine", "--request-json", str(refine_request), "--output-dir", str(root / "refined"),
                "--run-id", "refine-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "succeeded")
            self.assertEqual(len(list((root / "refined" / "refined-mattes").glob("*.png"))), 2)

            key_request = root / "key.json"
            write_request(key_request, {"images": str(frames)}, {"threshold": 15, "softness": 80, "despill": 1.0})
            code, payload, _ = self.invoke([
                "key", "--request-json", str(key_request), "--output-dir", str(root / "keyed"),
                "--run-id", "key-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            keyed = Image.open(root / "keyed" / "keyed" / "frame_000001.png").convert("RGBA")
            self.assertEqual(keyed.getpixel((0, 0))[3], 0)
            self.assertEqual(payload["status"], "succeeded")

            qc_request = root / "qc.json"
            write_request(qc_request, {"frames": str(frames)}, {"lumaJumpThreshold": 5, "alphaJumpThreshold": 0.1})
            code, payload, _ = self.invoke([
                "shot-qc", "--request-json", str(qc_request), "--output-dir", str(root / "qc"),
                "--run-id", "qc-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            report = json.loads((root / "qc" / "shot-qc.json").read_text())
            self.assertFalse(report["ok"])
            self.assertGreaterEqual(len(report["issues"]), 1)
            self.assertEqual(payload["status"], "succeeded")

    def test_track_export_writes_all_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            tracking = root / "tracking.json"
            tracking.write_text(json.dumps({
                "fps": 24,
                "frames": [{"frameIndex": 7, "detections": [{"objectID": "hero", "label": "actor", "box": [1, 2, 3, 4], "visible": True}]}],
            }))
            request = root / "request.json"
            write_request(request, {"trackingJson": str(tracking)})
            code, payload, _ = self.invoke([
                "track-export", "--request-json", str(request), "--output-dir", str(root / "export"),
                "--run-id", "track-export-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            self.assertTrue((root / "export" / "tracks.csv").is_file())
            self.assertTrue((root / "export" / "tracks-after-effects.json").is_file())
            self.assertTrue((root / "export" / "tracks-blender.json").is_file())
            self.assertEqual(len(payload["artifacts"]["items"]), 4)

    def test_roto_delivers_mattes_review_tracking_and_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            video = root / "shot.mov"
            video.write_bytes(b"source")
            request = root / "request.json"
            mere = root / "mere.py"
            ffmpeg = root / "ffmpeg.py"
            write_fake_mere_run(mere)
            write_fake_ffmpeg(ffmpeg)
            write_request(request, {"video": str(video)}, {"prompts": ["actor"], "alphaVideo": True, "featherRadius": 0.5})
            code, payload, stderr = self.invoke([
                "roto", "--request-json", str(request), "--output-dir", str(root / "roto"),
                "--run-id", "roto-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", f"{sys.executable} {ffmpeg}",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            self.assertTrue((root / "roto" / "roto-alpha.mov").is_file())
            self.assertEqual(len(list((root / "roto" / "mattes").glob("*.png"))), 2)
            self.assertEqual(payload["vfx"]["alphaFrameIndices"], [0, 1])
            self.assertRegex(payload["artifacts"]["items"][0]["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_native_generation_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            start = root / "start.png"
            end = root / "end.png"
            write_image(start)
            write_image(end, (40, 60, 220, 255))
            mere = root / "mere.py"
            ffmpeg = root / "ffmpeg.py"
            write_fake_mere_run(mere)
            write_fake_ffmpeg(ffmpeg)
            mere_command = f"{sys.executable} {mere}"
            ffmpeg_command = f"{sys.executable} {ffmpeg}"

            request = root / "inbetween.json"
            write_request(request, {"startImage": str(start), "endImage": str(end)}, {"prompt": "actor turns", "numFrames": 17})
            code, payload, stderr = self.invoke([
                "inbetween", "--request-json", str(request), "--output-dir", str(root / "inbetween"),
                "--run-id", "inbetween-test", "--mere-run-command", mere_command, "--ffmpeg-command", ffmpeg_command,
            ])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "inbetween" / "inbetween.mp4").is_file())
            self.assertEqual(payload["status"], "succeeded")

            request = root / "turntable.json"
            write_request(request, {"image": str(start)}, {"prompt": "orbit clockwise"})
            code, payload, stderr = self.invoke([
                "turntable", "--request-json", str(request), "--output-dir", str(root / "turntable"),
                "--run-id", "turntable-test", "--mere-run-command", mere_command, "--ffmpeg-command", ffmpeg_command,
            ])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "turntable" / "turntable-contact-sheet.jpg").is_file())
            self.assertEqual(payload["status"], "succeeded")

            request = root / "character.json"
            write_request(request, {"referenceImage": str(start)}, {"views": ["front", "back"], "lora": "/tmp/hero.safetensors"})
            code, payload, stderr = self.invoke([
                "character-sheet", "--request-json", str(request), "--output-dir", str(root / "character"),
                "--run-id", "character-test", "--mere-run-command", mere_command, "--ffmpeg-command", ffmpeg_command,
            ])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "character" / "character-sheet.jpg").is_file())
            self.assertEqual(len(list((root / "character" / "character-views").glob("*.png"))), 2)
            self.assertEqual(payload["status"], "succeeded")

    def test_pose_sequence_exports_motion_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root / "frames"
            write_image(frames / "frame-1.png")
            write_image(frames / "frame-2.png", (40, 60, 220, 255))
            request = root / "pose.json"
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            write_request(request, {"frames": str(frames)}, {"fps": 12, "minimumConfidence": 0.2})
            code, payload, stderr = self.invoke([
                "pose-sequence", "--request-json", str(request), "--output-dir", str(root / "pose-out"),
                "--run-id", "pose-sequence-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            sequence = json.loads((root / "pose-out" / "pose-sequence.json").read_text())
            self.assertEqual(sequence["fps"], 12)
            self.assertEqual(len(sequence["frames"]), 2)
            after_effects = json.loads((root / "pose-out" / "pose-after-effects.json").read_text())
            self.assertEqual(after_effects["origin"], "top-left")
            self.assertEqual(len(after_effects["layers"]), 2)
            self.assertTrue((root / "pose-out" / "pose-blender.json").is_file())
            self.assertTrue((root / "pose-out" / "pose-sequence.csv").is_file())

    def test_motion_pass_exports_adjacent_native_flow_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root / "frames"
            write_image(frames / "frame-1.png")
            write_image(frames / "frame-2.png", (40, 60, 220, 255))
            write_image(frames / "frame-3.png", (220, 60, 40, 255))
            request = root / "motion.json"
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            write_request(request, {"frames": str(frames)}, {"fps": 12, "accuracy": "very-high"})
            code, payload, stderr = self.invoke([
                "motion-pass", "--request-json", str(request), "--output-dir", str(root / "motion-out"),
                "--run-id", "motion-pass-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            motion = json.loads((root / "motion-out" / "motion-pass.json").read_text())
            self.assertEqual(motion["flowCount"], 2)
            self.assertEqual(motion["accuracy"], "very-high")
            self.assertEqual(len(list((root / "motion-out" / "motion-flow").glob("*.flo"))), 2)
            self.assertRegex(motion["flows"][0]["flowSha256"], r"^sha256:[0-9a-f]{64}$")

    def test_clean_plate_preserves_pixels_outside_mask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            mask = root / "mask.png"
            write_image(source)
            matte = Image.new("L", (32, 24), 0)
            ImageDraw.Draw(matte).rectangle((10, 7, 20, 18), fill=255)
            matte.save(mask)
            request = root / "clean-plate.json"
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            write_request(
                request,
                {"images": str(source), "masks": str(mask)},
                {"featherRadius": 0, "growPixels": 0, "boundingBoxPadding": 0},
            )
            code, payload, stderr = self.invoke([
                "clean-plate", "--request-json", str(request), "--output-dir", str(root / "clean-out"),
                "--run-id", "clean-plate-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "clean-out" / "clean-plate.json").read_text())
            self.assertEqual(delivery["maskMode"], "bounding-box")
            self.assertTrue(delivery["colorMatched"])
            self.assertRegex(delivery["frames"][0]["cleanPlateSha256"], r"^sha256:[0-9a-f]{64}$")
            result = Image.open(root / "clean-out" / "clean-plates" / "frame_000001.png").convert("RGB")
            original = Image.open(source).convert("RGB")
            self.assertEqual(result.getpixel((0, 0)), original.getpixel((0, 0)))
            self.assertNotEqual(result.getpixel((15, 10)), original.getpixel((15, 10)))

    def test_set_extension_preserves_source_and_restore_upscales(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            write_image(source)
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            mere_command = f"{sys.executable} {mere}"

            request = root / "extension.json"
            write_request(request, {"image": str(source)}, {"width": 64, "height": 48, "edgeFeather": 0})
            code, payload, stderr = self.invoke([
                "set-extension", "--request-json", str(request), "--output-dir", str(root / "extension-out"),
                "--run-id", "set-extension-test", "--mere-run-command", mere_command,
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            extended = Image.open(root / "extension-out" / "set-extension.png").convert("RGB")
            original = Image.open(source).convert("RGB")
            self.assertEqual(extended.size, (64, 48))
            self.assertEqual(extended.crop((16, 12, 48, 36)).tobytes(), original.tobytes())

            request = root / "restore.json"
            write_request(request, {"images": str(source)}, {"scale": 2})
            code, payload, stderr = self.invoke([
                "restore", "--request-json", str(request), "--output-dir", str(root / "restore-out"),
                "--run-id", "restore-test", "--mere-run-command", mere_command,
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            with Image.open(root / "restore-out" / "restored" / "frame_000001.png") as restored:
                self.assertEqual(restored.size, (64, 48))
            delivery = json.loads((root / "restore-out" / "restoration.json").read_text())
            self.assertTrue(delivery["synthesizedDetail"])
            self.assertFalse(delivery["identityPreservationGuaranteed"])
            self.assertRegex(delivery["frames"][0]["sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertTrue((root / "restore-out" / "upscale-baseline" / "frame_000001.png").is_file())

    def test_depth_normal_consumes_native_metric_geometry_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            write_image(source)
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            request = root / "depth.json"
            write_request(
                request,
                {"images": str(source)},
                {"resolutionLevel": 4, "maxPoints": 1000, "model": "image-klein-nano"},
            )
            code, payload, stderr = self.invoke([
                "depth-normal", "--request-json", str(request), "--output-dir", str(root / "depth-out"),
                "--run-id", "depth-normal-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "depth-out" / "depth-normal.json").read_text())
            self.assertTrue(delivery["metricDepth"])
            self.assertEqual(delivery["depthUnits"], "meters")
            self.assertEqual(delivery["depthSource"], "mere.run vision geometry")
            self.assertRegex(delivery["frames"][0]["normalSha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertTrue(pathlib.Path(delivery["frames"][0]["depth"]).is_file())
            self.assertTrue(pathlib.Path(delivery["frames"][0]["normal"]).is_file())
            self.assertTrue(pathlib.Path(delivery["frames"][0]["camera"]).is_file())
            self.assertTrue(pathlib.Path(delivery["frames"][0]["pointCloud"]).is_file())
            self.assertEqual(len(delivery["frames"][0]["nativeArtifacts"]), 7)
            self.assertEqual(delivery["frames"][0]["input"]["path"], str(source.resolve()))
            self.assertEqual(delivery["frames"][0]["input"]["sha256"], cli.sha256(source))
            self.assertEqual(delivery["frames"][0]["model"]["weightsSHA256"], cli.MOGE_WEIGHTS_SHA256)
            self.assertIn("vision geometry", stderr)
            self.assertNotIn("--model image-klein-nano", stderr)

    def test_depth_normal_preserves_labeled_provided_depth_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            depth = root / "provided-depth.png"
            write_image(source)
            Image.new("L", (32, 24), 128).save(depth)
            request = root / "depth.json"
            write_request(request, {"images": str(source), "depthImages": str(depth)}, {"normalStrength": 3})
            code, payload, stderr = self.invoke([
                "depth-normal", "--request-json", str(request), "--output-dir", str(root / "depth-out"),
                "--run-id", "depth-normal-provided", "--mere-run-command", "missing-mere",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "depth-out" / "depth-normal.json").read_text())
            self.assertFalse(delivery["metricDepth"])
            self.assertEqual(delivery["depthSource"], "provided grayscale fallback")
            self.assertEqual(delivery["depthUnits"], "normalized-display-values")
            self.assertIsNone(delivery["frames"][0]["camera"])
            normal = Image.open(delivery["frames"][0]["normalPreview"]).convert("RGB")
            self.assertEqual(normal.getpixel((16, 12)), (127, 127, 255))

    def test_relight_exports_diffuse_and_shadow_catcher_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            normal = root / "normal.png"
            mask = root / "mask.png"
            write_image(source)
            Image.new("RGB", (32, 24), (128, 128, 255)).save(normal)
            matte = Image.new("L", (32, 24), 0)
            ImageDraw.Draw(matte).rectangle((8, 5, 23, 20), fill=255)
            matte.save(mask)
            request = root / "relight.json"
            write_request(
                request,
                {"images": str(source), "normalMaps": str(normal), "masks": str(mask)},
                {
                    "lightDirection": [0, 0, 1],
                    "ambient": 0.25,
                    "intensity": 0.75,
                    "shadowOffsetX": 2,
                    "shadowOffsetY": 2,
                    "shadowScaleX": 1.2,
                    "shadowScaleY": 0.25,
                    "shadowBlur": 1,
                },
            )
            code, payload, stderr = self.invoke([
                "relight", "--request-json", str(request), "--output-dir", str(root / "relight-out"),
                "--run-id", "relight-test", "--mere-run-command", "missing-mere",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "relight-out" / "relight.json").read_text())
            self.assertEqual(delivery["normalSource"], "provided normal maps")
            self.assertEqual(delivery["shadowMode"], "projected-matte-proxy")
            self.assertRegex(delivery["frames"][0]["shadowCatcherSha256"], r"^sha256:[0-9a-f]{64}$")
            shadow = Image.open(root / "relight-out" / "shadow-catchers" / "frame_000001.png").convert("RGBA")
            self.assertGreater(shadow.getchannel("A").getextrema()[1], 0)
            self.assertTrue((root / "relight-out" / "shadow-previews" / "frame_000001.png").is_file())

    def test_relight_can_solve_missing_normals_with_native_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            mask = root / "mask.png"
            mere = root / "mere.py"
            write_image(source)
            Image.new("L", (32, 24), 255).save(mask)
            write_fake_mere_run(mere)
            request = root / "relight.json"
            write_request(request, {"images": str(source), "masks": str(mask)}, {"lightDirection": [0, 0, 1]})
            code, payload, stderr = self.invoke([
                "relight", "--request-json", str(request), "--output-dir", str(root / "relight-out"),
                "--run-id", "relight-native-normal", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "relight-out" / "relight.json").read_text())
            self.assertEqual(delivery["normalSource"], "mere.run vision geometry")
            self.assertEqual(delivery["nativeGeometry"][0]["units"], "meters")
            self.assertEqual(delivery["nativeGeometry"][0]["input"]["path"], str(source.resolve()))
            self.assertEqual(delivery["nativeGeometry"][0]["model"]["modelID"], cli.MOGE_MODEL_ID)
            self.assertTrue(pathlib.Path(delivery["frames"][0]["geometryManifest"]).is_file())

    def test_video_depth_records_native_sequence_manifest_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            video = root / "shot.mov"
            mere = root / "mere.py"
            video.write_bytes(b"source-video")
            write_fake_mere_run(mere)
            request = root / "video-depth.json"
            write_request(request, {"video": str(video)}, {"inputSize": 56, "maxFrames": 2})
            code, payload, stderr = self.invoke([
                "video-depth", "--request-json", str(request), "--output-dir", str(root / "video-depth-out"),
                "--run-id", "video-depth-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "video-depth-out" / "video-depth.json").read_text())
            self.assertEqual(delivery["depthSemantics"], "affine-relative")
            self.assertFalse(delivery["metricDepth"])
            self.assertFalse(delivery["hasConfidence"])
            self.assertFalse(delivery["hasCameraIntrinsics"])
            self.assertFalse(delivery["hasPointCloud"])
            self.assertEqual(delivery["frameCount"], 2)
            self.assertEqual(len(delivery["nativeArtifacts"]), 4)
            self.assertEqual(delivery["input"]["path"], str(video.resolve()))
            self.assertEqual(delivery["input"]["byteCount"], video.stat().st_size)
            self.assertEqual(delivery["model"]["modelID"], "vision-depth-vda-small")
            self.assertEqual(delivery["checkpointSHA256"], "sha256:13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609")
            self.assertTrue(pathlib.Path(delivery["nativeManifest"]).is_file())
            self.assertTrue(pathlib.Path(delivery["reviewVideo"]).is_file())

    def test_native_geometry_and_video_depth_reject_provenance_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            video = root / "shot.mov"
            write_image(source)
            video.write_bytes(b"source-video")

            geometry_request = root / "geometry.json"
            write_request(geometry_request, {"images": str(source)})
            faults = (
                ("schema", "schemaVersion"),
                ("input-path", "inputPath"),
                ("input-byte-count", "inputByteCount"),
                ("input-sha", "inputSHA256"),
                ("model-sha", "weightsSHA256"),
            )
            for fault, expected in faults:
                with self.subTest(workflow="geometry", fault=fault):
                    runtime = root / f"mere-geometry-{fault}.py"
                    write_fake_mere_run(runtime, geometry_fault=fault)
                    code, payload, stderr = self.invoke([
                        "depth-normal", "--request-json", str(geometry_request),
                        "--output-dir", str(root / f"geometry-{fault}-out"),
                        "--run-id", f"geometry-{fault}",
                        "--mere-run-command", f"{sys.executable} {runtime}",
                    ])
                    self.assertNotEqual(code, 0)
                    self.assertEqual(payload, {})
                    self.assertIn(expected, stderr)

            vda_request = root / "vda.json"
            write_request(vda_request, {"video": str(video)})
            for fault, expected in faults:
                with self.subTest(workflow="video-depth", fault=fault):
                    runtime = root / f"mere-vda-{fault}.py"
                    write_fake_mere_run(runtime, vda_fault=fault)
                    code, payload, stderr = self.invoke([
                        "video-depth", "--request-json", str(vda_request),
                        "--output-dir", str(root / f"vda-{fault}-out"),
                        "--run-id", f"vda-{fault}",
                        "--mere-run-command", f"{sys.executable} {runtime}",
                    ])
                    self.assertNotEqual(code, 0)
                    self.assertEqual(payload, {})
                    self.assertIn(expected, stderr)

    def test_multiview_geometry_preserves_order_and_honest_3dgs_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            second_by_name = root / "z-view.png"
            first_by_name = root / "a-view.png"
            cameras = root / "cameras.json"
            mere = root / "mere.py"
            write_image(second_by_name)
            write_image(first_by_name, (40, 60, 220, 255))
            cameras.write_text('{"schemaVersion": 1, "cameras": []}')
            write_fake_mere_run(mere)
            request = root / "multiview.json"
            ordered = [str(second_by_name), str(first_by_name)]
            resolved_order = [str(second_by_name.resolve()), str(first_by_name.resolve())]
            write_request(
                request,
                {"images": ordered, "cameras": str(cameras)},
                {
                    "processResolution": 56,
                    "referenceView": "middle",
                    "confidencePercentile": 35.0,
                    "maxPoints": 900,
                },
            )
            code, payload, stderr = self.invoke([
                "multiview-geometry", "--request-json", str(request),
                "--output-dir", str(root / "multiview-out"), "--run-id", "multiview-test",
                "--mere-run-command", f"{sys.executable} {mere}", "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "multiview-out" / "multiview-geometry.json").read_text())
            self.assertEqual(delivery["orderedViews"], resolved_order)
            self.assertEqual(
                [item["sourcePath"] for item in delivery["orderedViewProvenance"]],
                resolved_order,
            )
            for source, provenance in zip((second_by_name, first_by_name), delivery["orderedViewProvenance"]):
                self.assertEqual(provenance["sourceByteCount"], source.stat().st_size)
                self.assertEqual(provenance["sourceSHA256"], cli.sha256(source))
            self.assertEqual(delivery["checkpoint"]["modelID"], "vision-geometry-da3-small")
            self.assertEqual(delivery["processResolution"], 56)
            self.assertEqual(delivery["referenceViewStrategy"], "middle")
            self.assertEqual(delivery["confidencePercentile"], 35.0)
            self.assertEqual(delivery["maximumPointCount"], 900)
            self.assertEqual(delivery["depthUnits"], "relative")
            self.assertFalse(delivery["metricGeometry"])
            self.assertFalse(delivery["meshProduced"])
            self.assertFalse(delivery["containsGaussianParameters"])
            self.assertTrue(delivery["poseConditioned"])
            self.assertEqual(delivery["pointCloudRepresentation"], "colored-points-not-mesh")
            self.assertTrue(pathlib.Path(delivery["pointCloudPLY"]).is_file())
            self.assertTrue(pathlib.Path(delivery["pointCloudGLB"]).is_file())
            self.assertTrue(pathlib.Path(delivery["cameras"]).is_file())
            self.assertTrue(pathlib.Path(delivery["transforms"]).is_file())

    def test_multiview_geometry_rejects_schema_provenance_control_and_checkpoint_faults(self) -> None:
        cases = (
            ("schema-version", "schemaVersion must be 2"),
            ("source-path", "changed the requested view order or source path"),
            ("source-byte-count", "source byte count mismatch"),
            ("source-sha", "source checksum mismatch"),
            ("process-resolution", "changed the requested processResolution"),
            ("reference-view", "changed the requested referenceViewStrategy"),
            ("confidence-percentile", "changed the requested confidencePercentile"),
            ("max-points", "changed the requested maximumPointCount"),
            ("checkpoint-model", "invalid modelID"),
            ("checkpoint-revision", "invalid revision"),
            ("checkpoint-config-sha", "configurationSHA256 must contain exactly 64 hexadecimal digits"),
            ("checkpoint-weights-sha", "weightsSHA256 must contain exactly 64 hexadecimal digits"),
        )
        for fault, expected in cases:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                views = [root / "front.png", root / "back.png"]
                for path in views:
                    write_image(path)
                request = root / "multiview.json"
                write_request(
                    request,
                    {"images": [str(path) for path in views]},
                    {
                        "processResolution": 56,
                        "referenceView": "middle",
                        "confidencePercentile": 35.0,
                        "maxPoints": 900,
                    },
                )
                mere = root / "mere.py"
                write_fake_mere_run(mere, da3_fault=fault)
                code, payload, stderr = self.invoke([
                    "multiview-geometry", "--request-json", str(request),
                    "--output-dir", str(root / "multiview-out"),
                    "--run-id", f"multiview-{fault}",
                    "--mere-run-command", f"{sys.executable} {mere}",
                    "--ffmpeg-command", "missing-ffmpeg",
                ])
                self.assertEqual(code, 1)
                self.assertEqual(payload, {})
                self.assertIn(expected, stderr)

    def test_image_to_3d_defaults_to_native_triposr_and_validates_mesh_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            request = root / "geometry.json"
            mere = root / "mere.py"
            write_image(source)
            write_fake_mere_run(mere)
            write_request(request, {"images": str(source)}, {"resolution": 128})
            code, payload, stderr = self.invoke([
                "image-to-3d", "--request-json", str(request), "--output-dir", str(root / "geometry-out"),
                "--run-id", "image-to-3d-native", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "geometry-out" / "image-to-3d.json").read_text())
            self.assertEqual(delivery["schemaVersion"], "mere.run/vfx-image-to-3d.v2")
            self.assertEqual(delivery["reconstructionMode"], "native-triposr")
            self.assertTrue(delivery["nativeInference"])
            self.assertEqual(delivery["modelID"], "image-3d-triposr")
            self.assertFalse(delivery["metricGeometry"])
            self.assertTrue(delivery["inferredUnseenGeometry"])
            self.assertEqual(delivery["units"], "normalized-object-space")
            self.assertEqual(set(delivery["assets"]), {"obj", "ply", "glb"})
            for asset in delivery["assets"].values():
                self.assertTrue(pathlib.Path(asset["path"]).is_file())
                self.assertTrue(asset["sha256"].startswith("sha256:"))
            self.assertTrue(pathlib.Path(delivery["nativeManifest"]).is_file())
            self.assertTrue(pathlib.Path(delivery["meshManifest"]).is_file())

    def test_image_to_3d_supplied_depth_fallback_is_explicit_and_honest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            depth = root / "depth.png"
            write_image(source)
            Image.new("L", (32, 24), 128).save(depth)
            request = root / "geometry.json"
            write_request(
                request,
                {"images": str(source), "depthImages": str(depth)},
                {"reconstructionMode": "supplied-depth-2.5d", "stride": 8},
            )
            code, payload, stderr = self.invoke([
                "image-to-3d", "--request-json", str(request), "--output-dir", str(root / "geometry-out"),
                "--run-id", "image-to-3d-test", "--mere-run-command", "missing-mere",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "geometry-out" / "image-to-3d.json").read_text())
            self.assertFalse(delivery["metricGeometry"])
            self.assertFalse(delivery["nativeInference"])
            self.assertEqual(delivery["geometryMode"], "supplied-depth-2.5d-fallback")
            self.assertIn("not native object reconstruction", delivery["fallbackDisclosure"])
            self.assertEqual(delivery["frames"][0]["vertexCount"], 12)
            self.assertEqual(delivery["frames"][0]["faceCount"], 12)
            self.assertTrue((root / "geometry-out" / "geometry" / "frame_000001.ply").is_file())
            self.assertTrue((root / "geometry-out" / "geometry" / "frame_000001.obj").is_file())

    def test_image_to_3d_rejects_implicit_depth_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            depth = root / "depth.png"
            request = root / "geometry.json"
            write_image(source)
            Image.new("L", (32, 24), 128).save(depth)
            write_request(request, {"images": str(source), "depthImages": str(depth)})
            code, payload, stderr = self.invoke([
                "image-to-3d", "--request-json", str(request), "--output-dir", str(root / "geometry-out"),
                "--run-id", "image-to-3d-implicit-depth", "--mere-run-command", "missing-mere",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(payload, {})
            self.assertIn("supplied-depth-2.5d", stderr)

    def test_image_to_3d_rejects_native_status_paths_and_integrity_faults(self) -> None:
        for fault, expected in (
            ("status", "did not report completed status"),
            ("path-escape", "escapes native output directory"),
            ("manifest-checksum", "manifest checksum mismatch"),
            ("artifact-checksum", "artifact checksum mismatch"),
            ("byte-count", "artifact byte count mismatch"),
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                source = root / "source.png"
                request = root / "geometry.json"
                mere = root / "mere.py"
                write_image(source)
                write_fake_mere_run(mere, fault)
                write_request(request, {"images": str(source)}, {"resolution": 64})
                code, payload, stderr = self.invoke([
                    "image-to-3d", "--request-json", str(request),
                    "--output-dir", str(root / "geometry-out"),
                    "--run-id", f"image-to-3d-{fault}",
                    "--mere-run-command", f"{sys.executable} {mere}",
                    "--ffmpeg-command", "missing-ffmpeg",
                ])
                self.assertEqual(code, 1)
                self.assertEqual(payload, {})
                self.assertIn(expected, stderr)

    def test_multiview_image_to_3d_validates_instantmesh_handoff_and_camera_rig(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            views = [root / name for name in ("z-front.png", "a-left.png", "m-back.png", "b-right.png")]
            for index, path in enumerate(views):
                write_image(path, (20 + index, 80, 180, 255))
            cameras = root / "cameras.json"
            cameras.write_text(json.dumps({
                "schemaVersion": 1,
                "cameras": [
                    [1.0, 0.0, 0.0, float(index), 0.0, 1.0, 0.0, 0.0,
                     0.0, 0.0, 1.0, 0.0, 0.8, 0.8, 0.5, 0.5]
                    for index in range(4)
                ],
            }))
            request = root / "instantmesh.json"
            converted = root / "converted-instantmesh"
            converted.mkdir()
            write_request(
                request,
                {"images": [str(path) for path in views], "cameras": str(cameras)},
                {"model": str(converted), "resolution": 96, "noVertexColors": True},
            )
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            code, payload, stderr = self.invoke([
                "multiview-image-to-3d", "--request-json", str(request),
                "--output-dir", str(root / "instantmesh-out"),
                "--run-id", "instantmesh-camera-rig",
                "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "instantmesh-out" / "multiview-image-to-3d.json").read_text())
            self.assertEqual(delivery["schemaVersion"], "mere.run/vfx-multiview-image-to-3d.v1")
            self.assertEqual(delivery["orderedViews"], [str(path.resolve()) for path in views])
            self.assertEqual(delivery["modelID"], "image-3d-instantmesh-base")
            self.assertEqual(delivery["viewCount"], 4)
            self.assertTrue(delivery["userSuppliedViews"])
            self.assertFalse(delivery["viewGenerationIncluded"])
            self.assertFalse(delivery["zero123PlusPlusIncluded"])
            self.assertFalse(delivery["runtimePython"])
            self.assertFalse(delivery["proprietaryFlexiCubesIncluded"])
            self.assertFalse(delivery["topologyMatchesUpstreamFlexiCubes"])
            self.assertEqual(delivery["cameraRig"], "supplied-c2w-intrinsics")
            self.assertFalse(delivery["usedOfficialCameraRig"])
            self.assertEqual(delivery["suppliedCameraDocument"], str(cameras.resolve()))
            self.assertTrue(delivery["suppliedCameraDocumentSha256"].startswith("sha256:"))
            self.assertEqual(delivery["units"], "normalized-object-space")
            self.assertFalse(delivery["metricGeometry"])
            self.assertEqual(delivery["extraction"]["resolution"], 96)
            self.assertFalse(delivery["extraction"]["includesVertexColors"])
            self.assertTrue(delivery["extraction"]["upstreamEmptyFieldRepairApplied"])
            self.assertTrue(delivery["upstreamEmptyFieldRepairApplied"])
            self.assertEqual(
                delivery["extraction"]["topologyCompatibility"],
                "learned-field-parity-no-topology-parity-with-upstream-flexicubes",
            )
            self.assertEqual(set(delivery["assets"]), {"obj", "ply", "glb"})
            for asset in delivery["assets"].values():
                self.assertTrue(pathlib.Path(asset["path"]).is_file())
                self.assertTrue(asset["sha256"].startswith("sha256:"))
            self.assertIn(f"--model {converted}", stderr)
            self.assertIn(f"--cameras {cameras.resolve()}", stderr)
            self.assertIn("--no-vertex-colors", stderr)
            positions = [stderr.index(f"--view {path.resolve()}") for path in views]
            self.assertEqual(positions, sorted(positions))

    def test_multiview_image_to_3d_accepts_six_explicit_views_with_official_rig(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            views = [root / f"view-{index}.png" for index in range(6)]
            for index, path in enumerate(views):
                write_image(path, (40, 40 + index, 180, 255))
            request = root / "instantmesh.json"
            write_request(
                request,
                {"images": [str(path) for path in views]},
                {"model": "image-3d-instantmesh-base"},
            )
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            code, payload, stderr = self.invoke([
                "multiview-image-to-3d", "--request-json", str(request),
                "--output-dir", str(root / "instantmesh-out"),
                "--run-id", "instantmesh-six-views",
                "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "instantmesh-out" / "multiview-image-to-3d.json").read_text())
            self.assertEqual(delivery["viewCount"], 6)
            self.assertEqual(delivery["cameraRig"], "official-deterministic-conditioning-rig")
            self.assertTrue(delivery["usedOfficialCameraRig"])
            self.assertIsNone(delivery["suppliedCameraDocument"])
            self.assertTrue(delivery["upstreamEmptyFieldRepairApplied"])
            self.assertIn("--model image-3d-instantmesh-base", stderr)

    def test_multiview_image_to_3d_rejects_generated_or_ambiguous_views_and_bad_cameras(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            views = [root / f"view-{index}.png" for index in range(6)]
            for path in views:
                write_image(path)
            mere = root / "mere.py"
            write_fake_mere_run(mere)

            cases: list[tuple[str, dict[str, object], dict[str, object], str]] = [
                (
                    "three-views",
                    {"images": [str(path) for path in views[:3]]},
                    {},
                    "exactly 4 or 6",
                ),
                (
                    "single-image",
                    {"image": str(views[0])},
                    {},
                    "never generates views",
                ),
                (
                    "directory-order",
                    {"images": str(root)},
                    {},
                    "explicitly ordered path array",
                ),
                (
                    "view-generation",
                    {"images": [str(path) for path in views[:4]]},
                    {"generateViews": True},
                    "reconstruction-only",
                ),
            ]
            bad_cameras = root / "invalid-camera-rig.json"
            bad_cameras.write_text(json.dumps({"schemaVersion": 1, "cameras": [[1.0] * 16] * 3}))
            cases.append((
                "bad-cameras",
                {"images": [str(path) for path in views[:4]], "cameras": str(bad_cameras)},
                {},
                "exactly 4 cameras",
            ))
            for name, inputs, options, expected in cases:
                with self.subTest(name=name):
                    request = root / f"{name}.json"
                    write_request(request, inputs, options)
                    code, payload, stderr = self.invoke([
                        "multiview-image-to-3d", "--request-json", str(request),
                        "--output-dir", str(root / f"out-{name}"),
                        "--run-id", f"instantmesh-{name}",
                        "--mere-run-command", f"{sys.executable} {mere}",
                        "--ffmpeg-command", "missing-ffmpeg",
                    ])
                    self.assertEqual(code, 2)
                    self.assertEqual(payload, {})
                    self.assertIn(expected, stderr)

    def test_multiview_image_to_3d_rejects_runtime_security_and_integrity_faults(self) -> None:
        for fault, expected in (
            ("status", "did not report completed status"),
            ("path-escape", "escapes native output directory"),
            ("manifest-checksum", "manifest checksum mismatch"),
            ("artifact-checksum", "artifact checksum mismatch"),
            ("byte-count", "artifact byte count mismatch"),
            ("mesh-manifest-checksum", "mesh manifest checksum mismatch"),
            ("view-order", "changed the requested view order"),
            ("camera-rig", "camera rig does not match the request"),
            ("camera-missing", "input cameras must be a JSON array"),
            ("camera-count", "input cameras must contain exactly 4 cameras"),
            ("camera-width", "input cameras camera 0 must contain 16 values"),
            ("camera-nonfinite", "input cameras camera 0 must contain only finite numbers"),
            ("camera-document-mismatch", "do not exactly match the supplied camera document"),
            ("boundary", "zero123PlusPlusIncluded=false"),
            ("repair-type", "upstreamEmptyFieldRepairApplied must be a boolean"),
            ("repair-mismatch", "disagree on upstreamEmptyFieldRepairApplied"),
            ("mesh-provenance", "unexpected model inferenceBackend"),
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                views = [root / f"view-{index}.png" for index in range(4)]
                for path in views:
                    write_image(path)
                request = root / "instantmesh.json"
                inputs: dict[str, object] = {"images": [str(path) for path in views]}
                if fault == "camera-document-mismatch":
                    cameras = root / "cameras.json"
                    cameras.write_text(json.dumps({
                        "schemaVersion": 1,
                        "cameras": [[1.0] * 16 for _ in views],
                    }))
                    inputs["cameras"] = str(cameras)
                write_request(request, inputs, {"resolution": 64})
                mere = root / "mere.py"
                write_fake_mere_run(mere, instantmesh_fault=fault)
                code, payload, stderr = self.invoke([
                    "multiview-image-to-3d", "--request-json", str(request),
                    "--output-dir", str(root / "instantmesh-out"),
                    "--run-id", f"instantmesh-{fault}",
                    "--mere-run-command", f"{sys.executable} {mere}",
                    "--ffmpeg-command", "missing-ffmpeg",
                ])
                self.assertEqual(code, 1)
                self.assertEqual(payload, {})
                self.assertIn(expected, stderr)

    def test_resume_cleanup_dry_run_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            image = root / "mask.png"
            request = root / "request.json"
            write_image(image)
            write_request(request, {"masks": str(image)})
            common = [
                "--request-json", str(request), "--output-dir", str(root / "out"), "--run-id", "lifecycle-test",
                "--mere-run-command", "missing-mere", "--ffmpeg-command", "missing-ffmpeg",
            ]
            code, payload, _ = self.invoke(["matte-refine", *common, "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            manifest = root / "out" / "run.json"
            code, payload, _ = self.invoke(["resume", str(manifest)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            code, payload, _ = self.invoke(["cleanup", str(manifest)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["cleanup"]["status"], "skipped")
            code, payload, _ = self.invoke(["doctor", "--mere-run-command", "missing-mere", "--ffmpeg-command", "missing-ffmpeg"])
            self.assertEqual(code, 3)
            self.assertFalse(payload["ok"])
            code, _, stderr = self.invoke([
                "plan", "--tool", "matte-refine", "--request-json", str(request), "--output-dir", str(root / "bad"),
                "--run-id", "bad id", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 2)
            self.assertIn("invalid --run-id", stderr)


if __name__ == "__main__":
    unittest.main()
