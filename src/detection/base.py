"""
Motion detector interface.

A MotionDetector's only job is to look at frames and report whether motion
occurred. It must NOT know about Telegram, storage, cooldown, or which
camera the frame came from - those stay in main()/future event logic.
This keeps detectors swappable: a new algorithm can be dropped in without
touching anything else in the application (architecture plan §18-19, §46).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class MotionResult:
    """Structured result returned by a detector's process() call."""
    motion_detected: bool
    changed_percentage: float
    detector_name: str
    max_diff: Optional[int] = None
    mean_diff: Optional[float] = None


class MotionDetector(ABC):
    """Common interface all motion-detection algorithms implement."""

    name: str = "base"

    @abstractmethod
    def warm(self, frame) -> None:
        """
        Feed a frame into the detector to establish/update its baseline,
        without evaluating it for motion. Used during initial warmup and
        during camera re-warming after a video recording (architecture
        plan §4 - camera rewarming must be preserved).
        """
        raise NotImplementedError

    @abstractmethod
    def process(self, frame) -> MotionResult:
        """
        Evaluate a frame against the detector's current baseline and
        return a MotionResult. Implementations should update their
        internal baseline to this frame afterward.
        """
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        """Clear any stored baseline/state (e.g. before re-warming)."""
        raise NotImplementedError
