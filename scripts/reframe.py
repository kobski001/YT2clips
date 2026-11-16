#!/usr/bin/env python3
"""
Find where to crop when changing aspect ratio (e.g. 16:9 -> 9:16).

Samples frames, detects faces with OpenCV (optional dependency), and produces a list of
crop positions over time. Position changes are held for a minimum time and applied as
clean cuts (like a camera switch), not wobbly pans. Without OpenCV, or when no faces are
found, it falls back to the centre (or a fixed crop_x you pass).

Usage (debug):  python reframe.py <video> <start_s> <end_s> [9:16]
"""

import statistics
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import cv2  # opencv-python-headless
except ImportError:  # pragma: no cover
    cv2 = None


YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def _yunet_model() -> Optional[str]:
    """Download OpenCV's YuNet face model (~230 KB) once into <skill>/models/."""
    path = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
    if path.exists() and path.stat().st_size > 100_000:
        return str(path)
    try:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        print("  downloading YuNet face model (one time, 230 KB)...")
        urllib.request.urlretrieve(YUNET_URL, str(path) + ".part")
        Path(str(path) + ".part").replace(path)
        return str(path)
    except Exception as e:
        print(f"  could not download face model ({e})")
        return None


def make_face_detector():
    """Return detect(bgr_frame) -> [(center_x 0..1, area_px)], or None if unavailable."""
    if hasattr(cv2, "FaceDetectorYN"):  # OpenCV 4.5.4+ / 5.x: DNN detector, handles profiles
        model = _yunet_model()
        if model:
            det = cv2.FaceDetectorYN.create(model, "", (320, 320), 0.7, 0.3, 50)

            def detect_yunet(frame):
                h, w = frame.shape[:2]
                det.setInputSize((w, h))
                _, faces = det.detect(frame)
                if faces is None:
                    return []
                return [((f[0] + f[2] / 2) / w, f[2] * f[3]) for f in faces]
            return detect_yunet

    if hasattr(cv2, "CascadeClassifier"):  # older OpenCV: Haar cascades
        base = cv2.data.haarcascades
        frontal = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        profile = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")

        def detect_haar(frame):
            gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            min_size = (int(gray.shape[0] * 0.08),) * 2
            faces = list(frontal.detectMultiScale(gray, 1.1, 6, minSize=min_size)) or \
                list(profile.detectMultiScale(gray, 1.1, 6, minSize=min_size))
            return [((x + fw / 2) / gray.shape[1], fw * fh) for x, y, fw, fh in faces]
        return detect_haar
    return None


def sample_face_positions(video: str, start: float, end: float, fps: float = 2.0) -> List[Tuple[float, Optional[float]]]:
    """[(t_relative, face_center_x as 0..1 or None), ...]"""
    detect = make_face_detector()
    cap = cv2.VideoCapture(video)
    if detect is None or not cap.isOpened():
        return []
    samples, t = [], 0.0
    duration = end - start
    while t <= duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        if w > 640:
            frame = cv2.resize(frame, (640, int(h * 640 / w)))
        samples.append((t, detect(frame)))
        t += 1.0 / fps
    cap.release()

    # Stick with the current subject while it is visible; otherwise take the largest face.
    track, current = [], None
    for t, faces in samples:
        if not faces:
            track.append((t, None))
            continue
        near = [f for f in faces if current is not None and abs(f[0] - current) < 0.12]
        pick = max(near or faces, key=lambda f: f[1])
        current = pick[0]
        track.append((t, current))
    return track


def plan_crop(track, crop_frac: float, min_hold: float = 1.5, move_thresh: float = 0.08) -> List[Tuple[float, float]]:
    """
    Convert face track -> [(t_start, x_left_fraction)] segments.
    crop_frac = crop width / source width. x is the left edge as a fraction of source width.
    """
    def to_left(cx):
        return min(max(cx - crop_frac / 2, 0.0), 1.0 - crop_frac)

    known = [(t, cx) for t, cx in track if cx is not None]
    if not known:
        return [(0.0, to_left(0.5))]

    # Fill gaps with the last known position; median-smooth to kill detector noise
    filled, last = [], known[0][1]
    for t, cx in track:
        last = cx if cx is not None else last
        filled.append((t, last))
    xs = [cx for _, cx in filled]
    smooth = [statistics.median(xs[max(0, i - 2): i + 3]) for i in range(len(xs))]

    segments = [(0.0, to_left(smooth[0]))]
    pending_since = None
    for (t, _), cx in zip(filled, smooth):
        target = to_left(cx)
        if abs(target - segments[-1][1]) < move_thresh:
            pending_since = None
            continue
        if pending_since is None:
            pending_since = t
        elif t - pending_since >= min_hold * 0.5 and t - segments[-1][0] >= min_hold:
            segments.append((pending_since, target))
            pending_since = None
    return segments


def crop_x_expression(segments, src_w: int, crop_w: int) -> str:
    """ffmpeg crop 'x' expression (pixels) switching at the segment times."""
    px = [(t, int(round(min(x * src_w, src_w - crop_w)))) for t, x in segments]
    expr = str(px[-1][1])
    for (t_next, _), (_, x) in reversed(list(zip(px[1:], px[:-1]))):
        expr = f"if(lt(t,{t_next:.2f}),{x},{expr})"
    return expr


def auto_crop_segments(video: str, start: float, end: float, crop_frac: float):
    """Returns (segments, method) where method is 'faces' or 'center'."""
    if cv2 is None:
        return [(0.0, (1 - crop_frac) / 2)], "center (install opencv-python-headless for face tracking)"
    track = sample_face_positions(video, start, end)
    if not any(cx is not None for _, cx in track):
        return [(0.0, (1 - crop_frac) / 2)], "center (no faces found)"
    segs = plan_crop(track, crop_frac)
    return segs, f"faces ({len(segs)} position{'s' if len(segs) > 1 else ''})"


if __name__ == "__main__":
    video, s, e = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    aspect = sys.argv[4] if len(sys.argv) > 4 else "9:16"
    sys.path.insert(0, __file__.rsplit("reframe.py", 1)[0])
    from utils import probe_video
    info = probe_video(video)
    a, b = (int(x) for x in aspect.split(":"))
    crop_w = info["height"] * a / b
    segs, method = auto_crop_segments(video, s, e, crop_w / info["width"])
    print(method)
    for t, x in segs:
        print(f"  t={t:6.1f}s  x={x:.3f}")
