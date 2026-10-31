"""A typed code is the one the model and the letter detector read together.

The `textK` markers read the code all at once and slip on real BotDetect boards: two land on one
letter (R99VK for R9VK, WYYRH for WYRH), or one reads a W as И. The letter detector finds each
character's box but mistakes strokes for lookalikes (王 for T on a Latin board). Aligned in reading
order (`service.fuse`), each place takes the character with the most evidence from both, the boxes
settle how many letters there are, and the first retry makes the least sure choice the other way
(`service.fused_texts`, `service.read_answer`).
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import service as Svc

from test_a_refused_pointer_answer_moves_to_the_next import SIZE, STOP, decision


def typed(text, p, alt="", alt_p=()):
    return decision("type", text=[ord(c) for c in text], text_p=p,
                    text_alt=[ord(c) for c in (alt or text)], text_alt_p=alt_p or [0.0] * len(text))


def boxes(*letters):
    """letters: (class, score) or [(class, score), ...] for one box read as several lookalikes."""
    out = []
    for k, l in enumerate(letters):
        for c, s in (l if isinstance(l, list) else [l]):
            out.append({"class": c, "box": [30 * k, 0, 30 * k + 25, 30], "score": s})
    return Svc.letter_slots(out)


def read(d, letters, avoid=()):
    return Svc.read_answer(d, SIZE, [], lambda ids: "".join(map(chr, ids)), STOP, None, list(avoid), letters)


def test_a_doubled_letter_the_boxes_do_not_see_twice_is_typed_once():
    d = typed("R99VK", [.98, 1.0, .7, .89, .98])
    ans = read(d, boxes(("R", .9), ("9", .9), ("V", .9), ("K", .9)))
    assert ans["text"] == "R9VK" and ans["checks"]["letters_agree"] is False


def test_a_box_the_detector_misreads_keeps_the_models_letter():
    d = typed("TRU3D", [.95] * 5)
    assert read(d, boxes(("王", .5), ("R", .9), ("U", .9), ("3", .9), ("D", .9)))["text"] == "TRU3D"


def test_a_letter_the_model_was_unsure_of_takes_the_detectors_reading():
    d = typed("9C5KИP", [.9, .9, .9, .9, .5, .9], alt="9C5KWP", alt_p=[0, 0, 0, 0, .3, 0])
    ans = read(d, boxes(("9", .9), ("C", .9), ("5", .9), ("K", .9), ("W", .8), ("P", .9)))
    assert ans["text"] == "9C5KWP"


def test_the_first_retry_makes_the_least_sure_choice_the_other_way():
    d = typed("NPHDC", [.6, .9, .9, .9, .9], alt="MPHDC", alt_p=[.35, 0, 0, 0, 0])
    letters = boxes([("M", .6), ("N", .5)], ("P", .9), ("H", .9), ("D", .9), ("C", .9))
    first = read(d, letters)
    second = read(d, letters, [first])
    assert {first["text"], second["text"]} == {"NPHDC", "MPHDC"}
    assert second["checks"]["retry"] == "joint reading"


def test_with_no_box_found_the_model_types_alone():
    assert read(typed("U49C", [.9] * 4), [])["text"] == "U49C"


def test_two_readers_that_agree_are_marked_so():
    d = typed("XK4XWP", [.9] * 6)
    agree = read(d, boxes(*[(c, .9) for c in "XK4XWP"]))
    assert agree["text"] == "XK4XWP" and agree["checks"]["letters_agree"] is True
    assert agree["checks"]["letters"] == "XK4XWP"
    assert read(d, boxes(*[(c, .9) for c in "XK4XVP"]))["checks"]["letters_agree"] is False


def test_a_lookalike_is_typed_in_the_boards_script():
    # Latin: a W has no Cyrillic twin, so the model's Cyrillic Р and К are typed as P and K
    assert read(typed("Р5КТW", [.9] * 5), boxes(*[(c, .9) for c in "P5KTW"]))["text"] == "P5KTW"
    # Cyrillic: Ж has no Latin twin
    assert read(typed("ЖKPA", [.9] * 4), boxes(*[(c, .9) for c in "ЖKPA"]))["text"] == "ЖКРА"


def test_a_board_of_lookalikes_only_is_tried_in_latin_then_cyrillic():
    d = typed("ECKX", [.9] * 4)
    letters = boxes(*[(c, .9) for c in "ЕСКХ"])
    first = read(d, letters)
    assert first["text"] == "ECKX"
    assert read(d, letters, [first])["text"] == "ЕСКХ"


def test_overlapping_lookalike_boxes_are_one_letter_read_two_ways():
    slots = boxes([("A", .9), ("А", .6)], ("K", .8))
    assert len(slots) == 2 and slots[0]["chars"] == {"a": .9}
    assert Svc.read_letters([{"class": "B", "box": [40, 0, 60, 9], "score": .9},
                             {"class": "A", "box": [0, 0, 20, 9], "score": .9}]) == "AB"


def test_a_cyrillic_lookalike_or_another_case_is_the_same_letter():
    assert Svc.fold("КРАН") == Svc.fold("kpah") == Svc.fold("KPAH")


def test_a_box_of_another_script_is_still_a_box_but_names_no_letter():
    slots = Svc.in_board_script(boxes(("王", .9), ("R", .9)), "TR")
    assert len(slots) == 2 and slots[0]["chars"] == {} and slots[1]["chars"] == {"r": .9}
