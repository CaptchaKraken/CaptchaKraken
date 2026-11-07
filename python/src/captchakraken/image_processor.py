"""The frame-diff primitive every movement check in both ports shares."""

from .keyframes import frame_diff_ratio, read_frame


class ImageProcessor:
    @staticmethod
    def movement_ratio(image1_path: str, image2_path: str) -> float:
        """Share of pixels differing by more than 30 grey levels; 0 if unreadable, 1 if the sizes differ.

        Split from `detect_movement` so callers can report the number: GeeTest's permanent background shimmer
        sits close enough to the default threshold to fire the freshness re-solve on nearly every inference.
        """
        img1, img2 = read_frame(image1_path), read_frame(image2_path)
        if img1 is None or img2 is None:
            return 0.0
        return frame_diff_ratio(img1, img2)

    @staticmethod
    def detect_movement(image1_path: str, image2_path: str, threshold: float = 0.005) -> bool:
        return ImageProcessor.movement_ratio(image1_path, image2_path) > threshold
