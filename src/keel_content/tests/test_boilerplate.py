"""The boilerplate detector reports substance, never structure."""

from keel_content.core.boilerplate import PageUnits, Repeat, find_repeats, format_report

LONG = " ".join(["word"] * 30)
OTHER = " ".join(["other"] * 30)


def test_a_block_on_one_page_is_not_a_repeat():
    corpus = {"a": PageUnits(blocks=[LONG]), "b": PageUnits(blocks=[OTHER])}
    assert find_repeats(corpus) == []


def test_a_block_on_two_pages_is_reported_with_both():
    corpus = {"a": PageUnits(blocks=[LONG]), "b": PageUnits(blocks=[LONG])}
    (repeat,) = find_repeats(corpus)
    assert repeat.kind == "block"
    assert repeat.pages == ("a", "b")
    assert repeat.words == 30


def test_short_blocks_are_data_and_stay_out_of_the_report():
    corpus = {"a": PageUnits(blocks=["2 to 3 candles"]),
              "b": PageUnits(blocks=["2 to 3 candles"])}
    assert find_repeats(corpus) == []
    assert len(find_repeats(corpus, min_block_words=1)) == 1


def test_rewrapped_whitespace_is_the_same_block():
    corpus = {"a": PageUnits(blocks=[LONG]),
              "b": PageUnits(blocks=["  " + LONG.replace(" ", "\n  ") + "\n"])}
    assert len(find_repeats(corpus)) == 1


def test_a_phrase_repeated_within_one_page_is_not_a_corpus_repeat():
    corpus = {"a": PageUnits(blocks=[LONG, LONG]), "b": PageUnits(blocks=[OTHER])}
    assert find_repeats(corpus) == []


def test_headings_have_no_word_floor_and_take_their_own_cap():
    corpus = {p: PageUnits(headings=["The rule set"]) for p in "abc"}
    assert len(find_repeats(corpus)) == 1
    assert find_repeats(corpus, max_heading_pages=3) == []


def test_identical_figure_fingerprints_are_reported():
    corpus = {"a": PageUnits(figures=["sha:1"]), "b": PageUnits(figures=["sha:1"]),
              "c": PageUnits(figures=["sha:2"])}
    (repeat,) = find_repeats(corpus)
    assert repeat.kind == "figure"
    assert repeat.pages == ("a", "b")


def test_the_worst_offender_is_reported_first():
    corpus = {"a": PageUnits(blocks=[LONG, OTHER]), "b": PageUnits(blocks=[LONG, OTHER]),
              "c": PageUnits(blocks=[LONG])}
    first, second = find_repeats(corpus)
    assert first.count == 3 and second.count == 2


def test_report_names_every_page_a_repeat_landed_on():
    r = Repeat(kind="block", value=LONG, pages=("a", "b"), words=30)
    lines = format_report([r])
    assert "on  2 pages" in lines[0]
    assert lines[1].strip() == "a, b"
