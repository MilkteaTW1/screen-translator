from conftest import arial
import numpy as np
from PIL import Image, ImageDraw

from screen_translator import tracking


def page(offset=0, width=960, height=540):
    """A page of text lines scrolled by `offset` px, with a fixed grey bar at the top (uint8, like a screenshot)."""
    img = Image.new("L", (width, height + 600), 255)
    d = ImageDraw.Draw(img)
    f = arial(22)
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


def test_a_shift_that_does_not_match_the_text_moves_nothing():
    # a page of identical lines: every offset looks alike, so a wrong shift must not drag the blocks away
    rng = np.random.default_rng(1)
    prev = rng.integers(0, 255, (540, 960), dtype=np.uint8)
    cur = np.roll(prev, 300, axis=0)  # a 300 px jump: more than 0.5 of the screen is not one scroll step
    t = block(8, 100)
    y = t["y"]
    assert tracking.follow([t], prev, cur) is None
    assert t["y"] == y


def test_a_carried_box_next_to_its_fresh_twin_is_a_duplicate():
    from screen_translator.app import _duplicate
    fresh = {"x": 40, "y": 100, "w": 300, "h": 30, "text": "How do you automatically tag 2,000 books?"}
    carried = {"x": 44, "y": 112, "w": 300, "h": 30, "text": "How do you automatically tag 2,000 books"}
    other = {"x": 40, "y": 400, "w": 300, "h": 30, "text": "Something else entirely"}
    assert _duplicate(carried, fresh)
    assert not _duplicate(other, fresh)


def test_rows_that_repeat_do_not_fool_the_shift_when_the_scroll_speed_says_which_one():
    img = Image.new("L", (960, 1200), 255)
    d = ImageDraw.Draw(img)
    f = arial(22)
    for i in range(30):  # the same row again and again, 38 px apart
        d.text((40, 20 + 38 * i), "Same item, same text, same row", font=f, fill=0)
    full = np.asarray(img, np.uint8)
    prev, cur = full[0:540].copy(), full[76:616].copy()  # scrolled by two rows
    for hint, want in (((0, -76.0), (0, -76)), ((0, -38.0), (0, -38))):
        t = {"x": 40, "y": 200, "w": 400, "h": 30}
        assert tracking.follow([t], prev, cur, hint=hint) == want, hint


def test_a_wrong_hint_does_not_beat_what_the_pictures_show():
    prev, cur = page(100), page(160)
    t = block(8, 100)
    assert tracking.follow([t], prev, cur, hint=(0, -20.0)) == (0, -60)
