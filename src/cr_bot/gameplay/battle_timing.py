from __future__ import annotations

import os
import re
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


DIRECT_TIME_STAGE_ENV = "CR_DIRECT_TIME_STAGE"
DIRECT_ELIXIR_STAGE_ENV = "CR_DIRECT_ELIXIR_STAGE"

# User-adjustable image regions.
# Fill these coordinates in the same x,y,w,h format that OpenCV crops use.
BATTLE_TIME_REGION_ENV = "CR_BATTLE_TIME_REGION"
BATTLE_OVERTIME_REGION_ENV = "CR_BATTLE_OVERTIME_REGION"
BATTLE_ANCHOR_REGION_ENV = "CR_BATTLE_ANCHOR_REGION"
BATTLE_TIME_STABLE_FRAMES_ENV = "CR_BATTLE_TIME_STABLE_FRAMES"
BATTLE_TIME_FAIL_HOLD_FRAMES_ENV = "CR_BATTLE_TIME_FAIL_HOLD_FRAMES"
BATTLE_TIME_MIN_CONFIDENCE_ENV = "CR_BATTLE_TIME_MIN_CONFIDENCE"

TIME_STAGE_ALIASES = {
    "opening": "opening",
    "early": "opening",
    "midgame": "midgame",
    "mid": "midgame",
    "late": "late",
    "overtime": "overtime",
    "ot": "overtime",
}

ELIXIR_STAGE_ALIASES = {
    "single": "single",
    "1x": "single",
    "double": "double",
    "2x": "double",
    "triple": "triple",
    "3x": "triple",
}

TIME_STAGE_CHOICES = tuple(dict.fromkeys(TIME_STAGE_ALIASES.values()))
ELIXIR_STAGE_CHOICES = tuple(dict.fromkeys(ELIXIR_STAGE_ALIASES.values()))


def _normalize_stage(value, aliases):
    if value is None:
        return None

    key = "".join(ch for ch in str(value).strip().lower() if ch.isalnum())
    return aliases.get(key)


def normalize_time_stage(value):
    return _normalize_stage(value, TIME_STAGE_ALIASES)


def normalize_elixir_stage(value):
    return _normalize_stage(value, ELIXIR_STAGE_ALIASES)


def _read_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _read_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_region(value):
    if value is None:
        return None

    parts = [piece.strip() for piece in str(value).split(",") if piece.strip()]
    if len(parts) != 4:
        return None

    try:
        x, y, w, h = [int(float(piece)) for piece in parts]
    except ValueError:
        return None

    if w <= 0 or h <= 0:
        return None

    return x, y, w, h


def _crop_region(image, region):
    if image is None or region is None:
        return None

    x, y, w, h = region
    if w <= 0 or h <= 0:
        return None

    y1 = max(0, y)
    x1 = max(0, x)
    y2 = min(image.shape[0], y + h)
    x2 = min(image.shape[1], x + w)
    if y2 <= y1 or x2 <= x1:
        return None
    return image[y1:y2, x1:x2]


@dataclass(frozen=True)
class BattleTimingSelection:
    direct_battle: bool = False
    time_stage: str | None = None
    elixir_stage: str | None = None

    @property
    def start_elixir_stage(self):
        return self.elixir_stage or "single"

    @property
    def should_extend_single_stage(self):
        return self.start_elixir_stage == "single" and self.time_stage in {None, "opening"}

    def describe(self):
        time_stage = self.time_stage or "auto"
        elixir_stage = self.elixir_stage or "auto"
        return f"time_stage={time_stage}, elixir_stage={elixir_stage}"


@dataclass(frozen=True)
class BattleTimeVisionConfig:
    # User-adjustable: remaining time / countdown text region.
    time_region: tuple[int, int, int, int] | None
    # User-adjustable: overtime marker region.
    overtime_region: tuple[int, int, int, int] | None
    # User-adjustable: battle UI anchor region.
    battle_anchor_region: tuple[int, int, int, int] | None
    # User-adjustable: how many continuous frames must agree before a new time phase is committed.
    stable_frames: int = 3
    # User-adjustable: how many failed reads are tolerated while holding the last confirmed phase.
    fail_hold_frames: int = 12
    # Heuristic: minimum OCR confidence for accepting a parsed timer string.
    min_confidence: float = 0.35
    # Heuristic: minimum ratio for the anchor region to count as battle UI.
    anchor_threshold: float = 0.06
    # Heuristic: minimum ratio for the overtime marker region to count as overtime.
    overtime_threshold: float = 0.08
    debug: bool = False

    @classmethod
    def from_env(cls, debug=False):
        return cls(
            time_region=_parse_region(os.getenv(BATTLE_TIME_REGION_ENV)),
            overtime_region=_parse_region(os.getenv(BATTLE_OVERTIME_REGION_ENV)),
            battle_anchor_region=_parse_region(os.getenv(BATTLE_ANCHOR_REGION_ENV)),
            stable_frames=max(1, _read_int(os.getenv(BATTLE_TIME_STABLE_FRAMES_ENV), 3)),
            fail_hold_frames=max(0, _read_int(os.getenv(BATTLE_TIME_FAIL_HOLD_FRAMES_ENV), 12)),
            min_confidence=min(1.0, max(0.0, _read_float(os.getenv(BATTLE_TIME_MIN_CONFIDENCE_ENV), 0.35))),
            debug=debug,
        )


@dataclass(frozen=True)
class BattleTimeReading:
    stage: str | None
    source: str
    raw_text: str
    confidence: float
    confirmed: bool
    battle_anchor_score: float = 0.0
    overtime_score: float = 0.0
    failure_count: int = 0
    reason: str = ""


class BattleTimeVision:
    def __init__(self, config=None, debug=False):
        self.config = config or BattleTimeVisionConfig.from_env(debug=debug)
        self._confirmed_stage = None
        self._pending_stage = None
        self._pending_hits = 0
        self._failure_count = 0
        self._last_text = ""
        self._template_bank = self._build_template_bank()

    def _load_font(self, size):
        font_paths = [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
        ]
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _render_symbol_template(self, symbol, font_size):
        canvas = Image.new("L", (96, 96), 0)
        draw = ImageDraw.Draw(canvas)
        font = self._load_font(font_size)
        bbox = draw.textbbox((0, 0), symbol, font=font)
        if bbox is None:
            return None

        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        x = max(0, (96 - width) // 2 - bbox[0])
        y = max(0, (96 - height) // 2 - bbox[1])
        draw.text((x, y), symbol, fill=255, font=font)
        mask = np.array(canvas, dtype=np.uint8)
        _, mask = cv2.threshold(mask, 0, 255, cv2.THRESH_BINARY)
        points = cv2.findNonZero(mask)
        if points is None:
            return None

        x, y, w, h = cv2.boundingRect(points)
        if w <= 0 or h <= 0:
            return None
        return mask[y:y + h, x:x + w]

    def _build_template_bank(self):
        bank = {}
        for symbol in "0123456789:":
            templates = []
            for font_size in (40, 48, 54, 60, 66):
                template = self._render_symbol_template(symbol, font_size)
                if template is not None:
                    templates.append(template)
            if templates:
                bank[symbol] = templates
        return bank

    def _preprocess_text_region(self, region):
        if region is None or region.size == 0:
            return []

        upscaled = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        variants = []
        for thresh_type in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
            _, mask = cv2.threshold(gray, 0, 255, thresh_type + cv2.THRESH_OTSU)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            variants.append(mask)

        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        adaptive_inv = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            11,
        )
        variants.extend([adaptive, adaptive_inv])

        scored = []
        for mask in variants:
            score = self._mask_quality(mask)
            scored.append((score, mask))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [mask for _, mask in scored[:2]]

    def _mask_quality(self, mask):
        if mask is None or mask.size == 0:
            return 0.0

        foreground_ratio = float(np.count_nonzero(mask)) / float(mask.size)
        if foreground_ratio <= 0.001:
            return 0.0

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filtered = 0
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < 150:
                continue
            if h < mask.shape[0] * 0.08:
                continue
            filtered += 1

        return min(1.0, foreground_ratio + (filtered * 0.08))

    def _extract_boxes(self, mask):
        if mask is None or mask.size == 0:
            return []

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        height, width = mask.shape[:2]
        min_area = max(120, int(height * width * 0.001))
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < min_area:
                continue
            if h < max(12, int(height * 0.14)):
                continue
            boxes.append((x, y, w, h))

        boxes.sort(key=lambda item: item[0])
        return self._merge_boxes(boxes)

    def _merge_boxes(self, boxes):
        if not boxes:
            return []

        merged = [list(boxes[0])]
        for x, y, w, h in boxes[1:]:
            last = merged[-1]
            gap = x - (last[0] + last[2])
            last_height = max(last[3], h)
            if gap <= max(6, int(last_height * 0.18)):
                new_x = min(last[0], x)
                new_y = min(last[1], y)
                new_x2 = max(last[0] + last[2], x + w)
                new_y2 = max(last[1] + last[3], y + h)
                merged[-1] = [new_x, new_y, new_x2 - new_x, new_y2 - new_y]
            else:
                merged.append([x, y, w, h])
        return [tuple(box) for box in merged]

    def _normalize_symbol(self, symbol_mask):
        if symbol_mask is None or symbol_mask.size == 0:
            return None

        points = cv2.findNonZero(symbol_mask)
        if points is None:
            return None

        x, y, w, h = cv2.boundingRect(points)
        symbol_mask = symbol_mask[y:y + h, x:x + w]
        if symbol_mask.size == 0:
            return None

        target_size = (64, 64)
        resized = cv2.resize(symbol_mask, target_size, interpolation=cv2.INTER_AREA)
        _, resized = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return resized

    def _classify_symbol(self, symbol_mask):
        normalized = self._normalize_symbol(symbol_mask)
        if normalized is None:
            return None, 0.0

        best_symbol = None
        best_score = 0.0
        for symbol, templates in self._template_bank.items():
            for template in templates:
                candidate = cv2.resize(normalized, (template.shape[1], template.shape[0]), interpolation=cv2.INTER_AREA)
                if candidate.shape != template.shape:
                    continue
                diff = np.mean(np.abs(candidate.astype(np.float32) - template.astype(np.float32))) / 255.0
                score = max(0.0, 1.0 - float(diff))
                if score > best_score:
                    best_score = score
                    best_symbol = symbol

        return best_symbol, best_score

    def _recognize_text(self, region):
        candidates = self._preprocess_text_region(region)
        best_text = ""
        best_score = 0.0

        for mask in candidates:
            boxes = self._extract_boxes(mask)
            if not boxes:
                continue

            pieces = []
            scores = []
            for x, y, w, h in boxes:
                symbol_mask = mask[y:y + h, x:x + w]
                symbol, symbol_score = self._classify_symbol(symbol_mask)
                if symbol is None:
                    continue
                pieces.append(symbol)
                scores.append(symbol_score)

            if not pieces:
                continue

            text = "".join(pieces)
            score = float(np.mean(scores)) if scores else 0.0
            if len(text) >= 3 and score >= best_score:
                best_text = text
                best_score = score

        return best_text, best_score

    def _battle_anchor_score(self, screenshot):
        region = _crop_region(screenshot, self.config.battle_anchor_region)
        if region is None or region.size == 0:
            return 0.0

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edge_ratio = float(np.count_nonzero(cv2.Canny(gray, 50, 150))) / float(gray.size)
        bright_ratio = float(np.count_nonzero(gray >= 135)) / float(gray.size)
        return min(1.0, edge_ratio * 2.2 + bright_ratio * 0.8)

    def _overtime_score(self, screenshot):
        region = _crop_region(screenshot, self.config.overtime_region)
        if region is None or region.size == 0:
            return 0.0

        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        pink_mask = (
            (hsv[:, :, 0] >= 140)
            & (hsv[:, :, 0] <= 179)
            & (hsv[:, :, 1] >= 70)
            & (hsv[:, :, 2] >= 70)
        )
        return float(np.count_nonzero(pink_mask)) / float(pink_mask.size)

    def _parse_timer_text(self, text):
        if not text:
            return None

        normalized = (
            str(text)
            .replace("?", ":")
            .replace(",", ":")
            .replace(";", ":")
            .replace(" ", "")
        )
        normalized = re.sub(r"[^0-9:]", "", normalized)
        match = re.search(r"(\d{1,2})\s*[:]\s*(\d{2})", normalized)
        if match is None:
            return None

        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return minutes, seconds

    def _classify_stage(self, parsed_time, overtime_score):
        if overtime_score >= self.config.overtime_threshold:
            return "triple", "overtime_marker"

        if parsed_time is None:
            return None, "time_parse_failed"

        minutes, seconds = parsed_time
        total_seconds = minutes * 60 + seconds
        if total_seconds > 60:
            return "single", "timer"
        return "double", "timer"

    def observe(self, screenshot, battle_active=False):
        anchor_score = self._battle_anchor_score(screenshot)
        if not battle_active:
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source="battle_inactive",
                raw_text=self._last_text,
                confidence=0.0,
                confirmed=False,
                battle_anchor_score=anchor_score,
                overtime_score=0.0,
                failure_count=self._failure_count,
                reason="battle_inactive",
            )

        if self.config.battle_anchor_region is not None and anchor_score < self.config.anchor_threshold:
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source="anchor_weak",
                raw_text=self._last_text,
                confidence=0.0,
                confirmed=False,
                battle_anchor_score=anchor_score,
                overtime_score=0.0,
                failure_count=self._failure_count,
                reason="battle_anchor_weak",
            )

        region = _crop_region(screenshot, self.config.time_region)
        if region is None or region.size == 0:
            self._failure_count += 1
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source="time_region_missing",
                raw_text=self._last_text,
                confidence=0.0,
                confirmed=False,
                battle_anchor_score=anchor_score,
                overtime_score=0.0,
                failure_count=self._failure_count,
                reason="time_region_missing",
            )

        parsed_text, text_confidence = self._recognize_text(region)
        parsed_time = self._parse_timer_text(parsed_text)
        overtime_score = self._overtime_score(screenshot)
        stage_candidate, source = self._classify_stage(parsed_time, overtime_score)

        if stage_candidate is None or text_confidence < self.config.min_confidence:
            self._failure_count += 1
            if self.config.debug:
                print(
                    f"time vision failed: text={parsed_text!r}, confidence={text_confidence:.3f}, "
                    f"failures={self._failure_count}"
                )
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source="ocr_failed",
                raw_text=parsed_text,
                confidence=text_confidence,
                confirmed=False,
                battle_anchor_score=anchor_score,
                overtime_score=overtime_score,
                failure_count=self._failure_count,
                reason="ocr_failed",
            )

        self._failure_count = 0
        self._last_text = parsed_text

        if self._confirmed_stage is None:
            self._confirmed_stage = stage_candidate
            self._pending_stage = None
            self._pending_hits = 0
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source=source,
                raw_text=parsed_text,
                confidence=text_confidence,
                confirmed=True,
                battle_anchor_score=anchor_score,
                overtime_score=overtime_score,
                failure_count=self._failure_count,
                reason="initial_confirm",
            )

        if stage_candidate == self._confirmed_stage:
            self._pending_stage = None
            self._pending_hits = 0
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source=source,
                raw_text=parsed_text,
                confidence=text_confidence,
                confirmed=True,
                battle_anchor_score=anchor_score,
                overtime_score=overtime_score,
                failure_count=self._failure_count,
                reason="stable_confirm",
            )

        if self._pending_stage != stage_candidate:
            self._pending_stage = stage_candidate
            self._pending_hits = 1
        else:
            self._pending_hits += 1

        if self._pending_hits >= self.config.stable_frames:
            old_stage = self._confirmed_stage
            self._confirmed_stage = stage_candidate
            self._pending_stage = None
            self._pending_hits = 0
            return BattleTimeReading(
                stage=self._confirmed_stage,
                source=source,
                raw_text=parsed_text,
                confidence=text_confidence,
                confirmed=True,
                battle_anchor_score=anchor_score,
                overtime_score=overtime_score,
                failure_count=self._failure_count,
                reason=f"confirmed_transition:{old_stage}->{self._confirmed_stage}",
            )

        return BattleTimeReading(
            stage=self._confirmed_stage,
            source=source,
            raw_text=parsed_text,
            confidence=text_confidence,
            confirmed=False,
            battle_anchor_score=anchor_score,
            overtime_score=overtime_score,
            failure_count=self._failure_count,
            reason="pending_transition",
        )


def read_direct_battle_selection():
    return BattleTimingSelection(
        direct_battle=True,
        time_stage=normalize_time_stage(os.getenv(DIRECT_TIME_STAGE_ENV)),
        elixir_stage=normalize_elixir_stage(os.getenv(DIRECT_ELIXIR_STAGE_ENV)),
    )
