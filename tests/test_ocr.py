from screen_translator.ocr import Line, merge_paragraphs


def test_wrapped_sentence_is_one_block():
    lines = [Line(100, 200, 400, 20, "A long sentence that"), Line(100, 222, 150, 20, "wraps early.")]
    assert [b.text for b in merge_paragraphs(lines)] == ["A long sentence that wraps early."]


def test_sentence_end_starts_new_block():
    lines = [Line(100, 200, 400, 20, "First sentence."), Line(100, 222, 400, 20, "Second sentence")]
    assert len(merge_paragraphs(lines)) == 2


def test_far_apart_lines_stay_separate():
    lines = [Line(100, 200, 400, 20, "One line"), Line(100, 400, 400, 20, "Another line")]
    assert len(merge_paragraphs(lines)) == 2


def test_prepare_inverts_dark_pictures_and_enlarges_small_ones():
    import numpy as np
    from screen_translator import ocr
    dark = np.zeros((10, 20, 4), np.uint8)
    dark[:, :, 3] = 255
    data, w, h, scale = ocr.prepare(dark.tobytes(), 20, 10)
    assert (w, h, scale) == (40, 20, 2.0) and len(data) == 40 * 20 * 4
    assert data[0] == 255  # black became white
    light = np.full((2160, 3840, 4), 255, np.uint8)
    data, w, h, scale = ocr.prepare(light.tobytes(), 3840, 2160)
    assert (w, h, scale) == (3840, 2160, 1.0) and data[0] == 255  # a big screen is not enlarged


def test_words_ocr_keeps_misreading_are_corrected_in_english_only():
    from screen_translator.ocr import fix_confusions
    assert fix_confusions("Thank vou, vour order is ready", "en-US") == "Thank you, your order is ready"
    assert fix_confusions("VOU WIN. Vou win. tbe end", "en-GB") == "YOU WIN. You win. the end"
    assert fix_confusions("vou", "de-DE") == "vou"  # not English: left alone
    assert fix_confusions("Vouchers and covered", "en-US") == "Vouchers and covered"  # real words are not touched
