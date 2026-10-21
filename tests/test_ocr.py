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
