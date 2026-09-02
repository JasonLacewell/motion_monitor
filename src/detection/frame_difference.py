"""
Frame-difference motion detector.

This is the original motion_monitor.py algorithm (grayscale -> resize ->
blur -> absdiff -> threshold -> dilate -> % changed), moved behind the
MotionDetector interface unchanged. Do not alter the algorithm here -
this phase is purely an architectural move (architecture plan §Phase 3).
"""

import cv2

from detection.base import MotionDetector, MotionResult


class FrameDifferenceDetector(MotionDetector):
    name = "frame_difference"

    def __init__(self, pixel_change_threshold: int, motion_percent_threshold: float):
        self.pixel_change_threshold = pixel_change_threshold
        self.motion_percent_threshold = motion_percent_threshold
        self._previous_frame = None

    def reset(self) -> None:
        self._previous_frame = None

    @staticmethod
    def _preprocess(frame):
        """Convert a camera frame into a smaller grayscale image."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (640, 480))
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        return gray

    def warm(self, frame) -> None:
        """Update the baseline without evaluating motion - used for
        initial warmup and post-recording camera re-warming."""
        self._previous_frame = self._preprocess(frame)

    def process(self, frame) -> MotionResult:
        current = self._preprocess(frame)

        if self._previous_frame is None:
            # No baseline yet - establish one, nothing to compare against.
            self._previous_frame = current
            return MotionResult(
                motion_detected=False,
                changed_percentage=0.0,
                detector_name=self.name,
            )

        difference = cv2.absdiff(self._previous_frame, current)

        max_diff = int(difference.max())
        mean_diff = float(difference.mean())

        _, threshold = cv2.threshold(
            difference, self.pixel_change_threshold, 255, cv2.THRESH_BINARY
        )
        threshold = cv2.dilate(threshold, None, iterations=2)

        changed_pixels = cv2.countNonZero(threshold)
        total_pixels = threshold.shape[0] * threshold.shape[1]
        changed_percentage = (changed_pixels / total_pixels) * 100.0

        self._previous_frame = current

        return MotionResult(
            motion_detected=changed_percentage > self.motion_percent_threshold,
            changed_percentage=changed_percentage,
            detector_name=self.name,
            max_diff=max_diff,
            mean_diff=mean_diff,
        )
