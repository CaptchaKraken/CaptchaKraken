"""Frames are BGR arrays everywhere in the client, and the pixels the model is shown are the ones it was trained on.

A swapped channel order fails nothing loudly: grey levels shift, movement thresholds move, and the model is shown
a board in the wrong colours. The resize and grey values below are OpenCV's own output for the same inputs, which
the training frames were cut with.
"""

import io

import av
import numpy as np
from PIL import Image

from captchakraken import clipvideo
from captchakraken.keyframes import frame_diff_ratio, read_frame, to_gray, write_frame
from captchakraken.solver import CaptchaSolver

BLUE, GREEN, RED = (255, 0, 0), (0, 255, 0), (0, 0, 255)  # BGR
RAMP = (np.arange(36, dtype=np.uint8).reshape(6, 6) * 7 + 3)


def _bgr(colour, size=(16, 16)):
    return np.full((size[1], size[0], 3), colour, dtype=np.uint8)


def test_a_written_frame_is_an_ordinary_rgb_image_on_disk(tmp_path):
    path = tmp_path / "red.png"
    write_frame(path, _bgr(RED))
    assert Image.open(path).convert("RGB").getpixel((3, 3)) == (255, 0, 0)


def test_a_read_frame_is_bgr(tmp_path):
    path = tmp_path / "blue.png"
    Image.new("RGB", (8, 8), (0, 0, 255)).save(path)
    assert read_frame(path)[0, 0].tolist() == list(BLUE)


def test_an_unreadable_image_reads_as_none(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    assert read_frame(path) is None
    assert read_frame(tmp_path / "missing.png") is None


def test_grey_weighs_the_channels_as_bgr():
    frame = np.array([[BLUE, GREEN, RED, (37, 201, 90)]], dtype=np.uint8)
    assert to_gray(frame).tolist() == [[29, 150, 76, 149]]


def test_a_pixel_moves_only_past_thirty_grey_levels():
    a = np.zeros((1, 2, 3), np.uint8)
    b = a.copy()
    b[0, 0] = 30
    b[0, 1] = 31
    assert frame_diff_ratio(a, b) == 0.5


def test_the_clip_sent_to_the_model_keeps_its_colours():
    clip = clipvideo.clip_video([_bgr(RED, (64, 64))] * 2, 5.0, max_pixels=64 * 64)
    sent = Image.open(io.BytesIO(clipvideo.encode_jpeg(clip.frames[0])))
    r, g, b = sent.convert("RGB").getpixel((32, 32))
    assert r > 240 and g < 15 and b < 15
    assert sent.info.get("progressive") is None and sent.layer[0][1:3] == (2, 2), "4:2:0 chroma, baseline"


def test_frames_are_resized_as_opencv_resizes_them():
    area = clipvideo.resize_area
    assert area(RAMP, 4, 4).tolist() == [[19, 29, 40, 50], [75, 85, 96, 106], [145, 155, 166, 176],
                                         [201, 211, 222, 232]]
    assert area(RAMP, 3, 3).tolist() == [[28, 42, 56], [112, 126, 140], [196, 210, 224]]
    assert area(RAMP, 2, 3).tolist() == [[31, 52], [115, 136], [199, 220]]
    assert area(RAMP, 9, 7)[3].tolist() == [108, 112, 115, 122, 126, 129, 136, 140, 143]
    assert clipvideo.resize_linear(RAMP, 5, 4).tolist() == [[14, 23, 31, 39, 48], [77, 86, 94, 102, 111],
                                                           [140, 149, 157, 165, 174], [203, 212, 220, 228, 237]]
    assert clipvideo.resize_linear(RAMP, 7, 8)[1].tolist() == [29, 35, 41, 47, 53, 59, 64]


def _video(path, rgb):
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for _ in range(3):
            out.mux(stream.encode(av.VideoFrame.from_image(Image.new("RGB", (64, 48), rgb))))
        out.mux(stream.encode())


def test_a_video_or_gif_is_solved_from_its_first_frame_in_its_own_colours(tmp_path):
    clip, gif = tmp_path / "board.mp4", tmp_path / "board.gif"
    _video(clip, (220, 20, 20))
    Image.new("RGB", (40, 30), (20, 20, 220)).save(gif)
    solver = CaptchaSolver.__new__(CaptchaSolver)
    solver._temp_files = []
    for media, size, channel in ((clip, (64, 48), 0), (gif, (40, 30), 2)):
        png = solver._materialize_image(str(media))
        assert solver._image_size == size
        pixel = Image.open(png).convert("RGB").getpixel((size[0] // 2, size[1] // 2))
        assert pixel[channel] > 180 and all(v < 60 for i, v in enumerate(pixel) if i != channel)
