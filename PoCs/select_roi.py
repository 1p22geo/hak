"""
Interactive Screen ROI Selector (Blue Snipping Overlay)
-------------------------------------------------------
Pozwala zaznaczyć myszką prostokątny obszar ekranu (z niebieską ramką
w stylu narzędzia Wycinanie / Snipping Tool) i wypisuje 4 współrzędne ROI.

Użycie przez uv:
    uv run python PoCs/select_roi.py

Funkcje:
- Per-Monitor DPI Awareness (współrzędne 1:1 z rozdzielczością fizyczną OpenCV / mss)
- Przyciemniony ekran z rozjaśnianym wycinkiem w trakcie zaznaczania
- Niebieska ramka w stylu Windows Snipping Tool z etykietą wymiarów (W x H)
- Wypisanie współrzędnych w wielu formatach (x, y, w, h / x1, y1, x2, y2 / slice)
- Automatyczne skopiowanie (x, y, w, h) do schowka Windows
- Zapis miniatury wybranego fragmentu do podglądu (last_selected_roi.png)
- Klawisz ESC anuluje wybór
"""

import sys
import ctypes
import os
from typing import Optional, Tuple, Dict, Any

# 1. Włączamy pełną obsługę DPI w Windows przed importem GUI,
# aby współrzędne pikseli pokrywały się 1:1 ze zrzutami ekranu mss / OpenCV
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from PIL import Image, ImageTk, ImageEnhance

try:
    import mss
except ImportError:
    mss = None


class ScreenRegionSelector:
    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index
        self.result: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)

        # Punkty zaznaczenia
        self.start_x = 0
        self.start_y = 0
        self.current_x = 0
        self.current_y = 0
        self.is_drawing = False

        # Zrzuty ekranu
        self.original_image: Optional[Image.Image] = None
        self.dimmed_image: Optional[Image.Image] = None
        self.tk_background: Optional[ImageTk.PhotoImage] = None

    def _grab_screenshot(self) -> Image.Image:
        """Pobiera screenshot bieżącego ekranu/monitora."""
        if mss:
            with mss.mss() as sct:
                # Jeśli podano konkretny monitor, bierzemy go, w przeciwnym razie monitor 1
                mon_idx = min(self.monitor_index, len(sct.monitors) - 1)
                monitor = sct.monitors[mon_idx]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                return img
        else:
            from PIL import ImageGrab
            return ImageGrab.grab(all_screens=True)

    def select(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Otwiera pełnoekranową nakładkę do zaznaczenia ROI.
        Zwraca krotkę (x, y, w, h) lub None, jeśli anulowano klawiszem ESC.
        """
        root = tk.Tk()
        root.title("ROI Selector Overlay")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.config(cursor="crosshair")

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()

        # Próbujemy pobrać screenshot dla efektu przyciemnienia tła
        has_screenshot = False
        try:
            raw_shot = self._grab_screenshot()
            # Dopasowujemy rozmiar zrzutu do okna (jeśli był robiony w innej geometrii)
            if raw_shot.size != (screen_w, screen_h):
                self.original_image = raw_shot.resize((screen_w, screen_h), Image.Resampling.LANCZOS)
            else:
                self.original_image = raw_shot

            # Przyciemniamy tło o 45% (jak w narzędziu wycinania)
            enhancer = ImageEnhance.Brightness(self.original_image)
            self.dimmed_image = enhancer.enhance(0.55)
            self.tk_background = ImageTk.PhotoImage(self.dimmed_image)
            has_screenshot = True
        except Exception as e:
            # Tryb awaryjny (np. brak dostępu do bufora ekranu)
            root.attributes("-alpha", 0.35)
            root.configure(bg="#1e1e2e")

        canvas = tk.Canvas(root, cursor="crosshair", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        if has_screenshot and self.tk_background:
            canvas.create_image(0, 0, image=self.tk_background, anchor=tk.NW)

        # Informacja pomocnicza na górze ekranu
        info_pill = canvas.create_rectangle(
            screen_w // 2 - 220, 15, screen_w // 2 + 220, 50,
            fill="#181825", outline="#313244", width=1
        )
        info_text = canvas.create_text(
            screen_w // 2, 32,
            text="Zaznacz obszar myszką (LPM) | [ESC] Anuluj",
            fill="#cdd6f4", font=("Segoe UI", 11, "bold")
        )

        # Identyfikatory elementów graficznych rysowanych na bieżąco
        rect_border_id = None
        rect_fill_id = None
        badge_rect_id = None
        badge_text_id = None
        bright_crop_img_tk = None  # referencja, by GC nie usunął

        def on_mouse_down(event):
            nonlocal rect_border_id, rect_fill_id, badge_rect_id, badge_text_id
            self.is_drawing = True
            self.start_x = event.x
            self.start_y = event.y
            self.current_x = event.x
            self.current_y = event.y

            # Ukrywamy podpowiedź początkową przy rozpoczęciu rysowania
            canvas.itemconfigure(info_pill, state="hidden")
            canvas.itemconfigure(info_text, state="hidden")

        def on_mouse_move(event):
            nonlocal rect_border_id, rect_fill_id, badge_rect_id, badge_text_id, bright_crop_img_tk
            if not self.is_drawing:
                return

            self.current_x = event.x
            self.current_y = event.y

            x1 = min(self.start_x, self.current_x)
            y1 = min(self.start_y, self.current_y)
            x2 = max(self.start_x, self.current_x)
            y2 = max(self.start_y, self.current_y)
            w = x2 - x1
            h = y2 - y1

            # Usuwamy poprzednie kształty
            if rect_border_id:
                canvas.delete(rect_border_id)
            if rect_fill_id:
                canvas.delete(rect_fill_id)
            if badge_rect_id:
                canvas.delete(badge_rect_id)
            if badge_text_id:
                canvas.delete(badge_text_id)

            if w > 1 and h > 1:
                # Rozjaśniony wycinek oryginalnego obrazu wewnątrz zaznaczenia
                if has_screenshot and self.original_image:
                    crop_box = (x1, y1, x2, y2)
                    cropped = self.original_image.crop(crop_box)
                    bright_crop_img_tk = ImageTk.PhotoImage(cropped)
                    rect_fill_id = canvas.create_image(x1, y1, image=bright_crop_img_tk, anchor=tk.NW)

                # Niebieska ramka w stylu Windows Snipping Tool (#0078D7 / #00a2ed)
                rect_border_id = canvas.create_rectangle(
                    x1, y1, x2, y2,
                    outline="#00a2ed", width=2
                )

                # Dymka z wymiarami zaznaczonego ROI
                badge_text = f"{w} × {h}  (X: {x1}, Y: {y1})"
                badge_x = x2 + 8 if x2 + 180 < screen_w else x1 - 180
                badge_y = y2 + 8 if y2 + 35 < screen_h else y1 - 35

                badge_rect_id = canvas.create_rectangle(
                    badge_x, badge_y, badge_x + 165, badge_y + 26,
                    fill="#11111b", outline="#00a2ed", width=1
                )
                badge_text_id = canvas.create_text(
                    badge_x + 82, badge_y + 13,
                    text=badge_text,
                    fill="#ffffff", font=("Consolas", 10, "bold")
                )

        def on_mouse_up(event):
            self.is_drawing = False
            self.current_x = event.x
            self.current_y = event.y

            x1 = min(self.start_x, self.current_x)
            y1 = min(self.start_y, self.current_y)
            x2 = max(self.start_x, self.current_x)
            y2 = max(self.start_y, self.current_y)
            w = x2 - x1
            h = y2 - y1

            # Wymagamy sensownego minimalnego rozmiaru (np. > 3 piksele)
            if w > 3 and h > 3:
                self.result = (x1, y1, w, h)
                # Skopiuj do schowka
                try:
                    root.clipboard_clear()
                    root.clipboard_append(f"({x1}, {y1}, {w}, {h})")
                    root.update()
                except Exception:
                    pass
                root.destroy()
            else:
                # Kliknięcie bez przeciągnięcia - ignorujemy lub czekamy na ponowny ruch
                pass

        def on_cancel(event=None):
            self.result = None
            root.destroy()

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)
        root.bind("<Escape>", on_cancel)

        # Uruchamiamy pętlę okna
        root.mainloop()

        return self.result


def select_screen_roi(monitor_index: int = 1) -> Optional[Tuple[int, int, int, int]]:
    """Główna funkcja pomocnicza do importu w innych skryptach."""
    selector = ScreenRegionSelector(monitor_index=monitor_index)
    return selector.select()


def print_roi_report(roi: Tuple[int, int, int, int], save_preview: bool = True):
    """Drukuje ładne zestawienie współrzędnych do skopiowania do kodu."""
    x, y, w, h = roi
    x1, y1 = x, y
    x2, y2 = x + w, y + h

    print("\n" + "=" * 60)
    print("  SUKCES: POMYŚLNIE ZAZNACZONO OBSZAR ROI")
    print("=" * 60)
    print(f"\n  [1] Współrzędne (X, Y, W, H):")
    print(f"      ROI = ({x}, {y}, {w}, {h})")
    print(f"\n  [2] Słownik Pythona:")
    print(f"      ROI = {{'x': {x}, 'y': {y}, 'w': {w}, 'h': {h}}}")
    print(f"\n  [3] Slicing dla tablicy OpenCV (numpy):")
    print(f"      crop = frame[{y}:{y + h}, {x}:{x + w}]")
    print(f"\n  [4] Rogi (X1, Y1, X2, Y2):")
    print(f"      ({x1}, {y1}) -> ({x2}, {y2})  |  Wymiary: {w}x{h} px")
    print("-" * 60)
    print("  -> Skopiowano '(x, y, w, h)' do schowka systemowego!")

    # Opcjonalny zapis wycinka do pliku png w folderze PoCs/
    if save_preview:
        try:
            if mss:
                with mss.mss() as sct:
                    monitor = {"top": y, "left": x, "width": w, "height": h}
                    shot = sct.grab(monitor)
                    preview_path = os.path.join(os.path.dirname(__file__), "last_selected_roi.png")
                    mss.tools.to_png(shot.rgb, shot.size, output=preview_path)
                    print(f"  -> Zapisano podgląd wycinka do: {preview_path}")
        except Exception as e:
            pass
    print("=" * 60 + "\n")


def main():
    print("\nUruchamiam nakładkę zaznaczania ROI...")
    print("Naciśnij i przeciągnij lewy przycisk myszy. Wciśnij ESC, aby anulować.\n")

    roi = select_screen_roi()
    if roi is not None:
        print_roi_report(roi, save_preview=True)
    else:
        print("\n[ANULOWANO] Nie zaznaczono żadnego obszaru (naciśnięto ESC lub zamknięto).\n")


if __name__ == "__main__":
    main()
