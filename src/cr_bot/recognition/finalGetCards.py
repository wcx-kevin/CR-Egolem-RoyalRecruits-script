import os
import subprocess
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import cv2
import numpy as np
import uiautomator2 as u2

from cr_bot.config.decks import get_deck_definition
from cr_bot.config.device_config import DEVICE_ID, PACKAGE_NAME, adb_command
from cr_bot.core.card_config import card_key, get_card_pool, get_card_template_groups
from cr_bot.core.comCycle import CRCardCycle
from cr_bot.paths import (
    get_cards_dir,
    get_cards_full_dir,
    get_legacy_cards_dir,
    get_legacy_oldcards_dir,
)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class CRCardRecognizer:
    """Clash Royale card recognizer."""

    def __init__(
        self,
        device_id=None,
        vote_frames=3,
        vote_interval=0.08,
        unknown_retry_attempts=3,
        unknown_retry_interval=0.25,
        hand_accept_threshold=0.44,
        hand_margin_threshold=0.045,
        next_accept_threshold=0.40,
        next_margin_threshold=0.04,
    ):
        try:
            self.device_id = device_id or DEVICE_ID
            self.deck = get_deck_definition()

            self.cards_dir = os.fspath(get_cards_dir(self.deck.id))
            self.cards_full_dir = os.fspath(get_cards_full_dir(self.deck.id))
            os.makedirs(self.cards_dir, exist_ok=True)
            os.makedirs(self.cards_full_dir, exist_ok=True)

            self.template_sources = {
                "cards": {
                    "dir": self.cards_dir,
                    "mode": "portrait",
                    "weight": 0.22,
                },
                "cards_full": {
                    "dir": self.cards_full_dir,
                    "mode": "full",
                    "weight": 0.78,
                },
            }
            legacy_cards_path = get_legacy_cards_dir(self.deck.id)
            legacy_oldcards_path = get_legacy_oldcards_dir(self.deck.id)
            legacy_cards_dir = os.fspath(legacy_cards_path) if legacy_cards_path is not None else None
            legacy_oldcards_dir = os.fspath(legacy_oldcards_path) if legacy_oldcards_path is not None else None
            if legacy_cards_dir and os.path.isdir(legacy_cards_dir):
                self.template_sources["legacy_cards"] = {
                    "dir": legacy_cards_dir,
                    "mode": "full",
                    "weight": 0.68,
                }
            if legacy_oldcards_dir and os.path.isdir(legacy_oldcards_dir):
                self.template_sources["legacy_oldcards"] = {
                    "dir": legacy_oldcards_dir,
                    "mode": "full",
                    "weight": 0.56,
                }

            self.normalized_card_size = (120, 150)
            self.card_frame_crop = (0.06, 0.03, 0.94, 0.97)
            self.full_card_focus_crop = (0.06, 0.02, 0.94, 0.82)
            self.hand_accept_threshold = hand_accept_threshold
            self.hand_margin_threshold = hand_margin_threshold
            self.next_accept_threshold = next_accept_threshold
            self.next_margin_threshold = next_margin_threshold
            self.strong_match_bonus = 0.08
            self.position_bias = 0.04
            self.full_source_accept_threshold = 0.50
            self.full_source_margin_threshold = 0.025
            self.disabled_saturation_threshold = 0.30
            self.disabled_accept_bonus = 0.08
            self.disabled_margin_bonus = 0.03
            self.disabled_full_source_accept_threshold = 0.39
            self.rerank_score_gap = 0.02
            self.disabled_template_cache = {}
            self.vote_frames = max(1, int(vote_frames))
            self.vote_interval = max(0.0, float(vote_interval))
            self.unknown_retry_attempts = max(0, int(unknown_retry_attempts))
            self.unknown_retry_interval = max(0.0, float(unknown_retry_interval))

            self.setup_regions()
            self.load_templates()
            self.cycle = CRCardCycle()

            self.d = u2.connect(self.device_id)
            self.width, self.height = self.d.window_size()
        except Exception as e:
            print(f"初始化卡牌识别器失败: {e}")
            self.d = None

    def setup_regions(self):
        self.card_regions = [
            (280, 2100, 300, 330),
            (580, 2100, 300, 330),
            (850, 2100, 300, 330),
            (1120, 2100, 300, 330),
        ]
        self.next_card_region = (80, 2390, 120, 150)

    def load_templates(self):
        card_pool = get_card_pool(self.deck.id)
        card_template_groups = get_card_template_groups(self.deck.id)
        self.templates = {
            card_name: {source_name: [] for source_name in self.template_sources}
            for card_name in card_pool
        }

        template_indexes = {
            source_name: self._index_templates(config["dir"])
            for source_name, config in self.template_sources.items()
        }

        for card_name, aliases in card_template_groups.items():
            loaded_paths = {source_name: set() for source_name in self.template_sources}
            for alias in aliases:
                key = card_key(alias)
                for source_name in self.template_sources:
                    template_path = template_indexes[source_name].get(key)
                    if template_path is None or template_path in loaded_paths[source_name]:
                        continue

                    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
                    if template is None or template.size == 0:
                        continue

                    self.templates[card_name][source_name].append(template)
                    loaded_paths[source_name].add(template_path)

        self.templates = {
            card_name: sources
            for card_name, sources in self.templates.items()
            if any(sources.values())
        }

    def _index_templates(self, directory):
        template_index = {}
        if not os.path.isdir(directory):
            return template_index

        for file_name in os.listdir(directory):
            file_path = os.path.join(directory, file_name)
            if not os.path.isfile(file_path):
                continue

            stem, ext = os.path.splitext(file_name)
            if ext.lower() not in IMAGE_EXTENSIONS:
                continue

            template_index[card_key(stem)] = file_path

        return template_index

    def _get_disabled_template_variants(self, template):
        cache_key = template.data.tobytes()
        variants = self.disabled_template_cache.get(cache_key)
        if variants is None:
            variants = (
                self._make_disabled_template_variant(template, variant=0),
                self._make_disabled_template_variant(template, variant=1),
            )
            self.disabled_template_cache[cache_key] = variants
        return variants

    def _make_disabled_template_variant(self, template, variant=0):
        height, width = template.shape[:2]
        gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        base = cv2.addWeighted(base, 0.82, np.full_like(base, 255), 0.18, 0)

        overlay = np.zeros((height, width), dtype=np.uint8)
        if variant == 0:
            polygon = np.array(
                [
                    (0, 0),
                    (int(width * 0.66), 0),
                    (int(width * 0.47), int(height * 0.47)),
                    (0, int(height * 0.63)),
                ],
                dtype=np.int32,
            )
            cv2.fillConvexPoly(overlay, polygon, 255)
            cv2.rectangle(
                overlay,
                (0, int(height * 0.42)),
                (int(width * 0.50), height),
                112,
                -1,
            )
        else:
            polygon = np.array(
                [
                    (0, 0),
                    (int(width * 0.72), 0),
                    (int(width * 0.52), int(height * 0.53)),
                    (0, int(height * 0.72)),
                ],
                dtype=np.int32,
            )
            cv2.fillConvexPoly(overlay, polygon, 208)
            cv2.rectangle(overlay, (0, 0), (int(width * 0.42), height), 80, -1)

        overlay = cv2.GaussianBlur(
            overlay,
            (0, 0),
            sigmaX=max(1, width // 18),
            sigmaY=max(1, height // 18),
        )
        alpha = (overlay.astype(np.float32) / 255.0)[:, :, None] * 0.34
        return np.clip(base.astype(np.float32) * (1.0 - alpha) + 255.0 * alpha, 0, 255).astype(np.uint8)

    def ensure_game_foreground(self):
        current_app = self.d.app_current()
        if current_app["package"] != PACKAGE_NAME:
            self.d.app_start(PACKAGE_NAME)
            time.sleep(5)
            current_app = self.d.app_current()
            return current_app["package"] == PACKAGE_NAME
        return True

    def adb_screenshot(self):
        if self.d is not None:
            try:
                screenshot = self.d.screenshot(format="opencv")
                if screenshot is not None:
                    return screenshot
            except Exception:
                pass

        try:
            adb_cmd = adb_command("exec-out", "screencap", "-p", device_id=self.device_id)
            process = subprocess.run(
                adb_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                check=False,
            )
            if process.stderr:
                return None

            nparr = np.frombuffer(process.stdout, np.uint8)
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception:
            return None

    def _capture_screenshots(self, frame_count=None):
        screenshots = []
        total_frames = frame_count or self.vote_frames
        for index in range(total_frames):
            screenshot = self.adb_screenshot()
            if screenshot is not None:
                screenshots.append(screenshot)
            if index + 1 < total_frames and self.vote_interval > 0:
                time.sleep(self.vote_interval)
        return screenshots

    def _crop_by_ratio(self, image, ratios):
        if image is None or image.size == 0:
            return None

        height, width = image.shape[:2]
        x1 = max(0, min(width - 1, int(round(width * ratios[0]))))
        y1 = max(0, min(height - 1, int(round(height * ratios[1]))))
        x2 = max(x1 + 1, min(width, int(round(width * ratios[2]))))
        y2 = max(y1 + 1, min(height, int(round(height * ratios[3]))))
        return image[y1:y2, x1:x2]

    def _crop_center_to_aspect(self, image, target_aspect):
        if image is None or image.size == 0:
            return None

        height, width = image.shape[:2]
        current_aspect = width / float(height)

        if current_aspect > target_aspect:
            new_width = max(1, int(round(height * target_aspect)))
            x1 = max(0, (width - new_width) // 2)
            return image[:, x1:x1 + new_width]

        new_height = max(1, int(round(width / target_aspect)))
        y1 = max(0, (height - new_height) // 2)
        return image[y1:y1 + new_height, :]

    def _normalize_card_frame(self, card_img):
        cropped = self._crop_by_ratio(card_img, self.card_frame_crop)
        if cropped is None or cropped.size == 0:
            return None

        target_aspect = self.normalized_card_size[0] / float(self.normalized_card_size[1])
        card_frame = self._crop_center_to_aspect(cropped, target_aspect)
        if card_frame is None or card_frame.size == 0:
            return None

        return cv2.resize(card_frame, self.normalized_card_size, interpolation=cv2.INTER_AREA)

    def _prepare_card_views(self, card_img):
        portrait_view = self._normalize_card_frame(card_img)
        full_view = cv2.resize(card_img, self.normalized_card_size, interpolation=cv2.INTER_AREA)
        return {
            "cards": portrait_view if portrait_view is not None and portrait_view.size != 0 else full_view,
            "cards_full": full_view,
        }

    def _crop_full_card_focus(self, card_img):
        return self._crop_by_ratio(card_img, self.full_card_focus_crop)

    def _estimate_saturation(self, image):
        if image is None or image.size == 0:
            return 0.0
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        return float(np.mean(hsv[:, :, 1]) / 255.0)

    def _is_disabled_card_view(self, card_views):
        full_view = card_views.get("cards_full")
        if full_view is None or full_view.size == 0:
            return False
        focus_view = self._crop_full_card_focus(full_view)
        return self._estimate_saturation(focus_view) <= self.disabled_saturation_threshold

    def _preprocess_gray(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        return cv2.GaussianBlur(gray, (3, 3), 0)

    def _match_score(self, image_gray, template_gray):
        if image_gray.shape[0] < template_gray.shape[0] or image_gray.shape[1] < template_gray.shape[1]:
            template_gray = cv2.resize(
                template_gray,
                (min(image_gray.shape[1], template_gray.shape[1]), min(image_gray.shape[0], template_gray.shape[0])),
                interpolation=cv2.INTER_AREA,
            )

        result = cv2.matchTemplate(image_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return max(0.0, float(max_val))

    def _score_color_similarity(self, card_img, template_img):
        diff = np.mean(np.abs(card_img.astype(np.float32) - template_img.astype(np.float32))) / 255.0
        return max(0.0, 1.0 - float(diff))

    def _score_hist_similarity(self, card_img, template_img):
        hsv_card = cv2.cvtColor(card_img, cv2.COLOR_BGR2HSV)
        hsv_template = cv2.cvtColor(template_img, cv2.COLOR_BGR2HSV)
        hist_card = cv2.calcHist([hsv_card], [0, 1], None, [24, 16], [0, 180, 0, 256])
        hist_template = cv2.calcHist([hsv_template], [0, 1], None, [24, 16], [0, 180, 0, 256])
        cv2.normalize(hist_card, hist_card)
        cv2.normalize(hist_template, hist_template)
        return max(0.0, float(cv2.compareHist(hist_card, hist_template, cv2.HISTCMP_CORREL)))

    def _score_full_template_features(self, card_view, template_img, disabled_like=False):
        card_gray = self._preprocess_gray(card_view)
        template_gray = self._preprocess_gray(template_img)

        gray_score = self._match_score(card_gray, template_gray)
        edge_card = cv2.Canny(card_gray, 60, 160)
        edge_template = cv2.Canny(template_gray, 60, 160)
        edge_score = self._match_score(edge_card, edge_template)

        focus_card = self._crop_full_card_focus(card_view)
        focus_template = self._crop_full_card_focus(template_img)
        focus_gray = self._preprocess_gray(focus_card)
        focus_template_gray = self._preprocess_gray(focus_template)
        focus_gray_score = self._match_score(focus_gray, focus_template_gray)
        color_score = self._score_color_similarity(focus_card, focus_template)
        hist_score = self._score_hist_similarity(focus_card, focus_template)

        if disabled_like:
            disabled_hybrid = (
                0.40 * focus_gray_score
                + 0.18 * gray_score
                + 0.18 * edge_score
                + 0.14 * color_score
                + 0.10 * hist_score
            )
            disabled_structural = 0.52 * focus_gray_score + 0.20 * gray_score + 0.28 * edge_score
            return max(disabled_hybrid, disabled_structural)

        return 0.28 * focus_gray_score + 0.10 * edge_score + 0.40 * color_score + 0.22 * hist_score

    def _score_template_variant(self, card_view, template, mode):
        template_img = cv2.resize(template, self.normalized_card_size, interpolation=cv2.INTER_AREA)
        if mode == "full":
            focus_card = self._crop_full_card_focus(card_view)
            saturation = self._estimate_saturation(focus_card)
            if saturation <= self.disabled_saturation_threshold:
                best_score = self._score_full_template_features(card_view, template_img, disabled_like=True)
                for disabled_template in self._get_disabled_template_variants(template_img):
                    best_score = max(
                        best_score,
                        self._score_full_template_features(card_view, disabled_template, disabled_like=True),
                    )
                return best_score

            return self._score_full_template_features(card_view, template_img, disabled_like=False)

        card_gray = self._preprocess_gray(card_view)
        template_gray = self._preprocess_gray(template_img)
        gray_score = self._match_score(card_gray, template_gray)
        edge_card = cv2.Canny(card_gray, 60, 160)
        edge_template = cv2.Canny(template_gray, 60, 160)
        edge_score = self._match_score(edge_card, edge_template)

        return 0.72 * gray_score + 0.28 * edge_score

    def _combine_source_scores(self, source_scores):
        full_like_scores = [
            source_scores[source_name]
            for source_name in ("cards_full", "legacy_cards", "legacy_oldcards")
            if source_name in source_scores
        ]
        portrait_score = source_scores.get("cards")

        if full_like_scores:
            full_score = max(full_like_scores)
            if portrait_score is None:
                return full_score
            return min(1.0, 0.96 * full_score + 0.04 * portrait_score)

        if portrait_score is not None:
            return portrait_score

        return 0.0

    def _get_cycle_card(self, internal_position):
        if internal_position is None:
            return None
        card_name = self.cycle.get_card(internal_position)
        return None if card_name in {None, "Unknown"} else card_name

    def _get_candidate_cards(self, position, allow_cycle_filter=True):
        if not allow_cycle_filter:
            return list(self.templates.keys())

        if isinstance(position, int) and 1 <= position <= 4:
            internal_position = position
        elif position == "next":
            internal_position = 5
        else:
            return list(self.templates.keys())

        reserved_cards = set()
        for idx in range(1, 9):
            if idx == internal_position:
                continue
            card_name = self._get_cycle_card(idx)
            if card_name is not None:
                reserved_cards.add(card_name)

        if self.cycle.removed_card not in {None, "Unknown"}:
            reserved_cards.add(self.cycle.removed_card)

        current_card = self._get_cycle_card(internal_position)
        candidates = [
            card_name
            for card_name in self.templates
            if card_name not in reserved_cards or card_name == current_card
        ]

        if not candidates:
            return list(self.templates.keys())

        return candidates

    def _rank_candidates(self, card_views, position, allow_cycle_filter=True):
        current_card = None
        if isinstance(position, int) and 1 <= position <= 4:
            current_card = self._get_cycle_card(position)
        elif position == "next":
            current_card = self._get_cycle_card(5)

        ranked = []
        for card_name in self._get_candidate_cards(position, allow_cycle_filter=allow_cycle_filter):
            source_scores = {}
            for source_name, templates in self.templates.get(card_name, {}).items():
                if not templates:
                    continue

                best_source_score = 0.0
                mode = self.template_sources[source_name]["mode"]
                card_view = card_views.get(source_name)
                if card_view is None or card_view.size == 0:
                    continue
                for template in templates:
                    score = self._score_template_variant(card_view, template, mode)
                    if score > best_source_score:
                        best_source_score = score

                if best_source_score > 0.0:
                    source_scores[source_name] = best_source_score

            if not source_scores:
                continue

            combined_score = self._combine_source_scores(source_scores)
            if current_card == card_name:
                combined_score = min(1.0, combined_score + self.position_bias)

            ranked.append(
                {
                    "name": card_name,
                    "score": combined_score,
                    "source_scores": source_scores,
                }
            )

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    def _evaluate_ranked_candidates(self, ranked, position, disabled_like=False):
        if not ranked:
            return {
                "name": "Unknown",
                "score": 0.0,
                "accepted": False,
                "best_name": "Unknown",
                "margin": 0.0,
                "accept_threshold": self._accept_threshold(position),
                "margin_threshold": self._margin_threshold(position),
            }

        best = ranked[0]
        second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
        margin = best["score"] - second_score

        accept_threshold = self._accept_threshold(position)
        margin_threshold = self._margin_threshold(position)
        if disabled_like and position != "next":
            accept_threshold = max(0.0, accept_threshold - self.disabled_accept_bonus)
            margin_threshold = max(0.02, margin_threshold - self.disabled_margin_bonus)

        accepted = best["score"] >= accept_threshold and margin >= margin_threshold
        if not accepted:
            accepted = self._accept_by_full_source_fallback(
                ranked,
                full_accept_threshold=(
                    self.disabled_full_source_accept_threshold
                    if disabled_like and position != "next"
                    else self.full_source_accept_threshold
                ),
            )

        return {
            "name": best["name"] if accepted else "Unknown",
            "score": best["score"],
            "accepted": accepted,
            "best_name": best["name"],
            "margin": margin,
            "accept_threshold": accept_threshold,
            "margin_threshold": margin_threshold,
        }

    def _accept_threshold(self, position):
        return self.next_accept_threshold if position == "next" else self.hand_accept_threshold

    def _margin_threshold(self, position):
        return self.next_margin_threshold if position == "next" else self.hand_margin_threshold

    def _accept_by_full_source_fallback(self, ranked, full_accept_threshold=None):
        if not ranked:
            return False

        if full_accept_threshold is None:
            full_accept_threshold = self.full_source_accept_threshold

        best_full_score = ranked[0]["source_scores"].get("cards_full")
        if best_full_score is None or best_full_score < full_accept_threshold:
            return False

        second_full_score = 0.0
        if len(ranked) > 1:
            second_full_score = ranked[1]["source_scores"].get("cards_full", 0.0)

        # Current combined scoring can suppress a confident full-card match when
        # the portrait crop is weak. Keep a narrow fallback aligned with the
        # original full-card matcher and require a source-level gap.
        return (best_full_score - second_full_score) >= self.full_source_margin_threshold

    def _recognize_card_details_from_screenshot(self, screenshot, region, position=None):
        if screenshot is None:
            return {"name": "Screenshot Failed", "score": 0.0, "accepted": False}

        x, y, w, h = region
        if x >= screenshot.shape[1] or y >= screenshot.shape[0]:
            return {"name": "Region Out of Bounds", "score": 0.0, "accepted": False}
        if x + w > screenshot.shape[1] or y + h > screenshot.shape[0]:
            return {"name": "Region Out of Bounds", "score": 0.0, "accepted": False}

        card_img = screenshot[y:y + h, x:x + w]
        if card_img is None or card_img.size == 0:
            return {"name": "Empty Card Image", "score": 0.0, "accepted": False}

        card_views = self._prepare_card_views(card_img)
        portrait_view = card_views.get("cards")
        if portrait_view is None or portrait_view.size == 0:
            return {"name": "Empty Card Image", "score": 0.0, "accepted": False}

        disabled_like = self._is_disabled_card_view(card_views)
        ranked = self._rank_candidates(card_views, position, allow_cycle_filter=True)
        evaluation = self._evaluate_ranked_candidates(ranked, position, disabled_like=disabled_like)

        if position is not None and (not evaluation["accepted"] or evaluation["score"] < (evaluation["accept_threshold"] + 0.02)):
            unfiltered_ranked = self._rank_candidates(card_views, position, allow_cycle_filter=False)
            unfiltered_evaluation = self._evaluate_ranked_candidates(
                unfiltered_ranked,
                position,
                disabled_like=disabled_like,
            )
            if (
                (unfiltered_evaluation["accepted"] and not evaluation["accepted"])
                or (unfiltered_evaluation["score"] >= evaluation["score"] + self.rerank_score_gap)
            ):
                evaluation = unfiltered_evaluation

        return {
            "name": evaluation["name"],
            "score": evaluation["score"],
            "accepted": evaluation["accepted"],
            "best_name": evaluation["best_name"],
            "margin": evaluation["margin"],
        }

    def _recognize_card_from_screenshot(self, screenshot, region, position=None):
        result = self._recognize_card_details_from_screenshot(screenshot, region, position=position)
        return result["name"], result["score"]

    def _aggregate_frame_results(self, frame_results, position):
        if not frame_results:
            return "Unknown", 0.0

        accepted_results = [result for result in frame_results if result.get("accepted")]
        if not accepted_results:
            grouped = {}
            for result in frame_results:
                best_name = result.get("best_name")
                if not best_name or best_name == "Unknown":
                    continue
                bucket = grouped.setdefault(best_name, {"count": 0, "score_sum": 0.0, "margin_sum": 0.0})
                bucket["count"] += 1
                bucket["score_sum"] += result.get("score", 0.0)
                bucket["margin_sum"] += result.get("margin", 0.0)

            if grouped:
                winner_name, winner_stats = max(
                    grouped.items(),
                    key=lambda item: (
                        item[1]["count"],
                        item[1]["score_sum"] / item[1]["count"],
                        item[1]["margin_sum"] / max(1, item[1]["count"]),
                    ),
                )
                avg_score = winner_stats["score_sum"] / winner_stats["count"]
                avg_margin = winner_stats["margin_sum"] / winner_stats["count"]
                near_accept_threshold = self._accept_threshold(position) - 0.02
                near_margin_threshold = max(0.015, self._margin_threshold(position) - 0.02)
                if winner_stats["count"] >= max(1, len(frame_results) - 1) and avg_score >= near_accept_threshold:
                    return winner_name, avg_score
                if winner_stats["count"] >= 2 and avg_score >= near_accept_threshold and avg_margin >= near_margin_threshold:
                    return winner_name, avg_score

            best_result = max(frame_results, key=lambda item: item.get("score", 0.0))
            return "Unknown", best_result.get("score", 0.0)

        grouped = {}
        for result in accepted_results:
            bucket = grouped.setdefault(
                result["best_name"],
                {"count": 0, "score_sum": 0.0, "margin_sum": 0.0},
            )
            bucket["count"] += 1
            bucket["score_sum"] += result["score"]
            bucket["margin_sum"] += result.get("margin", 0.0)

        winner_name, winner_stats = max(
            grouped.items(),
            key=lambda item: (
                item[1]["count"],
                item[1]["score_sum"] / item[1]["count"],
                item[1]["margin_sum"] / item[1]["count"],
            ),
        )

        winner_count = winner_stats["count"]
        winner_score = winner_stats["score_sum"] / winner_count
        winner_margin = winner_stats["margin_sum"] / winner_count
        required_votes = (len(frame_results) // 2) + 1
        strong_threshold = self._accept_threshold(position) + self.strong_match_bonus

        if winner_count >= required_votes:
            return winner_name, winner_score

        if winner_score >= strong_threshold and winner_margin >= self._margin_threshold(position):
            return winner_name, winner_score

        return "Unknown", winner_score

    def _recognize_position_from_screenshots(self, screenshots, region, position):
        if not screenshots:
            return "Unknown", 0.0

        return self._aggregate_frame_results(
            [
                self._recognize_card_details_from_screenshot(screenshot, region, position=position)
                for screenshot in screenshots
            ],
            position=position,
        )

    def _retry_unknown_position(self, position, region, best_confidence=0.0):
        best_unknown_confidence = best_confidence

        for _ in range(self.unknown_retry_attempts):
            time.sleep(self.unknown_retry_interval)
            screenshots = self._capture_screenshots()
            if not screenshots:
                continue

            card_name, confidence = self._recognize_position_from_screenshots(screenshots, region, position)
            if card_name != "Unknown":
                return card_name, confidence

            best_unknown_confidence = max(best_unknown_confidence, confidence)

        return "Unknown", best_unknown_confidence

    def recognize_card(self, region):
        if self.d is None:
            return "Device Not Connected", 0.0
        if not self.ensure_game_foreground():
            return "Game Not Foreground", 0.0

        screenshots = self._capture_screenshots()
        if not screenshots:
            return "Screenshot Failed", 0.0

        card_name, confidence = self._recognize_position_from_screenshots(screenshots, region, position=None)
        if card_name != "Unknown":
            return card_name, confidence

        return self._retry_unknown_position(position=None, region=region, best_confidence=confidence)

    def _get_all_cards_from_screenshots(self, screenshots, retry_unknown=True):
        results = []
        for i, region in enumerate(self.card_regions, start=1):
            card_name, confidence = self._recognize_position_from_screenshots(screenshots, region, position=i)
            results.append({"position": i, "name": card_name, "confidence": confidence})

        next_card, next_confidence = self._recognize_position_from_screenshots(
            screenshots,
            self.next_card_region,
            position="next",
        )
        results.append({"position": "next", "name": next_card, "confidence": next_confidence})

        if not retry_unknown:
            return results

        unknown_positions = {
            result["position"]: index
            for index, result in enumerate(results)
            if result["name"] == "Unknown"
        }

        for _ in range(self.unknown_retry_attempts):
            if not unknown_positions:
                break

            time.sleep(self.unknown_retry_interval)
            retry_screenshots = self._capture_screenshots()
            if not retry_screenshots:
                continue

            resolved_positions = []
            for position, index in unknown_positions.items():
                region = self.next_card_region if position == "next" else self.card_regions[position - 1]
                card_name, confidence = self._recognize_position_from_screenshots(
                    retry_screenshots,
                    region,
                    position=position,
                )

                if confidence > results[index]["confidence"]:
                    results[index]["confidence"] = confidence

                if card_name != "Unknown":
                    results[index]["name"] = card_name
                    results[index]["confidence"] = confidence
                    resolved_positions.append(position)

            for position in resolved_positions:
                unknown_positions.pop(position, None)

        return results

    def get_all_cards_from_screenshot(self, screenshot, retry_unknown=False):
        if screenshot is None:
            return []
        return self._get_all_cards_from_screenshots([screenshot], retry_unknown=retry_unknown)

    def get_all_cards(self):
        if self.d is None:
            return []
        if not self.ensure_game_foreground():
            return []

        screenshots = self._capture_screenshots()
        if not screenshots:
            return []

        return self._get_all_cards_from_screenshots(screenshots, retry_unknown=True)

    def get_card_at_position(self, position, retry_unknown=True):
        if self.d is None:
            return {"position": position, "name": "Device Not Connected", "confidence": 0.0}
        if not self.ensure_game_foreground():
            return {"position": position, "name": "Game Not Foreground", "confidence": 0.0}

        return self.get_card_at_position_from_screenshot(
            self._capture_screenshots(),
            position,
            retry_unknown=retry_unknown,
        )

    def get_card_at_position_from_screenshot(self, screenshot_or_screenshots, position, retry_unknown=False):
        if screenshot_or_screenshots is None:
            return {"position": position, "name": "Screenshot Failed", "confidence": 0.0}

        if isinstance(position, int) and 1 <= position <= 4:
            region = self.card_regions[position - 1]
        elif position == "next":
            region = self.next_card_region
        else:
            return {"position": position, "name": "Invalid Position", "confidence": 0.0}

        if isinstance(screenshot_or_screenshots, list):
            screenshots = [shot for shot in screenshot_or_screenshots if shot is not None]
        else:
            screenshots = [screenshot_or_screenshots]

        if not screenshots:
            return {"position": position, "name": "Screenshot Failed", "confidence": 0.0}

        card_name, confidence = self._recognize_position_from_screenshots(screenshots, region, position=position)
        if retry_unknown and card_name == "Unknown":
            card_name, confidence = self._retry_unknown_position(position=position, region=region, best_confidence=confidence)
        return {"position": position, "name": card_name, "confidence": confidence}


if __name__ == "__main__":
    recognizer = CRCardRecognizer(DEVICE_ID)
    if recognizer.d is not None:
        time.sleep(2)
        all_cards = recognizer.get_all_cards()
        print("所有卡牌信息:")
        for card in all_cards:
            print(f"位置 {card['position']}: {card['name']} (置信度: {card['confidence']:.2f})")

        card_1 = recognizer.get_card_at_position(1)
        print(f"第一张卡牌: {card_1['name']} (置信度: {card_1['confidence']:.2f})")

        next_card = recognizer.get_card_at_position("next")
        print(f"下一张卡牌: {next_card['name']} (置信度: {next_card['confidence']:.2f})")
    else:
        print("无法进行识别，因为设备连接失败")
