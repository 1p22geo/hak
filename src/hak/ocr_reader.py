from __future__ import annotations

import os
import json
import re
import cv2
import numpy as np
import asyncio
from typing import Optional, Tuple, Dict, Any

try:
    import mss
except ImportError:
    mss = None

try:
    import winocr
except ImportError:
    winocr = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from winrt.windows.media.ocr import OcrEngine
except ImportError:
    OcrEngine = None


DEFAULT_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "roi_config.json")
)


class ScreenReader:
    """
    Geometry Dash OCR Screen Reader.
    Captures screen and performs OCR for:
    1. Percentage (float 0.0 - 100.0)
    2. Attempt count (int)
    3. In-game Time (float seconds)
    4. Tap/Jump count (int)
    """

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        monitor_index: int = 1,
        language: Optional[str] = None,
        mock_mode: bool = False,
    ):
        self.config_path = config_path
        self.monitor_index = monitor_index
        self.mock_mode = mock_mode
        self.sct = mss.MSS() if (mss and not mock_mode) else None
        self.language = language or self._detect_best_language()
        self.rois: Dict[str, Tuple[int, int, int, int]] = self.load_rois()

    def _detect_best_language(self) -> str:
        if not winocr or OcrEngine is None:
            return "en"
        try:
            available = [x.language_tag for x in OcrEngine.available_recognizer_languages]
            if "en" in available or "en-US" in available or "en-GB" in available:
                return "en"
            if "pl" in available or "pl-PL" in available:
                return "pl"
            return available[0] if available else "en"
        except Exception:
            return "en"

    def get_default_rois(self) -> Dict[str, Tuple[int, int, int, int]]:
        """Standard calibrated ROIs for Geometry Dash HUD."""
        return {
            "percentage": (1311, 4, 119, 50),
            "attempt_count": (113, 91, 76, 28),
            "time": (80, 60, 92, 31),
            "tap_count": (75, 117, 56, 30),
        }

    def load_rois(self) -> Dict[str, Tuple[int, int, int, int]]:
        """Load ROI coordinates from JSON file or create defaults."""
        defaults = self.get_default_rois()
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                rois = {}
                for k in ["percentage", "attempt_count", "time", "tap_count"]:
                    if k in data and len(data[k]) == 4:
                        rois[k] = tuple(int(x) for x in data[k])
                    else:
                        rois[k] = defaults[k]
                return rois
            except Exception:
                return defaults
        return defaults

    def save_rois(self, rois: Dict[str, Tuple[int, int, int, int]]) -> None:
        """Persist ROI coordinates to config file."""
        self.rois = rois
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({k: list(v) for k, v in rois.items()}, f, indent=2)
        except Exception as exc:
            print(f"[ScreenReader] Warning: Failed to save ROIs: {exc}")

    def capture_screen(self) -> np.ndarray:
        """Capture current screen into a BGR numpy array with safe fallback."""
        if self.mock_mode or not self.sct:
            return self.generate_mock_frame(
                percentage=0.0, attempt=1, elapsed=0.0, taps=0
            )

        try:
            monitor = self.sct.monitors[self.monitor_index]
            screenshot = self.sct.grab(monitor)
            frame = np.array(screenshot)
            bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            self._last_captured_frame = bgr
            return bgr
        except Exception:
            if hasattr(self, "_last_captured_frame") and self._last_captured_frame is not None:
                return self._last_captured_frame
            return self.generate_mock_frame(percentage=0.0, attempt=1, elapsed=0.0, taps=0)

    def crop_roi(self, frame: np.ndarray, roi_name: str) -> np.ndarray:
        """Safely crop the specified ROI from the frame."""
        x, y, w, h = self.rois.get(roi_name, (0, 0, 100, 50))
        h_max, w_max = frame.shape[:2]
        x1 = max(0, min(x, w_max - 1))
        y1 = max(0, min(y, h_max - 1))
        x2 = max(x1 + 1, min(x + w, w_max))
        y2 = max(y1 + 1, min(y + h, h_max))
        return frame[y1:y2, x1:x2]

    def preprocess_for_ocr(
        self, roi: np.ndarray, scale: float = 2.5, thresh_val: int = 140
    ) -> np.ndarray:
        """Upscale, convert to grayscale, and binary threshold for crisp OCR."""
        if scale != 1.0:
            roi_scaled = cv2.resize(
                roi, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )
        else:
            roi_scaled = roi

        gray = cv2.cvtColor(roi_scaled, cv2.COLOR_BGR2GRAY)
        _, binarized = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        return binarized

    def ocr_raw_text(self, image_np: np.ndarray) -> str:
        """Perform Windows OCR on image numpy array."""
        if not winocr or OcrEngine is None or Image is None:
            return ""

        pil_img = Image.fromarray(image_np)
        try:
            result = winocr.recognize_pil(pil_img, self.language)
        except TypeError:
            result = winocr.recognize_pil(pil_img)

        if hasattr(result, "get"):
            result = result.get()
        elif hasattr(result, "__await__") and not asyncio.iscoroutine(result):
            result = asyncio.run(result)
        elif asyncio.iscoroutine(result):
            result = asyncio.run(result)

        text = " ".join([line.text for line in result.lines]).strip()
        return text

    def read_percentage(self, frame: np.ndarray) -> Optional[float]:
        """Extract level percentage (0.0 to 100.0)."""
        crop = self.crop_roi(frame, "percentage")
        processed = self.preprocess_for_ocr(crop)
        raw = self.ocr_raw_text(processed)
        # Match percentage pattern e.g. 73.49% or 73.490/0 or 15%
        match = re.search(r"[-+]?\d*[.,]\d+|\d+", raw)
        if match:
            token = match.group(0).replace(",", ".")
            try:
                val = float(token)
                if 0.0 <= val <= 100.0:
                    return round(val, 2)
            except ValueError:
                return None
        return None

    def read_attempt(self, frame: np.ndarray) -> Optional[int]:
        """Extract attempt counter (e.g. Attempt 152 -> 152)."""
        crop = self.crop_roi(frame, "attempt_count")
        processed = self.preprocess_for_ocr(crop)
        raw = self.ocr_raw_text(processed)
        match = re.search(r"\d+", raw)
        if match:
            try:
                return int(match.group(0))
            except ValueError:
                return None
        return None

    def _parse_time_string(self, raw: str) -> Optional[float]:
        """Helper to parse float seconds or MM:SS from raw string."""
        if not raw:
            return None
        # Check MM:SS format e.g. 01:23.4
        time_match = re.search(r"(\d+):(\d+[.,]?\d*)", raw)
        if time_match:
            mins = float(time_match.group(1))
            secs = float(time_match.group(2).replace(",", "."))
            return round(mins * 60.0 + secs, 2)

        match = re.search(r"[-+]?\d*[.,]\d+|\d+", raw)
        if match:
            token = match.group(0).replace(",", ".")
            try:
                val = float(token)
                if 0.0 <= val <= 300.0:
                    return round(val, 2)
            except ValueError:
                return None
        return None

    def read_time(self, frame: np.ndarray) -> Optional[float]:
        """
        Extract in-game time in seconds.
        Tries standard threshold, Otsu, and inverted Otsu for font color robustness.
        """
        crop = self.crop_roi(frame, "time")
        # 1. Standard threshold
        processed1 = self.preprocess_for_ocr(crop)
        raw1 = self.ocr_raw_text(processed1)
        val1 = self._parse_time_string(raw1)
        if val1 is not None:
            return val1

        # 2. Otsu auto-threshold (robust for fluctuating background colors)
        roi_scaled = cv2.resize(crop, (0, 0), fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(roi_scaled, cv2.COLOR_BGR2GRAY)
        _, processed2 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        raw2 = self.ocr_raw_text(processed2)
        val2 = self._parse_time_string(raw2)
        if val2 is not None:
            return val2

        # 3. Inverted Otsu (if text is dark on light background)
        _, processed3 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        raw3 = self.ocr_raw_text(processed3)
        return self._parse_time_string(raw3)


    def read_tap_count(self, frame: np.ndarray) -> Optional[int]:
        """Extract tap / jump count."""
        crop = self.crop_roi(frame, "tap_count")
        processed = self.preprocess_for_ocr(crop)
        raw = self.ocr_raw_text(processed)
        match = re.search(r"\d+", raw)
        if match:
            try:
                return int(match.group(0))
            except ValueError:
                return None
        return None

    def read_all(self, frame: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """Capture frame and read all 4 metrics."""
        if frame is None:
            frame = self.capture_screen()
        return {
            "percentage": self.read_percentage(frame),
            "attempt": self.read_attempt(frame),
            "time": self.read_time(frame),
            "tap_count": self.read_tap_count(frame),
        }

    def generate_annotated_frame(
        self,
        frame: Optional[np.ndarray] = None,
        telemetry_info: Optional[Dict[str, Any]] = None,
        max_width: int = 640,
    ) -> bytes:
        """
        Draw ROI rectangles and telemetry onto the frame and return JPEG bytes.
        """
        if frame is None:
            frame = self.capture_screen()

        draw_frame = frame.copy()
        info = telemetry_info or {}

        colors = {
            "percentage": (0, 242, 254),    # Cyan
            "attempt_count": (0, 165, 255),  # Orange
            "time": (255, 200, 0),          # Sky Blue
            "tap_count": (255, 100, 255),   # Magenta
        }

        labels = {
            "percentage": f"PCT: {info.get('percentage', '--')}%",
            "attempt_count": f"ATTEMPT: {info.get('attempt', '--')}",
            "time": f"TIME: {info.get('time', '--')}s",
            "tap_count": f"TAPS: {info.get('tap_count', '--')}",
        }

        h_img, w_img = draw_frame.shape[:2]
        for name, (x, y, w, h) in self.rois.items():
            color = colors.get(name, (0, 255, 0))
            label = labels.get(name, name)
            cv2.rectangle(draw_frame, (x, y), (x + w, y + h), color, 2)
            cv2.rectangle(draw_frame, (x, max(0, y - 20)), (x + w, y), color, -1)
            cv2.putText(
                draw_frame,
                label,
                (x + 4, max(14, y - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        # Scale down for efficient web delivery
        if w_img > max_width:
            scale = max_width / float(w_img)
            draw_frame = cv2.resize(
                draw_frame, (max_width, int(h_img * scale)), interpolation=cv2.INTER_AREA
            )

        ret, buffer = cv2.imencode(".jpg", draw_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if ret:
            return buffer.tobytes()
        return b""

    @staticmethod
    def generate_mock_frame(
        percentage: float = 0.0,
        attempt: int = 1,
        elapsed: float = 0.0,
        taps: int = 0,
        w: int = 1280,
        h: int = 720,
    ) -> np.ndarray:
        """Create a synthetic Geometry Dash screenshot for testing / fallback."""
        screen = np.full((h, w, 3), (35, 20, 20), dtype=np.uint8)

        # Draw HUD elements in synthetic positions
        cv2.putText(
            screen,
            f"{percentage:.2f}%",
            (int(w * 0.45), 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            screen,
            f"Attempt {attempt}",
            (int(w * 0.40), 360),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            screen,
            f"Time {elapsed:.1f}s",
            (40, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (200, 255, 200),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            screen,
            f"Jumps {taps}",
            (w - 200, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 200, 255),
            2,
            cv2.LINE_AA,
        )
        return screen
