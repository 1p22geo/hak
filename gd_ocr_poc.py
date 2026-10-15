"""
Geometry Dash Screen Reader / "Prawie OCR" - Proof of Concept (PoC)
-------------------------------------------------------------------
Kroki działania:
1. Robi screenshot ekranu (lub okna) przy użyciu 'mss'.
2. Ładuje klatkę do OpenCV (konwersja do formatu BGR).
3. Wycina wybrany fragment (ROI - Region of Interest, np. licznik %, próby, FPS).
4. Preprocessing obrazu (skala szarości, powiększenie, progowanie binarne dla czystego tekstu).
5. Odczytuje tekst, int lub float za pomocą OCR (wbudowany Windows Media OCR - bez potrzeby instalacji Tesseracta).
"""

import cv2
import numpy as np
import re
import asyncio
from typing import Optional, Tuple, Dict, Any

# Biblioteka do superszybkiego zrzucania ekranu
try:
    import mss
    import mss.tools
except ImportError:
    mss = None

# Windows Media OCR (wbudowany w Windows 10/11)
try:
    import winocr
    from PIL import Image
    from winrt.windows.media.ocr import OcrEngine
except ImportError:
    winocr = None


class ScreenReaderPoC:
    def __init__(self, language: Optional[str] = None):
        """
        Inicjalizacja czytnika ekranu i OCR.
        Domyślnie wykrywa zainstalowany język w Windows OCR (np. 'pl' lub 'en').
        """
        self.sct = mss.MSS() if mss else None
        self.language = language or self._detect_best_language()

    def _detect_best_language(self) -> str:
        """Automatycznie dobiera dostępny język Windows OCR."""
        if not winocr:
            return "en"
        try:
            available = [x.language_tag for x in OcrEngine.available_recognizer_languages]
            if "en" in available or "en-US" in available:
                return "en"
            if "pl" in available or "pl-PL" in available:
                return "pl"
            return available[0] if available else "en"
        except Exception:
            return "pl"

    def capture_screen(self, monitor_index: int = 1) -> np.ndarray:
        """
        KROK 1 & 2: Robi screenshot i ładuje do OpenCV (numpy array BGR).
        """
        if not self.sct:
            raise RuntimeError("Zainstaluj mss: pip install mss")

        monitor = self.sct.monitors[monitor_index]
        screenshot = self.sct.grab(monitor)

        # Konwersja BGRA (mss) -> BGR (OpenCV)
        frame = np.array(screenshot)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return frame_bgr

    def crop_roi(self, frame: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
        """
        KROK 3: Wycina fragment z obrazu (Region of Interest - ROI).
        """
        # Bezpieczne cięcie tablicy NumPy: [y:y+h, x:x+w]
        h_max, w_max = frame.shape[:2]
        x1 = max(0, min(x, w_max - 1))
        y1 = max(0, min(y, h_max - 1))
        x2 = max(x1 + 1, min(x + w, w_max))
        y2 = max(y1 + 1, min(y + h, h_max))
        return frame[y1:y2, x1:x2]

    def preprocess_for_ocr(self, roi: np.ndarray, scale: float = 2.5, thresh_val: int = 140) -> np.ndarray:
        """
        Preprocessing w OpenCV:
        - Skalowanie (mały tekst z gry staje się czytelniejszy dla OCR)
        - Konwersja do skali szarości
        - Progowanie binarne (czarne tło, czysty biały tekst bez szumów)
        """
        # 1. Zwiększenie rozdzielczości wycinka (kluczowe przy małych czcionkach w GD)
        if scale != 1.0:
            roi_scaled = cv2.resize(roi, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        else:
            roi_scaled = roi

        # 2. Skala szarości
        gray = cv2.cvtColor(roi_scaled, cv2.COLOR_BGR2GRAY)

        # 3. Binaryzacja (progowanie)
        # Opcjonalnie: cv2.threshold z THRESH_OTSU sam dobiera próg, jeśli kontrast jest zmienny
        _, binarized = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)

        return binarized

    def ocr_raw_text(self, image_np: np.ndarray) -> str:
        """
        KROK 4: Rozpoznawanie tekstu z wycinka.
        Używa wbudowanego Windows OCR (bardzo szybki, bez tesseract.exe).
        """
        if not winocr:
            raise RuntimeError("Zainstaluj winocr: pip install winocr")

        pil_img = Image.fromarray(image_np)
        res = asyncio.run(winocr.recognize_pil(pil_img, self.language))
        text = " ".join([line.text for line in res.lines]).strip()
        return text

    # ===============================================================
    # METODY ODCZYTU: STRING, INT, FLOAT
    # ===============================================================

    def read_string(self, roi: np.ndarray, preprocess: bool = True) -> str:
        """Zwraca odczytany surowy string z wycinka."""
        img = self.preprocess_for_ocr(roi) if preprocess else roi
        return self.ocr_raw_text(img)

    def read_int(self, roi: np.ndarray, preprocess: bool = True) -> Optional[int]:
        """
        Wyciąga pierwszą liczbę całkowitą (np. 'Attempt 42' -> 42, 'Stars: 15' -> 15).
        """
        raw = self.read_string(roi, preprocess=preprocess)
        # Szukamy ciągu cyfr
        match = re.search(r'\d+', raw)
        if match:
            try:
                return int(match.group(0))
            except ValueError:
                return None
        return None

    def read_float(self, roi: np.ndarray, preprocess: bool = True) -> Optional[float]:
        """
        Wyciąga liczbę zmiennoprzecinkową (np. '94.52%' -> 94.52, 'Time: 12.3s' -> 12.3).
        Obsługuje kropki i przecinki.
        """
        raw = self.read_string(roi, preprocess=preprocess)
        # Dopasowuje liczbę typu 12.34 lub 12,34 lub zwykłe 12
        match = re.search(r'[-+]?\d*[.,]\d+|\d+', raw)
        if match:
            token = match.group(0).replace(',', '.')
            try:
                return float(token)
            except ValueError:
                return None
        return None


# ===================================================================
# DEMO / TEST FUNKCJONALNOŚCI
# ===================================================================

def generate_mock_gd_screenshot() -> Tuple[np.ndarray, Dict[str, Tuple[int, int, int, int]]]:
    """Generuje przykładową klatkę symulującą HUD z Geometry Dash do testów."""
    h, w = 720, 1280
    screen = np.full((h, w, 3), (40, 20, 20), dtype=np.uint8)

    # 1. Pasek postępu (float): '73.49%' na górze ekranu
    cv2.putText(screen, "73.49%", (560, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3, cv2.LINE_AA)

    # 2. Licznik prób (int): 'Attempt 152'
    cv2.putText(screen, "Attempt 152", (500, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3, cv2.LINE_AA)

    # 3. Status/Napis (string): 'PRACTICE MODE'
    cv2.putText(screen, "PRACTICE MODE", (460, 650), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (100, 255, 100), 2, cv2.LINE_AA)

    # Współrzędne (x, y, w, h)
    rois = {
        "progress_percent": (540, 15, 220, 70),
        "attempt_count": (480, 310, 340, 80),
        "game_mode": (440, 605, 400, 60),
    }

    return screen, rois


def run_mock_demo():
    print("=" * 60)
    print("URUCHAMIANIE TESTU POc NA SYNTETYCZNYM EKRANIE GEOMETRY DASH")
    print("=" * 60)

    reader = ScreenReaderPoC()
    screen, rois = generate_mock_gd_screenshot()

    # 1. Test czytania FLOAT (procenty w GD)
    x, y, w, h = rois["progress_percent"]
    roi_float = reader.crop_roi(screen, x, y, w, h)
    val_float = reader.read_float(roi_float)
    raw_float = reader.read_string(roi_float)
    print(f"\n[1] ROI Procent ukończenia: {rois['progress_percent']}")
    print(f"    Raw OCR string: '{raw_float}'")
    print(f"    -> Parsed FLOAT: {val_float} (typ: {type(val_float).__name__})")

    # 2. Test czytania INT (licznik prób)
    x, y, w, h = rois["attempt_count"]
    roi_int = reader.crop_roi(screen, x, y, w, h)
    val_int = reader.read_int(roi_int)
    raw_int = reader.read_string(roi_int)
    print(f"\n[2] ROI Licznik prób: {rois['attempt_count']}")
    print(f"    Raw OCR string: '{raw_int}'")
    print(f"    -> Parsed INT: {val_int} (typ: {type(val_int).__name__})")

    # 3. Test czytania STRING (tryb gry)
    x, y, w, h = rois["game_mode"]
    roi_str = reader.crop_roi(screen, x, y, w, h)
    val_str = reader.read_string(roi_str)
    print(f"\n[3] ROI Tryb gry: {rois['game_mode']}")
    print(f"    -> Parsed STRING: '{val_str}'")

    print("\n" + "=" * 60)
    print("Test syntetyczny zakończony sukcesem!")
    print("=" * 60)


def run_live_screen_capture():
    """
    Uruchamia przechwytywanie w czasie rzeczywistym z Twojego ekranu.
    Możesz wskazać współrzędne fragmentu okna z Geometry Dash.
    """
    print("\n[LIVE MODE] Przechwytywanie na żywo...")
    reader = ScreenReaderPoC()

    # Współrzędne fragmentu, który chcesz śledzić (np. x, y, w, h w pikselach ekranu)
    # Możesz to dostosować do rozdzielczości swojego GD!
    ROI_X, ROI_Y, ROI_W, ROI_H = 100, 100, 250, 80

    print(f"Monitorowany wycinek: x={ROI_X}, y={ROI_Y}, w={ROI_W}, h={ROI_H}")
    print("Naciśnij Ctrl+C, aby zatrzymać.\n")

    try:
        while True:
            # 1. Zrzut ekranu
            frame = reader.capture_screen()

            # 2. Wycięcie ROI
            crop = reader.crop_roi(frame, ROI_X, ROI_Y, ROI_W, ROI_H)

            # 3. Odczyt wartości
            val_float = reader.read_float(crop)
            val_int = reader.read_int(crop)
            val_str = reader.read_string(crop)

            print(f"\rOdczyt: str='{val_str}' | float={val_float} | int={val_int}", end="", flush=True)

            # Opcjonalny podgląd okna OpenCV (odkomentuj jeśli chcesz okienko z podglądem):
            # cv2.imshow("ROI Preview", crop)
            # if cv2.waitKey(30) & 0xFF == 27: # ESC
            #     break

    except KeyboardInterrupt:
        print("\nZakończono nasłuch.")
    finally:
        cv2.destroyAllWindows()


def select_roi_interactively():
    """
    Robi zrzut ekranu i pozwala użytkownikowi zaznaczyć myszką obszar (np. pasek %, FPS, Attempt).
    Po zaznaczeniu i wciśnięciu ENTER / SPACJA wypisuje gotowe współrzędne x, y, w, h.
    """
    print("\n[SELECT MODE] Robię zrzut ekranu do zaznaczenia...")
    reader = ScreenReaderPoC()
    frame = reader.capture_screen()

    window_title = "Wybierz ROI myszka (Zaznacz prostokat, wcisnij SPACJE lub ENTER, ESC by anulowac)"
    # Tworzymy okno z możliwością przeskalowania jeśli ekran jest duży
    cv2.namedWindow(window_title, cv2.WINDOW_NORMAL)
    roi_coords = cv2.selectROI(window_title, frame, fromCenter=False, showCrosshair=True)
    cv2.destroyAllWindows()

    x, y, w, h = roi_coords
    if w == 0 or h == 0:
        print("Nie wybrano żadnego obszaru.")
        return

    print("\n" + "=" * 50)
    print(f"WYBRANE WSPÓŁRZĘDNE ROI:")
    print(f"  x={x}, y={y}, w={w}, h={h}")
    print("=" * 50)

    # Testowy odczyt wybranego fragmentu
    crop = reader.crop_roi(frame, x, y, w, h)
    raw = reader.read_string(crop)
    parsed_float = reader.read_float(crop)
    parsed_int = reader.read_int(crop)

    print(f"-> Tekst: '{raw}'")
    print(f"-> Jako float: {parsed_float}")
    print(f"-> Jako int: {parsed_int}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        run_live_screen_capture()
    elif len(sys.argv) > 1 and sys.argv[1] == "--select":
        select_roi_interactively()
    else:
        run_mock_demo()
        print("\nDostępne tryby uruchomienia:")
        print("  1. Test syntetyczny:    py gd_ocr_poc.py")
        print("  2. Zaznaczanie myszką:  py gd_ocr_poc.py --select")
        print("  3. Ciągły nasłuch:      py gd_ocr_poc.py --live")
