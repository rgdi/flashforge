# FlashForge - Smart Flashcard Deck Builder for Anki 25.09
# License: AGPL-3.0
#
# Rapid deck creation with multiple card types, FSRS-aware scheduling,
# and exam-date-based study planning for PAU.
#
# Card types supported:
#   1. Basic          → Pregunta / Respuesta (clásico)
#   2. Basic+Image    → Con imagen frontal (pregunta visual)
#   3. Inverse        → Respuesta / Pregunta (reversa)
#   4. Open           → Pregunta abierta / Respuesta libre
#   5. Cloze          → Texto con huecos [[hueco]]
#   6. Image Occlusion → Máscara sobre imagen
#   7. Two卡片         → Dos tarjetas relacionadas (vocabulario)
#
# FSRS configuration:
#   - Input: exam_date (target exam date)
#   - Computes optimal interval distribution
#   - Presets: 30d/7d/3d/1d "cram" before exam
#   - Reschedules all cards in deck to exam target

from __future__ import annotations

import json as _json
import math
import os
import re
from datetime import date, datetime, timedelta
from typing import Any

import aqt
import aqt.main
from aqt import gui_hooks, mw
from aqt.qt import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFont,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
    QIcon,
    QFileDialog,
    QTimer,
)
from aqt.utils import showInfo, showWarning, tooltip


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

__addon_id__ = "1742078545"

CARD_BASIC     = "basic"
CARD_BASIC_IMG = "basic_img"
CARD_INVERSE   = "inverse"
CARD_OPEN      = "open"
CARD_CLOZE     = "cloze"
CARD_IO        = "image_occl"
CARD_TWOCARD   = "two_card"

# ──────────────────────────────────────────────────────────────────────────────
# Note-Type definitions (templates)
# ──────────────────────────────────────────────────────────────────────────────

NOTE_DEFS = {

    CARD_BASIC: {
        "name": "FlashForge_Basic",
        "fields": ["Pregunta", "Respuesta"],
        "qfmt": "{{Pregunta}}",
        "afmt": "{{Pregunta}}<hr id=answer>{{Respuesta}}",
    },

    CARD_BASIC_IMG: {
        "name": "FlashForge_BasicImg",
        "fields": ["Pregunta", "Imagen (opcional)", "Respuesta"],
        "qfmt": ("{{Pregunta}}"
                 "{{#Imagen}}<br><img src=\"{{Imagen}}\">{{/Imagen}}"),
        "afmt": ("{{Pregunta}}"
                 "{{#Imagen}}<br><img src=\"{{Imagen}}\">{{/Imagen}}"
                 "<hr id=answer>{{Respuesta}}"),
    },

    CARD_INVERSE: {
        "name": "FlashForge_Inverse",
        "fields": ["Frente", "Reverso"],
        "qfmt": "{{Frente}}",
        "afmt": "{{Frente}}<hr id=answer>{{Reverso}}",
        "inverse": True,
    },

    CARD_OPEN: {
        "name": "FlashForge_Open",
        "fields": ["Pregunta", "Respuesta", "Orientación"],
        "qfmt": "<b>{{Pregunta}}</b><br><i style='color:#888'>{{Orientación}}</i>",
        "afmt": "{{Pregunta}}<hr><b>Respuesta sugerida:</b><br>{{Respuesta}}",
    },

    CARD_CLOZE: {
        "name": "FlashForge_Cloze",
        "fields": ["Texto"],
        "qfmt": "{{cloze:Texto}}",
        "afmt": "{{cloze:Texto}}",
        "cloze": True,
    },

    CARD_TWOCARD: {
        "name": "FlashForge_TwoCard",
        "fields": ["Término", "Definición", "Ejemplo"],
        "qfmt": ("<b>{{Término}}</b>"
                 "{{#Ejemplo}}<br><i>Ej: {{Ejemplo}}</i>{{/Ejemplo}}"),
        "afmt": ("<b>{{Término}}</b>"
                 "<hr><b>{{Definición}}</b>"
                 "{{#Ejemplo}}<br><i>Ej: {{Ejemplo}}</i>{{/Ejemplo}}"),
        "inverse": True,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# FSRS helper
# ──────────────────────────────────────────────────────────────────────────────

def fsrs_intervals_for_exam(exam_date: date, n_cards: int) -> list[dict]:
    """
    Given an exam_date and card count, return a list of
    {interval_days, target_date, label} dicts that represent
    optimal FSRS review waves before the exam.

    Strategy:
      - 1st wave: ~30 days before exam (long-term retention)
      - 2nd wave: ~14 days before
      - 3rd wave: ~7 days before
      - 4th wave: ~3 days before
      - 5th (cram): ~1 day before
    """
    waves = [
        (30, "Fase 1: Repaso amplio"),
        (14, "Fase 2: Consolidación"),
        ( 7, "Fase 3: Repaso medio"),
        ( 3, "Fase 4: Repaso intensivo"),
        ( 1, "Fase 5: Cram final"),
    ]

    intervals = []
    for days_before, label in waves:
        target = exam_date - timedelta(days=days_before)
        intervals.append({
            "interval_days": days_before,
            "target_date": target.isoformat(),
            "label": label,
        })
    return intervals


def compute_fsrs_params(desired_retention: float = 0.90,
                        exam_date: date | None = None) -> dict[str, Any]:
    """
    Build FSRS deck config params based on exam date.

    If no exam_date given, uses sensible defaults for daily reviews.
    """
    if exam_date is None:
        exam_date = date.today() + timedelta(days=60)

    days_to_exam = max(1, (exam_date - date.today()).days)

    retention = max(0.85, min(0.95, desired_retention))
    learning_steps = [1, 10, 60]
    graduating_interval = min(21, days_to_exam // 3)
    easy_interval = min(graduating_interval * 2, days_to_exam // 2)

    return {
        "desired_retention": retention,
        "learning_steps": learning_steps,
        "graduating_interval": graduating_interval,
        "easy_interval": easy_interval,
        "days_to_exam": days_to_exam,
        "exam_date": exam_date.isoformat(),
    }


def apply_fsrs_to_deck(deck_id: int, exam_date: date,
                       desired_retention: float = 0.90) -> dict[str, Any]:
    """Reschedule all cards in a deck to FSRS-optimal intervals for exam."""
    col = mw.col
    params = compute_fsrs_params(desired_retention, exam_date)

    card_ids = col.find_cards(f"deck:{deck_id}")
    if not card_ids:
        return {"cards": 0, "status": "no cards"}

    intervals = fsrs_intervals_for_exam(exam_date, len(card_ids))

    scheduled = 0
    for i, cid in enumerate(card_ids):
        card = col.get_card(cid)
        if card is None:
            continue
        target_interval = intervals[i % len(intervals)]["interval_days"]

        card.due = int((datetime.now() + timedelta(days=target_interval)).timestamp())
        card.ivl = target_interval
        card.queue = 2
        col.update_card(card)
        scheduled += 1

    col.save()
    return {
        "cards": len(card_ids),
        "scheduled": scheduled,
        "params": params,
        "intervals": intervals,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Note-type management
# ──────────────────────────────────────────────────────────────────────────────

def get_or_create_notetype(col, card_type: str) -> dict:
    """Get an existing FlashForge notetype or create it fresh."""
    defn = NOTE_DEFS.get(card_type)
    if not defn:
        raise ValueError(f"Unknown card type: {card_type}")

    for nt in col.models.all():
        if nt["name"] == defn["name"]:
            return nt

    nt = col.models.new(defn["name"])
    for field_name in defn["fields"]:
        col.models.add_field(nt, col.models.new_field(field_name))

    if defn.get("cloze"):
        tpl = col.models.new_template("Cloze")
        tpl["qfmt"] = defn["qfmt"]
        tpl["afmt"] = defn["afmt"]
        col.models.add_template(nt, tpl)
        nt["css"] = ".cloze { font-weight: bold; color: #2980b9; }"
    elif defn.get("inverse"):
        tpl_front = col.models.new_template("正向")
        tpl_front["qfmt"] = defn["qfmt"]
        tpl_front["afmt"] = defn["afmt"]
        col.models.add_template(nt, tpl_front)

        tpl_back = col.models.new_template("逆向")
        tpl_back["qfmt"] = defn["afmt"]
        tpl_back["afmt"] = defn["qfmt"]
        col.models.add_template(nt, tpl_back)
        nt["css"] = ".card { font-family: sans-serif; font-size: 20px; padding: 10px; }"
    else:
        tpl = col.models.new_template("Tarjeta")
        tpl["qfmt"] = defn["qfmt"]
        tpl["afmt"] = defn["afmt"]
        col.models.add_template(nt, tpl)
        nt["css"] = ".card { font-family: sans-serif; font-size: 20px; padding: 10px; }"

    col.models.add(nt)
    return nt


def ensure_all_notetypes(col) -> None:
    """Pre-create all FlashForge notetypes."""
    for card_type in NOTE_DEFS:
        get_or_create_notetype(col, card_type)


# ──────────────────────────────────────────────────────────────────────────────
# Deck management
# ──────────────────────────────────────────────────────────────────────────────

def create_deck_with_config(name: str,
                             card_type: str,
                             exam_date: date | None = None,
                             desired_retention: float = 0.90,
                             tags: list[str] | None = None) -> int:
    """
    Create a deck with a single notetype and FSRS config.
    Returns deck_id.
    """
    col = mw.col
    ensure_all_notetypes(col)

    deck = col.decks.new_deck()
    deck.name = name
    if tags:
        deck.tags = tags
    col.decks.add_deck(deck)
    deck_id = deck.id

    fsrs_params = compute_fsrs_params(desired_retention, exam_date)
    dconf = col.decks.config_dict_for_deck_id(deck_id)
    dconf["name"] = f"{name} (FSRS)"
    dconf["resched"] = True
    dconf["daily_limits"] = {"new": 30, "rev": 200}
    col.decks.update_conf(dconf)

    return deck_id


def add_card_to_deck(deck_id: int,
                     card_type: str,
                     fields: dict[str, str],
                     tags: list[str] | None = None) -> int | None:
    """Add a single card to a deck. Returns note_id or None."""
    col = mw.col
    nt = get_or_create_notetype(col, card_type)

    note = col.new_note(nt)

    field_map = {f["name"]: i for i, f in enumerate(nt["flds"])}
    for key, value in fields.items():
        if key in field_map:
            note.fields[field_map[key]] = value

    if tags:
        note.tags = tags

    col.add_note(note, deck_id)
    return note.id


def bulk_import_json(deck_id: int, card_type: str,
                     json_path: str,
                     progress_callback=None) -> dict[str, Any]:
    """
    Import flashcards from a JSON/YAML file.

    Expected JSON format:
    {
      "deck": "Nombre del Mazo",
      "exam_date": "2026-06-15",
      "cards": [
        { "front": "...", "back": "...", "tags": ["bio", "genetica"] },
        { "text": "...cloze text with [[h]]..." },  # cloze
        { "term": "...", "def": "...", "example": "..." }  # two_card
      ]
    }

    card_type field mappings:
      basic:      front → Pregunta, back → Respuesta
      basic_img:  front → Pregunta, img → Imagen (opcional), back → Respuesta
      inverse:    front → Frente, back → Reverso
      open:       front → Pregunta, hint → Orientación, back → Respuesta
      cloze:      text → Texto
      two_card:   term → Término, def → Definición, example → Ejemplo
    """
    with open(json_path, encoding="utf-8") as f:
        data = _json.load(f)

    col = mw.col
    ensure_all_notetypes(col)
    nt = get_or_create_notetype(col, card_type)

    cards_loaded = 0
    errors = []

    field_map = {f["name"]: i for i, f in enumerate(nt["flds"])}

    for i, item in enumerate(data.get("cards", [])):
        try:
            note = col.new_note(nt)

            if card_type == CARD_CLOZE:
                note.fields[field_map.get("Texto", 0)] = item.get("text", "")
            elif card_type == CARD_TWOCARD:
                note.fields[field_map.get("Término", 0)] = item.get("term", "")
                note.fields[field_map.get("Definición", 1)] = item.get("def", "")
                note.fields[field_map.get("Ejemplo", 2)] = item.get("example", "")
            else:
                note.fields[field_map.get("Pregunta", 0)] = (
                    item.get("front", item.get("pregunta", ""))
                )
                note.fields[field_map.get("Respuesta", 1)] = (
                    item.get("back", item.get("respuesta", ""))
                )
                if "img" in item:
                    note.fields[field_map.get("Imagen (opcional)", 1)] = item.get("img", "")

            note.tags = item.get("tags", [])
            col.add_note(note, deck_id)
            cards_loaded += 1

            if progress_callback:
                progress_callback(i + 1, len(data.get("cards", [])))

        except Exception as e:
            errors.append(f"Card {i}: {e}")

    col.save()
    return {
        "loaded": cards_loaded,
        "errors": errors,
        "total": len(data.get("cards", [])),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main Dialog: DeckBuilder
# ──────────────────────────────────────────────────────────────────────────────

class DeckBuilder(QDialog):
    """
    Main FlashForge dialog for rapid deck creation.
    Tabs: [Nuevo Mazo] [Importar JSON] [FSRS Config] [Explorar Mazo] [Añadir Tarjetas]
    """

    WINDOW_TITLE = "FlashForge - Constructor de Mazos PAU"
    MIN_SIZE = (820, 600)

    def __init__(self) -> None:
        super().__init__(mw)
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(*self.MIN_SIZE)

        self._current_deck_id: int | None = None
        self._current_deck_name: str = ""

        self._setup_ui()
        self.show()

    # ── UI Setup ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Title bar
        title = QLabel("FlashForge — Constructor de Mazos PAU")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #2c3e50; padding: 4px;")
        layout.addWidget(title)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_new_tab(), "Nuevo Mazo")
        self.tabs.addTab(self._build_import_tab(), "Importar JSON")
        self.tabs.addTab(self._build_fsrs_tab(), "FSRS Config")
        self.tabs.addTab(self._build_explore_tab(), "Explorar Mazo")
        self.tabs.addTab(self._build_bulk_add_tab(), "Añadir Tarjetas")
        layout.addWidget(self.tabs)

        # Status bar
        status_row = QHBoxLayout()
        self.status_lbl = QLabel("Listo")
        self.status_lbl.setStyleSheet("color: #555; font-size: 12px;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(300)
        self.progress_bar.setVisible(False)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch()
        status_row.addWidget(self.progress_bar)
        layout.addLayout(status_row)

        # Close button
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    # ── Tab: New Deck ─────────────────────────────────────────────────────────

    def _build_new_tab(self) -> QWidget:
        w = QWidget()
        ly = QFormLayout(w)
        ly.setLabelWidth(150)

        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("ej: Biología PAU 2026 - Genética")
        ly.addRow("Nombre del mazo:", self.new_name)

        self.card_type_combo = QComboBox()
        self.card_type_combo.addItems([
            "1. Básico (Pregunta → Respuesta)",
            "2. Básico con Imagen",
            "3. Inverso (Respuesta → Pregunta)",
            "4. Pregunta Abierta (sin respuesta fija)",
            "5. Cloze (Texto con huecos)",
            "6. Dos Caras (Término + Definición)",
        ])
        self.card_type_combo.setCurrentIndex(0)
        ly.addRow("Tipo de tarjeta:", self.card_type_combo)

        from PyQt6.QtCore import QDate
        self.exam_date_picker = QDateEdit()
        self.exam_date_picker.setCalendarPopup(True)
        self.exam_date_picker.setDate(QDate(2026, 6, 15))
        ly.addRow("Fecha del examen PAU:", self.exam_date_picker)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(80, 97)
        self.retention_spin.setSuffix(" %")
        self.retention_spin.setValue(90)
        self.retention_spin.setToolTip(
            "Porcentaje de retención objetivo (FSRS). "
            "90% es ideal para PAU."
        )
        ly.addRow("Retención objetivo:", self.retention_spin)

        self.new_tags = QLineEdit()
        self.new_tags.setPlaceholderText("biologia, genetica, pau (separadas por coma)")
        ly.addRow("Tags:", self.new_tags)

        info_lbl = QLabel(
            "<b>Nota:</b> Las tarjetas se crearán con el tipo seleccionado. "
            "Podrás añadir más tarjetas después."
        )
        info_lbl.setStyleSheet("color: #555; font-size: 12px; padding: 4px;")
        ly.addRow("", info_lbl)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("Vista Previa")
        preview_btn.clicked.connect(self._on_preview_notetype)
        create_btn = QPushButton("Crear Mazo")
        create_btn.setStyleSheet(
            "font-weight: bold; background: #27ae60; color: white; padding: 6px 16px;"
        )
        create_btn.clicked.connect(self._on_create_deck)
        btn_row.addWidget(preview_btn)
        btn_row.addStretch()
        btn_row.addWidget(create_btn)
        ly.addRow("", btn_row)

        return w

    # ── Tab: Import JSON ─────────────────────────────────────────────────────

    def _build_import_tab(self) -> QWidget:
        w = QWidget()
        ly = QFormLayout(w)
        ly.setLabelWidth(150)

        file_row = QHBoxLayout()
        self.json_path = QLineEdit()
        self.json_path.setPlaceholderText("Ruta al archivo .json o .anki-json")
        browse_btn = QPushButton("Examinar...")
        browse_btn.clicked.connect(self._on_browse_json)
        file_row.addWidget(self.json_path, 1)
        file_row.addWidget(browse_btn)
        ly.addRow("Archivo:", file_row)

        self.imp_type_combo = QComboBox()
        self.imp_type_combo.addItems([
            "Básico (pregunta/back)",
            "Básico con imagen",
            "Inverso",
            "Pregunta abierta",
            "Cloze",
            "Dos Caras",
        ])
        ly.addRow("Tipo de tarjeta:", self.imp_type_combo)

        deck_row = QHBoxLayout()
        self.imp_deck_combo = QComboBox()
        self._refresh_deck_list(self.imp_deck_combo)
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.clicked.connect(lambda: self._refresh_deck_list(self.imp_deck_combo))
        deck_row.addWidget(self.imp_deck_combo, 1)
        deck_row.addWidget(refresh_btn)
        ly.addRow("Mazo destino:", deck_row)

        sample = (
            "Ejemplo JSON:\n"
            '{"cards": [\n'
            '  {"front": "?Qué es la mitosis?", "back": "Divisin celular"},\n'
            '  {"front": "?Qu es la meiosis?", "back": "Div. celular reduccional"}\n'
            ']}\n\n'
            "Cloze: {\"text\": \"La clula [[hueco1]] es la unidad bsica...\"}\n"
            "DosCaras: {\"term\": \"Mitosis\", \"def\": \"Div. celular\"}"
        )
        sample_lbl = QLabel(sample)
        sample_lbl.setStyleSheet(
            "font-family: monospace; font-size: 11px; "
            "background: #f8f8f8; padding: 8px; border-radius: 4px;"
        )
        sample_lbl.setWordWrap(True)
        ly.addRow("Formato:", sample_lbl)

        import_btn = QPushButton("Importar")
        import_btn.setStyleSheet(
            "font-weight: bold; background: #2980b9; color: white; padding: 6px 16px;"
        )
        import_btn.clicked.connect(self._on_import_json)
        ly.addRow("", import_btn)

        return w

    # ── Tab: FSRS Config ─────────────────────────────────────────────────────

    def _build_fsrs_tab(self) -> QWidget:
        w = QWidget()
        ly = QFormLayout(w)
        ly.setLabelWidth(160)

        info = QLabel(
            "<b>Configura la optimización FSRS para tu examen PAU.</b><br><br>"
            "FSRS (Free Spaced Repetition Scheduler) calcula automáticamente "
            "los mejores intervalos de repaso para maximizar la retención "
            "el día del examen.<br><br>"
            "La <b>retención objetivo</b> indica qué porcentaje de tarjetas "
            "recordarás correctamente. 90% es ideal para PAU."
        )
        info.setStyleSheet(
            "font-size: 13px; padding: 8px; background: #eaf4fb; "
            "border-radius: 6px;"
        )
        info.setWordWrap(True)
        ly.addRow("Cómo funciona:", info)

        from PyQt6.QtCore import QDate
        self.fsrs_exam_date = QDateEdit()
        self.fsrs_exam_date.setCalendarPopup(True)
        self.fsrs_exam_date.setDate(QDate(2026, 6, 15))
        ly.addRow("Fecha examen PAU:", self.fsrs_exam_date)

        self.fsrs_retention = QSpinBox()
        self.fsrs_retention.setRange(80, 97)
        self.fsrs_retention.setSuffix(" %")
        self.fsrs_retention.setValue(90)
        ly.addRow("Retención objetivo:", self.fsrs_retention)

        deck_row = QHBoxLayout()
        self.fsrs_deck_combo = QComboBox()
        self._refresh_deck_list(self.fsrs_deck_combo)
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.clicked.connect(lambda: self._refresh_deck_list(self.fsrs_deck_combo))
        deck_row.addWidget(self.fsrs_deck_combo, 1)
        deck_row.addWidget(refresh_btn)
        ly.addRow("Mazo a optimizar:", deck_row)

        self.fsrs_preview = QTextEdit()
        self.fsrs_preview.setReadOnly(True)
        self.fsrs_preview.setMaximumHeight(180)
        self.fsrs_preview.setPlaceholderText(
            "Selecciona fecha y pulsa 'Calcular' para ver los intervalos."
        )
        ly.addRow("Intervalos proyectados:", self.fsrs_preview)

        btn_row = QHBoxLayout()
        calc_btn = QPushButton("Calcular")
        calc_btn.clicked.connect(self._on_fsrs_calculate)
        apply_btn = QPushButton("Aplicar a Mazo")
        apply_btn.setStyleSheet(
            "font-weight: bold; background: #8e44ad; color: white; padding: 6px 16px;"
        )
        apply_btn.clicked.connect(self._on_fsrs_apply)
        btn_row.addWidget(calc_btn)
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        ly.addRow("", btn_row)

        return w

    # ── Tab: Explore Deck ───────────────────────────────────────────────────

    def _build_explore_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)

        toolbar = QHBoxLayout()
        self.explore_deck_combo = QComboBox()
        self._refresh_deck_list(self.explore_deck_combo)
        self.explore_deck_combo.currentIndexChanged.connect(
            self._on_explore_deck_changed
        )
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.clicked.connect(
            lambda: self._refresh_deck_list(self.explore_deck_combo)
        )
        toolbar.addWidget(QLabel("Mazo:"))
        toolbar.addWidget(self.explore_deck_combo, 1)
        toolbar.addWidget(refresh_btn)
        ly.addLayout(toolbar)

        self.explore_output = QTextEdit()
        self.explore_output.setReadOnly(True)
        self.explore_output.setPlaceholderText(
            "Selecciona un mazo para ver su contenido y estadísticas FSRS."
        )
        ly.addWidget(self.explore_output, 1)

        return w

    # ── Tab: Bulk Add ────────────────────────────────────────────────────────

    def _build_bulk_add_tab(self) -> QWidget:
        w = QWidget()
        ly = QVBoxLayout(w)

        top = QHBoxLayout()
        self.bulk_deck_combo = QComboBox()
        self._refresh_deck_list(self.bulk_deck_combo)
        top.addWidget(QLabel("Mazo:"))
        top.addWidget(self.bulk_deck_combo, 1)
        refresh_btn = QPushButton("Actualizar")
        refresh_btn.clicked.connect(
            lambda: self._refresh_deck_list(self.bulk_deck_combo)
        )
        top.addWidget(refresh_btn)
        ly.addLayout(top)

        self.bulk_type_lbl = QLabel("Tipo de tarjeta: (selecciona un mazo primero)")
        ly.addWidget(self.bulk_type_lbl)

        self.bulk_input = QPlainTextEdit()
        self.bulk_input.setPlaceholderText(
            "Escribe una tarjeta por línea, usando TAB como separador.\n\n"
            "Ejemplo (Básico):\n"
            "?Qu es el ADN?\tMolcula portadora de la informacin gentica\n"
            "?Qu es un gen?\tSecuencia de ADN que codifica una protena\n\n"
            "Ejemplo (Cloze):\n"
            "La [[mitosis]] es la divisin del ncleo celular\n\n"
            "Ejemplo (Dos Caras):\n"
            "Mitosis\tDivisin celular\tProduce 2 clulas idnticas"
        )
        ly.addWidget(self.bulk_input, 1)

        delim_lbl = QLabel(
            "Separador de campos: TAB (copia desde una tabla Excel/Google Sheets)"
        )
        delim_lbl.setStyleSheet("color: #666; font-size: 12px;")
        ly.addWidget(delim_lbl)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Limpiar")
        clear_btn.clicked.connect(self.bulk_input.clear)
        add_btn = QPushButton("Añadir tarjetas")
        add_btn.setStyleSheet(
            "font-weight: bold; background: #27ae60; color: white; padding: 6px 16px;"
        )
        add_btn.clicked.connect(self._on_bulk_add)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(add_btn)
        ly.addLayout(btn_row)

        return w

    # ── Event Handlers ─────────────────────────────────────────────────────

    def _card_type_key(self, idx: int) -> str:
        keys = [
            CARD_BASIC, CARD_BASIC_IMG, CARD_INVERSE,
            CARD_OPEN, CARD_CLOZE, CARD_TWOCARD,
        ]
        return keys[idx]

    def _on_preview_notetype(self) -> None:
        idx = self.card_type_combo.currentIndex()
        key = self._card_type_key(idx)
        defn = NOTE_DEFS.get(key, {})
        fields = defn.get("fields", [])
        templates = defn.get("qfmt", "")

        showInfo(
            f"<b>Nota tipo:</b> {defn.get('name', key)}\n\n"
            f"<b>Campos:</b><br>- " + "<br>- ".join(fields) +
            (f"<br><br><b>Template pregunta:</b><br><code>{templates[:200]}</code>"
             if templates else ""),
            title="Vista Previa — FlashForge",
        )

    def _on_create_deck(self) -> None:
        name = self.new_name.text().strip()
        if not name:
            showWarning("Ponle un nombre al mazo.", parent=self)
            return

        from PyQt6.QtCore import QDate
        exam_qdate = self.exam_date_picker.date()
        exam_dt = date(exam_qdate.year(), exam_qdate.month(), exam_qdate.day())
        retention = self.retention_spin.value() / 100.0
        card_type_key = self._card_type_key(self.card_type_combo.currentIndex())
        tags = [t.strip() for t in self.new_tags.text().split(",") if t.strip()]

        try:
            deck_id = create_deck_with_config(
                name=name,
                card_type=card_type_key,
                exam_date=exam_dt,
                desired_retention=retention,
                tags=tags,
            )
            self._current_deck_id = deck_id
            self._current_deck_name = name

            tooltip(f"Mazo '{name}' creado", parent=self)
            self.status_lbl.setText(f"Mazo creado: {name} (id={deck_id})")

            self._refresh_deck_list(self.imp_deck_combo)
            self._refresh_deck_list(self.fsrs_deck_combo)
            self._refresh_deck_list(self.explore_deck_combo)
            self._refresh_deck_list(self.bulk_deck_combo)

            self.tabs.setCurrentIndex(4)

        except Exception as e:
            showWarning(f"Error creando mazo:\n{e}", parent=self)

    def _on_browse_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona archivo JSON", "",
            "JSON (*.json *.anki-json);;All files (*)"
        )
        if path:
            self.json_path.setText(path)

    def _on_import_json(self) -> None:
        path = self.json_path.text().strip()
        if not path:
            showWarning("Selecciona un archivo JSON.", parent=self)
            return

        deck_combo: QComboBox = self.imp_deck_combo
        deck_id_str = deck_combo.currentData()
        if not deck_id_str:
            showWarning("Selecciona un mazo destino.", parent=self)
            return

        try:
            with open(path, encoding="utf-8") as f:
                _ = _json.load(f)
        except Exception as e:
            showWarning(f"No pude leer el archivo JSON:\n{e}", parent=self)
            return

        card_type_idx = self.imp_type_combo.currentIndex()
        card_type_key = self._card_type_key(card_type_idx)

        self.progress_bar.setVisible(True)
        # Get card count for progress
        try:
            with open(path, encoding="utf-8") as f:
                data_preview = _json.load(f)
            total = len(data_preview.get("cards", []))
        except Exception:
            total = 100
        self.progress_bar.setMaximum(total)

        def progress(current: int, total_cards: int) -> None:
            self.progress_bar.setValue(current)

        try:
            result = bulk_import_json(
                deck_id=int(deck_id_str),
                card_type=card_type_key,
                json_path=path,
                progress_callback=progress,
            )
            self.progress_bar.setVisible(False)
            tooltip(f"{result['loaded']} tarjetas importadas", parent=self)
            self.status_lbl.setText(
                f"Importadas {result['loaded']}/{result['total']} — "
                f"{len(result['errors'])} errores"
            )
            if result["errors"]:
                showWarning(
                    f"Algunos errores:\n" + "\n".join(result["errors"][:5]),
                    parent=self,
                )
        except Exception as e:
            self.progress_bar.setVisible(False)
            showWarning(f"Error importando:\n{e}", parent=self)

    def _on_fsrs_calculate(self) -> None:
        from PyQt6.QtCore import QDate
        exam_qdate = self.fsrs_exam_date.date()
        exam_dt = date(exam_qdate.year(), exam_qdate.month(), exam_qdate.day())
        retention = self.fsrs_retention.value() / 100.0

        params = compute_fsrs_params(retention, exam_dt)
        intervals = fsrs_intervals_for_exam(exam_dt, 100)

        html = "<b>Parámetros FSRS:</b><br>"
        html += f"Retention objetivo: {params['desired_retention']:.0%}<br>"
        html += f"Días hasta examen: {params['days_to_exam']}<br>"
        html += f"Graduating interval: {params['graduating_interval']} días<br>"
        html += f"Easy interval: {params['easy_interval']} días<br>"
        html += "<br><b>Repasos proyectados:</b><br>"
        for iv in intervals:
            html += (
                f"&bull; {iv['label']} &mdash; "
                f"{iv['target_date']} (hace {iv['interval_days']} días)<br>"
            )

        self.fsrs_preview.setHtml(html)

    def _on_fsrs_apply(self) -> None:
        from PyQt6.QtCore import QDate
        exam_qdate = self.fsrs_exam_date.date()
        exam_dt = date(exam_qdate.year(), exam_qdate.month(), exam_qdate.day())
        retention = self.fsrs_retention.value() / 100.0

        deck_combo: QComboBox = self.fsrs_deck_combo
        deck_id_str = deck_combo.currentData()
        if not deck_id_str:
            showWarning("Selecciona un mazo.", parent=self)
            return

        try:
            result = apply_fsrs_to_deck(int(deck_id_str), exam_dt, retention)
            if result["cards"] == 0:
                showWarning("El mazo no tiene tarjetas.", parent=self)
                return

            tooltip(
                f"FSRS aplicado a {result['scheduled']} tarjetas",
                parent=self,
            )
            self.status_lbl.setText(
                f"FSRS: {result['scheduled']} tarjetas reprogramadas para {exam_dt}"
            )

        except Exception as e:
            showWarning(f"Error aplicando FSRS:\n{e}", parent=self)

    def _on_explore_deck_changed(self) -> None:
        deck_combo: QComboBox = self.explore_deck_combo
        deck_id_str = deck_combo.currentData()
        if not deck_id_str:
            self.explore_output.clear()
            return

        deck_id = int(deck_id_str)
        col = mw.col
        deck = col.decks.get(deck_id)
        if not deck:
            return

        card_ids = col.find_cards(f"deck:{deck_id}")
        note_ids = set()
        for cid in card_ids:
            c = col.get_card(cid)
            if c:
                note_ids.add(c.nid)

        new_count = sum(
            1 for cid in card_ids
            if col.get_card(cid) and col.get_card(cid).queue == 0
        )
        lrnd_count = sum(
            1 for cid in card_ids
            if col.get_card(cid) and col.get_card(cid).queue == 1
        )
        rev_count = sum(
            1 for cid in card_ids
            if col.get_card(cid) and col.get_card(cid).queue == 2
        )

        html = f"<b>Mazo:</b> {deck['name']}<br>"
        html += f"<b>Tarjetas totales:</b> {len(card_ids)}<br>"
        html += f"<b>Notas únicas:</b> {len(note_ids)}<br>"
        html += "<br><b>Cola:</b><br>"
        html += f"&bull; Nuevas: {new_count}<br>"
        html += f"&bull; Aprendiendo: {lrnd_count}<br>"
        html += f"&bull; Revisión: {rev_count}<br>"

        self.explore_output.setHtml(html)

    def _on_bulk_add(self) -> None:
        deck_combo: QComboBox = self.bulk_deck_combo
        deck_id_str = deck_combo.currentData()
        if not deck_id_str:
            showWarning("Selecciona un mazo primero.", parent=self)
            return

        deck_id = int(deck_id_str)
        text = self.bulk_input.toPlainText()
        if not text.strip():
            showWarning("Escribe tarjetas en el área de texto.", parent=self)
            return

        col = mw.col

        deck_name = deck_combo.currentText().lower()
        if "cloze" in deck_name or "hueco" in deck_name:
            card_type_key = CARD_CLOZE
        elif "dos" in deck_name or "vocab" in deck_name or "termino" in deck_name:
            card_type_key = CARD_TWOCARD
        elif "img" in deck_name or "imagen" in deck_name:
            card_type_key = CARD_BASIC_IMG
        elif "open" in deck_name or "abierta" in deck_name:
            card_type_key = CARD_OPEN
        else:
            card_type_key = CARD_BASIC

        try:
            nt = get_or_create_notetype(col, card_type_key)
            field_map = {f["name"]: i for i, f in enumerate(nt["flds"])}

            added = 0
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                note = col.new_note(nt)

                if card_type_key == CARD_CLOZE:
                    note.fields[field_map.get("Texto", 0)] = parts[0]
                elif card_type_key == CARD_TWOCARD:
                    note.fields[field_map.get("Término", 0)] = parts[0]
                    note.fields[field_map.get("Definición", 1)] = (
                        parts[1] if len(parts) > 1 else ""
                    )
                    note.fields[field_map.get("Ejemplo", 2)] = (
                        parts[2] if len(parts) > 2 else ""
                    )
                else:
                    note.fields[field_map.get("Pregunta", 0)] = parts[0]
                    note.fields[field_map.get("Respuesta", 1)] = (
                        parts[1] if len(parts) > 1 else ""
                    )

                col.add_note(note, deck_id)
                added += 1

            col.save()
            tooltip(f"{added} tarjetas añadidas", parent=self)
            self.status_lbl.setText(
                f"{added} tarjetas añadidas a '{deck_combo.currentText()}'"
            )
            self.bulk_input.clear()

        except Exception as e:
            showWarning(f"Error añadiendo tarjetas:\n{e}", parent=self)

    # ── Utility ──────────────────────────────────────────────────────────────

    def _refresh_deck_list(self, combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— Sin seleccionar —", None)
        if mw and mw.col:
            for deck in mw.col.decks.all():
                combo.addItem(deck["name"], str(deck["id"]))
        combo.blockSignals(False)


# ──────────────────────────────────────────────────────────────────────────────
# Menu + Hooks
# ──────────────────────────────────────────────────────────────────────────────

_flashforge_dialog: DeckBuilder | None = None


def open_flashforge() -> None:
    global _flashforge_dialog
    if _flashforge_dialog is not None:
        _flashforge_dialog.close()
        _flashforge_dialog.deleteLater()
    _flashforge_dialog = DeckBuilder()


def on_profile_open() -> None:
    if mw and mw.col:
        try:
            ensure_all_notetypes(mw.col)
        except Exception as e:
            print(f"[FlashForge] Warning: could not pre-create notetypes: {e}")


def on_main_window_did_init() -> None:
    if mw is None:
        return
    menu = mw.form.menuTools
    action = menu.addAction("FlashForge — Constructor de Mazos PAU")
    action.triggered.connect(open_flashforge)


gui_hooks.profile_did_open.append(on_profile_open)
gui_hooks.main_window_did_init.append(on_main_window_did_init)