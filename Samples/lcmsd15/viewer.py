import os
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
import hashlib
from itertools import combinations

IMAGE_DIR = "images"
CACHE_DIR = ".thumb_cache"
THUMB_SIZE = 150

RENAMES = {"n": "steps", "cfg": "g", "s": "str"}
KNOWN_PARAMS = ["str", "g", "res", "steps", "loops"]
DEFAULTS = {"str": 1.0, "g": 7, "res": 512, "steps": 4, "loops": 1}

BG = "#ffffff"
BG2 = "#f0f0f0"
BG3 = "#e0e0e0"
BG_DISABLED = "#e8e8e8"
FG = "#111111"
FG2 = "#333333"
FG_DISABLED = "#aaaaaa"
ACCENT = "#2266cc"
FONT = ("Arial", 12)
FONT_BOLD = ("Arial", 12, "bold")
FONT_HEADER = ("Arial", 11, "bold")

CELL_PAD = 4
CELL_W = THUMB_SIZE + CELL_PAD * 2
CELL_H = THUMB_SIZE + CELL_PAD * 2
HEADER_W = 120
HEADER_H = 40
DRAG_THRESHOLD = 5


def parse_filename(filename):
    name = os.path.splitext(filename)[0]
    parts = name.split("_")
    params = {}
    for part in parts:
        part = part.replace("-", ".")
        all_keys = sorted(list(RENAMES.keys()) + KNOWN_PARAMS, key=len, reverse=True)
        for key in all_keys:
            if part.startswith(key):
                val_str = part[len(key):]
                try:
                    val = float(val_str)
                    params[RENAMES.get(key, key)] = val
                    break
                except ValueError:
                    pass
    for k, v in DEFAULTS.items():
        if k not in params:
            params[k] = v
    return params


def load_database():
    db = []
    if not os.path.exists(IMAGE_DIR):
        return db
    for fname in os.listdir(IMAGE_DIR):
        if fname.lower().endswith(".png"):
            params = parse_filename(fname)
            if params:
                path = os.path.join(IMAGE_DIR, fname)
                db.append({"file": path, "params": params,
                            "filesize": os.path.getsize(path)})
    return db


def get_thumb_path(image_path):
    os.makedirs(CACHE_DIR, exist_ok=True)
    h = hashlib.md5(image_path.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}_{THUMB_SIZE}.png")


def build_thumbnail(image_path):
    thumb_path = get_thumb_path(image_path)
    if os.path.exists(thumb_path):
        if os.path.getmtime(thumb_path) >= os.path.getmtime(image_path):
            return thumb_path
    img = Image.open(image_path).resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
    img.save(thumb_path, "PNG")
    return thumb_path


class SplashProgress(tk.Toplevel):
    def __init__(self, parent, total):
        super().__init__(parent)
        self.title("Loading thumbnails...")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.total = total
        w, h = 400, 110
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth()-w)//2}+{(self.winfo_screenheight()-h)//2}")
        self.grab_set()
        tk.Label(self, text="Building thumbnail cache...", bg=BG, fg=FG,
                 font=FONT_BOLD).pack(pady=(18, 6))
        self.bar = ttk.Progressbar(self, length=340, maximum=total, mode="determinate")
        self.bar.pack(pady=4)
        self.lbl = tk.Label(self, text=f"0 / {total}", bg=BG, fg=FG2, font=FONT)
        self.lbl.pack()

    def update_progress(self, done):
        self.bar["value"] = done
        self.lbl.config(text=f"{done} / {self.total}")
        self.update()


class ImageBrowser(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Parameter Browser")
        self.state("zoomed")
        self.configure(bg=BG)
        self.withdraw()

        self.db = load_database()
        self.all_params = self._collect_all_params()
        self._index = {frozenset(e["params"].items()): e for e in self.db}

        self.x_var = tk.StringVar()
        self.y_var = tk.StringVar()
        self.slider_vars = {}
        self.slider_values = {}
        self.slider_widgets = {}

        self.tk_cache = {}
        self._empty_img = None
        self._top_slices = self._compute_top_slices()

        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_moved = False
        self._pending_open = None  # path to open on release

        self._apply_style()
        self._build_ui()
        self._init_dropdowns()
        self._init_sliders()
        self._preload_thumbnails()

        self.deiconify()
        self.update_grid()

    def _apply_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG, background=BG,
                        foreground=FG, font=FONT)
        style.configure("TScrollbar", background=BG3, troughcolor=BG2)

    def _collect_all_params(self):
        params = {}
        for entry in self.db:
            for k, v in entry["params"].items():
                params.setdefault(k, set()).add(v)
        return {k: sorted(v) for k, v in params.items()}

    def _compute_top_slices(self):
        params = list(self.all_params.keys())
        results = []
        for x_param, y_param in combinations(params, 2):
            fixed_params = [p for p in params if p not in (x_param, y_param)]
            if not fixed_params:
                total = sum(e["filesize"] for e in self.db)
                results.append({"x": x_param, "y": y_param, "fixed": {},
                                 "score": total, "label": f"{x_param} vs {y_param}"})
                continue
            slice_scores = {}
            for entry in self.db:
                fixed_key = tuple((p, entry["params"].get(p)) for p in fixed_params)
                slice_scores[fixed_key] = slice_scores.get(fixed_key, 0) + entry["filesize"]
            best_key, best_score = max(slice_scores.items(), key=lambda kv: kv[1])
            fixed_dict = dict(best_key)
            fixed_str = ", ".join(f"{k}={v}" for k, v in fixed_dict.items())
            results.append({"x": x_param, "y": y_param, "fixed": fixed_dict,
                             "score": best_score,
                             "label": f"{x_param} vs {y_param}  [{fixed_str}]"})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:10]

    def _preload_thumbnails(self):
        if not self.db:
            return
        splash = SplashProgress(self, len(self.db))
        for i, entry in enumerate(self.db):
            entry["thumb_path"] = build_thumbnail(entry["file"])
            splash.update_progress(i + 1)
        splash.destroy()

    def _get_tk_image(self, thumb_path):
        if thumb_path not in self.tk_cache:
            self.tk_cache[thumb_path] = ImageTk.PhotoImage(Image.open(thumb_path))
        return self.tk_cache[thumb_path]

    def _get_empty_image(self):
        if self._empty_img is None:
            img = Image.new("RGB", (THUMB_SIZE, THUMB_SIZE), color=(220, 220, 220))
            draw = ImageDraw.Draw(img)
            m, s = 20, THUMB_SIZE
            draw.line([(m, m), (s-m, s-m)], fill=(180, 180, 180), width=2)
            draw.line([(s-m, m), (m, s-m)], fill=(180, 180, 180), width=2)
            self._empty_img = ImageTk.PhotoImage(img)
        return self._empty_img

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────
        top = tk.Frame(self, bg=BG2, pady=8)
        top.pack(side=tk.TOP, fill=tk.X)

        tk.Label(top, text="X Axis:", bg=BG2, fg=FG, font=FONT_BOLD).pack(side=tk.LEFT, padx=(14, 4))
        self.x_combo = ttk.Combobox(top, textvariable=self.x_var, state="readonly", width=10, font=FONT)
        self.x_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.x_combo.bind("<<ComboboxSelected>>", lambda e: self._on_axis_change())

        self.x_vals_label = tk.Label(top, text="", bg=BG2, fg=ACCENT, font=FONT)
        self.x_vals_label.pack(side=tk.LEFT, padx=(0, 18))

        tk.Label(top, text="Y Axis:", bg=BG2, fg=FG, font=FONT_BOLD).pack(side=tk.LEFT, padx=(0, 4))
        self.y_combo = ttk.Combobox(top, textvariable=self.y_var, state="readonly", width=10, font=FONT)
        self.y_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.y_combo.bind("<<ComboboxSelected>>", lambda e: self._on_axis_change())

        self.y_vals_label = tk.Label(top, text="", bg=BG2, fg=ACCENT, font=FONT)
        self.y_vals_label.pack(side=tk.LEFT, padx=(0, 24))

        tk.Frame(top, bg=BG3, width=2).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        tk.Label(top, text="Top slices:", bg=BG2, fg=FG, font=FONT_BOLD).pack(side=tk.LEFT, padx=(6, 4))
        self.slice_var = tk.StringVar()
        self.slice_combo = ttk.Combobox(top, textvariable=self.slice_var, state="readonly",
                                        width=52, font=FONT,
                                        values=[s["label"] for s in self._top_slices])
        self.slice_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.slice_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_top_slice())

        tk.Frame(self, bg=BG3, height=2).pack(fill=tk.X)

        # ── Main area ────────────────────────────────────────────
        main = tk.Frame(self, bg=BG)
        main.pack(fill=tk.BOTH, expand=True)

        # Right panel
        tk.Frame(main, bg=BG3, width=2).pack(side=tk.RIGHT, fill=tk.Y)
        right = tk.Frame(main, bg=BG2, width=230)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)
        tk.Label(right, text="Filters", bg=BG2, fg=FG,
                 font=("Arial", 14, "bold")).pack(pady=(14, 6))
        tk.Frame(right, bg=BG3, height=2).pack(fill=tk.X, padx=8)
        self.sliders_frame = tk.Frame(right, bg=BG2)
        self.sliders_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        # Grid area - use a plain Frame, manually place everything
        self.grid_area = tk.Frame(main, bg=BG)
        self.grid_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbars packed into grid_area edges
        self.vscroll = ttk.Scrollbar(self.grid_area, orient=tk.VERTICAL)
        self.vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.hscroll = ttk.Scrollbar(self.grid_area, orient=tk.HORIZONTAL)
        self.hscroll.pack(side=tk.BOTTOM, fill=tk.X)

        # Corner label (top-left fixed cell)
        self.corner = tk.Label(self.grid_area, bg=BG3, relief="flat",
                               width=HEADER_W, height=HEADER_H)
        self.corner.place(x=0, y=0, width=HEADER_W, height=HEADER_H)
        self.corner.lift()

        # Col header canvas - sits at top, left of HEADER_W, clips to its frame
        self.col_header_canvas = tk.Canvas(self.grid_area, bg=BG3,
                                           highlightthickness=0, height=HEADER_H)
        self.col_header_canvas.place(x=HEADER_W, y=0, height=HEADER_H)

        # Row header canvas - sits at left, top of HEADER_H
        self.row_header_canvas = tk.Canvas(self.grid_area, bg=BG3,
                                           highlightthickness=0, width=HEADER_W)
        self.row_header_canvas.place(x=0, y=HEADER_H, width=HEADER_W)

        # Main canvas
        self.canvas = tk.Canvas(self.grid_area, bg=BG, highlightthickness=0,
                                yscrollcommand=self._on_yscroll,
                                xscrollcommand=self._on_xscroll)
        self.canvas.place(x=HEADER_W, y=HEADER_H)

        self.vscroll.config(command=self.canvas.yview)
        self.hscroll.config(command=self.canvas.xview)

        # Resize binding to reposition canvases
        self.grid_area.bind("<Configure>", self._on_grid_resize)

        # Mouse bindings
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)

    def _on_grid_resize(self, event):
        # Recompute sizes for placed widgets
        vscroll_w = self.vscroll.winfo_width() or 16
        hscroll_h = self.hscroll.winfo_height() or 16
        w = event.width - vscroll_w
        h = event.height - hscroll_h

        self.col_header_canvas.place(x=HEADER_W, y=0,
                                     width=max(1, w - HEADER_W),
                                     height=HEADER_H)
        self.row_header_canvas.place(x=0, y=HEADER_H,
                                     width=HEADER_W,
                                     height=max(1, h - HEADER_H))
        self.canvas.place(x=HEADER_W, y=HEADER_H,
                          width=max(1, w - HEADER_W),
                          height=max(1, h - HEADER_H))

    # ── Scroll sync ──────────────────────────────────────────────
    def _on_yscroll(self, first, last):
        self.vscroll.set(first, last)
        self.row_header_canvas.yview_moveto(float(first))

    def _on_xscroll(self, first, last):
        self.hscroll.set(first, last)
        self.col_header_canvas.xview_moveto(float(first))

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_shift_mousewheel(self, event):
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Drag scroll ──────────────────────────────────────────────
    def _drag_start(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._drag_moved = False
        sr = self.canvas.cget("scrollregion")
        if sr:
            parts = sr.split()
            self._drag_total_w = float(parts[2]) if len(parts) > 2 else 1
            self._drag_total_h = float(parts[3]) if len(parts) > 3 else 1
        else:
            self._drag_total_w = self._drag_total_h = 1
        self._drag_scroll_x = self.canvas.xview()[0]
        self._drag_scroll_y = self.canvas.yview()[0]
        # Hit-test what's under the cursor
        self._pending_open = None
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(cx, cy, cx, cy)
        if items:
            item = items[-1]
            self._pending_open = self._item_paths.get(item)
        self.canvas.config(cursor="fleur")


    def _drag_motion(self, event):
        dx = self._drag_start_x - event.x
        dy = self._drag_start_y - event.y
        if abs(dx) > DRAG_THRESHOLD or abs(dy) > DRAG_THRESHOLD:
            self._drag_moved = True
        if self._drag_moved:
            self.canvas.xview_moveto(self._drag_scroll_x + dx / self._drag_total_w)
            self.canvas.yview_moveto(self._drag_scroll_y + dy / self._drag_total_h)

    def _drag_end(self, event):
        self.canvas.config(cursor="")
        if not self._drag_moved and self._pending_open:
            self._open_full(self._pending_open)
        self._pending_open = None
        self._drag_moved = False

    # ── Dropdowns / sliders ──────────────────────────────────────
    def _init_dropdowns(self):
        params = list(self.all_params.keys())
        self.x_combo["values"] = params
        self.y_combo["values"] = params
        if len(params) >= 1:
            self.x_var.set(params[0])
        if len(params) >= 2:
            self.y_var.set(params[1])

    def _init_sliders(self):
        for w in self.sliders_frame.winfo_children():
            w.destroy()
        self.slider_vars.clear()
        self.slider_values.clear()
        self.slider_widgets.clear()

        for param, values in self.all_params.items():
            self.slider_values[param] = values
            var = tk.IntVar(value=0)
            self.slider_vars[param] = var

            frame = tk.Frame(self.sliders_frame, bg=BG2)
            frame.pack(fill=tk.X, pady=6)

            top_row = tk.Frame(frame, bg=BG2)
            top_row.pack(fill=tk.X)
            name_lbl = tk.Label(top_row, text=param, bg=BG2, fg=FG, font=FONT_BOLD, anchor="w")
            name_lbl.pack(side=tk.LEFT)
            val_lbl = tk.Label(top_row, text=str(values[0]), bg=BG2, fg=ACCENT, font=FONT_BOLD, anchor="e")
            val_lbl.pack(side=tk.RIGHT)

            slider = tk.Scale(frame, from_=0, to=len(values)-1, orient=tk.HORIZONTAL,
                              variable=var, showvalue=False, bg=BG2, fg=FG,
                              troughcolor=BG3, activebackground=ACCENT,
                              highlightthickness=0, bd=0,
                              command=lambda v, p=param, vl=val_lbl: self._on_slider(p, vl))
            slider.pack(fill=tk.X)

            tick = tk.Frame(frame, bg=BG2)
            tick.pack(fill=tk.X)
            tk.Label(tick, text=str(values[0]), bg=BG2, fg=FG2, font=("Arial", 9)).pack(side=tk.LEFT)
            tk.Label(tick, text=str(values[-1]), bg=BG2, fg=FG2, font=("Arial", 9)).pack(side=tk.RIGHT)

            self.slider_widgets[param] = {"frame": frame, "slider": slider,
                                          "val_label": val_lbl, "name_label": name_lbl}
        self._update_slider_states()

    def _update_slider_states(self):
        axis = {self.x_var.get(), self.y_var.get()}
        for param, w in self.slider_widgets.items():
            dis = param in axis
            fg = FG_DISABLED if dis else FG
            bg = BG_DISABLED if dis else BG2
            ac = FG_DISABLED if dis else ACCENT
            w["frame"].config(bg=bg)
            w["name_label"].config(bg=bg, fg=fg)
            w["val_label"].config(bg=bg, fg=ac)
            w["slider"].config(state=tk.DISABLED if dis else tk.NORMAL,
                               bg=bg, troughcolor=BG_DISABLED if dis else BG3)

    def _update_axis_value_labels(self):
        def fmt(p):
            vals = self.all_params.get(p, [])
            return "[" + ", ".join(str(v) for v in vals) + "]" if vals else ""
        self.x_vals_label.config(text=fmt(self.x_var.get()))
        self.y_vals_label.config(text=fmt(self.y_var.get()))

    def _on_axis_change(self):
        self._update_slider_states()
        self._update_axis_value_labels()
        self.update_grid()

    def _on_slider(self, param, val_label):
        idx = self.slider_vars[param].get()
        val_label.config(text=str(self.slider_values[param][idx]))
        self.update_grid()

    def _apply_top_slice(self):
        idx = self.slice_combo.current()
        if idx < 0:
            return
        sl = self._top_slices[idx]
        self.x_var.set(sl["x"])
        self.y_var.set(sl["y"])
        for param, val in sl["fixed"].items():
            if param in self.slider_values and val in self.slider_values[param]:
                self.slider_vars[param].set(self.slider_values[param].index(val))
                self.slider_widgets[param]["val_label"].config(text=str(val))
        self._on_axis_change()

    def _get_filter_values(self):
        return {p: self.slider_values[p][v.get()] for p, v in self.slider_vars.items()}

    def _find_entry(self, filters):
        return self._index.get(frozenset(filters.items()))

    # ── Grid rendering ───────────────────────────────────────────
    def update_grid(self):
        self.canvas.delete("all")
        self._item_paths = {}
        self.col_header_canvas.delete("all")
        self.row_header_canvas.delete("all")
        self.canvas.image_refs = []

        x_param = self.x_var.get()
        y_param = self.y_var.get()
        self._update_axis_value_labels()

        if not x_param or not y_param or x_param == y_param:
            self.canvas.create_text(200, 60, text="Pick two different axis parameters.",
                                    fill=FG2, font=FONT)
            return

        filters = self._get_filter_values()
        filters.pop(x_param, None)
        filters.pop(y_param, None)

        x_vals_all = self.all_params.get(x_param, [])
        y_vals_all = self.all_params.get(y_param, [])

        x_vals = [x for x in x_vals_all if any(
            self._find_entry({**filters, x_param: x, y_param: y}) for y in y_vals_all)]
        y_vals = [y for y in y_vals_all if any(
            self._find_entry({**filters, x_param: x, y_param: y}) for x in x_vals_all)]

        if not x_vals or not y_vals:
            self.canvas.create_text(200, 60, text="No images match current filters.",
                                    fill=FG2, font=FONT)
            return

        total_w = len(x_vals) * CELL_W
        total_h = len(y_vals) * CELL_H

        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))
        # Header canvases need scrollregion too for xview_moveto/yview_moveto to work
        self.col_header_canvas.configure(scrollregion=(0, 0, total_w, HEADER_H))
        self.row_header_canvas.configure(scrollregion=(0, 0, HEADER_W, total_h))

        # Sync header positions to current main canvas scroll
        cx0 = self.canvas.xview()[0]
        cy0 = self.canvas.yview()[0]
        self.col_header_canvas.xview_moveto(cx0)
        self.row_header_canvas.yview_moveto(cy0)

        # Col headers
        for col, xv in enumerate(x_vals):
            x0 = col * CELL_W
            self.col_header_canvas.create_rectangle(x0, 0, x0 + CELL_W, HEADER_H,
                                                    fill=BG3, outline=BG2)
            self.col_header_canvas.create_text(x0 + CELL_W // 2, HEADER_H // 2,
                                               text=f"{x_param}={xv}",
                                               fill=FG, font=FONT_HEADER)

        # Row headers
        for row, yv in enumerate(y_vals):
            y0 = row * CELL_H
            self.row_header_canvas.create_rectangle(0, y0, HEADER_W, y0 + CELL_H,
                                                    fill=BG3, outline=BG2)
            self.row_header_canvas.create_text(HEADER_W // 2, y0 + CELL_H // 2,
                                               text=f"{y_param}={yv}",
                                               fill=FG, font=FONT_HEADER)

        # Images
        for row, yv in enumerate(y_vals):
            for col, xv in enumerate(x_vals):
                f = {**filters, x_param: xv, y_param: yv}
                entry = self._find_entry(f)
                cx = col * CELL_W + CELL_PAD
                cy = row * CELL_H + CELL_PAD

                if entry and "thumb_path" in entry:
                    img = self._get_tk_image(entry["thumb_path"])
                    item = self.canvas.create_image(cx, cy, anchor="nw", image=img)
                    self._item_paths[item] = entry["file"]   # ← store, no tag_bind

                else:
                    img = self._get_empty_image()
                    self.canvas.create_image(cx, cy, anchor="nw", image=img)

                self.canvas.image_refs.append(img)

    def _on_image_press(self, path):
        # Record intent; actual open happens in drag_end if no drag occurred
        self._pending_open = path

    def _open_full(self, path):
        win = tk.Toplevel(self, bg=BG)
        win.attributes("-topmost", True)
        win.title(os.path.basename(path))
        img = Image.open(path)
        tk_img = ImageTk.PhotoImage(img)
        lbl = tk.Label(win, image=tk_img, bg=BG)
        lbl.image = tk_img
        lbl.pack(padx=10, pady=10)

        # Drag to move window
        lbl._drag_x = 0
        lbl._drag_y = 0

        def on_press(e):
            lbl._drag_x = e.x_root - win.winfo_x()
            lbl._drag_y = e.y_root - win.winfo_y()

        def on_drag(e):
            win.geometry(f"+{e.x_root - lbl._drag_x}+{e.y_root - lbl._drag_y}")

        lbl.bind("<ButtonPress-1>", on_press)
        lbl.bind("<B1-Motion>", on_drag)



if __name__ == "__main__":
    app = ImageBrowser()
    app.mainloop()
