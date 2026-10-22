import numpy as np
from PIL import Image, ImageDraw, ImageFont

from screen_translator import tracking


def page(offset=0, width=960, height=540):
    """A page of text lines scrolled by `offset` px, with a fixed grey bar at the top (uint8, like a screenshot)."""
    img = Image.new("L", (width, height + 600), 255)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype("arial.ttf", 22)
    for i in range(40):
        d.text((40 + 10 * (i % 3), 20 + 38 * i), f"Line {i}: the quick brown fox jumps over {i * 7} lazy dogs", font=f, fill=0)
    a = np.asarray(img, np.uint8)[offset:offset + height].copy()
    a[:40] = 200
    return a


def block(line, offset):
    """The track for text line `line` when the page is scrolled by `offset`."""
    return {"x": 40, "y": 20 + 38 * line - offset, "w": 520, "h": 30}


def test_every_scroll_distance_is_found_to_the_pixel_even_odd_ones():
    for step in (1, 5, 7, 23, 45, 90):
        t = block(8, 100)
        got = tracking.follow([t], page(100), page(100 + step))
        if step < tracking.COARSE:
            assert got in ((0, 0), (0, -step)), (step, got)
            continue
        assert got == (0, -step), (step, got)
        assert t["y"] == block(8, 100 + step)["y"]


def test_blocks_move_with_the_scroll_and_a_fixed_header_stays():
    body = block(8, 100)
    header = {"x": 0, "y": 0, "w": 400, "h": 36}
    assert tracking.follow([body, header], page(100), page(160)) == (0, -60)
    assert body["y"] == block(8, 160)["y"]
    assert header["y"] == 0  # did not scroll


def test_a_page_change_moves_nothing():
    other = np.random.default_rng(0).integers(0, 255, (540, 960), dtype=np.uint8)
    t = block(8, 100)
    y = t["y"]
    assert tracking.follow([t], page(100), other) is None
    assert t["y"] == y


def test_a_block_hidden_under_our_own_box_goes_with_the_scroll_and_our_boxes_do_not_confuse_the_measurement():
    prev, cur = page(100), page(160)
    cover = (0, 100, 600, 300)  # our own box: drawn at the same place in both pictures
    for img in (prev, cur):
        img[100:300, 0:600] = 20
    hidden = {**block(4, 100), "covered": True}
    got = tracking.follow([hidden], prev, cur, ignore=[cover])
    assert got == (0, -60) and hidden["y"] == block(4, 160)["y"] and hidden["followed"]
