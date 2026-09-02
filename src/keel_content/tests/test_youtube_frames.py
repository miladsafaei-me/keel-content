"""Unit tests for the video-screenshot stage.

Offline by design. Downloading and cutting video are thin wrappers around yt-dlp
and ffmpeg, and pinning those in tests would only pin the wrapper; what is tested
here is where the bugs actually live - timecode parsing, the burst geometry, the
JPEG header reader that supplies the figure's width and height, and the manifest
shape ``blog_add_figures`` consumes.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from keel_content.core.youtube_frames import (
    burst_offsets,
    jpeg_size,
    parse_timecode,
    second_from_name,
    slugify,
)
from keel_content.core.youtube_transcript import thin_index, timecode


def _fake_jpeg(path: Path, width: int, height: int) -> Path:
    """A minimal JPEG carrying one APP0 segment and one SOF0 frame header."""
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xe0" + struct.pack(">H", 6) + b"JFIF"          # a segment to skip over
        + b"\xff\xc0" + struct.pack(">H", 11) + b"\x08"
        + struct.pack(">HH", height, width) + b"\x01"
    )
    return path


class TimecodeTests(SimpleTestCase):
    def test_every_form_becomes_seconds(self):
        self.assertEqual(parse_timecode("01:30"), 90.0)
        self.assertEqual(parse_timecode("43:53"), 2633.0)
        self.assertEqual(parse_timecode("1:00:30"), 3630.0)
        self.assertEqual(parse_timecode("90"), 90.0)

    def test_garbage_is_zero_not_an_exception(self):
        for bad in ("", "soon", "--", None):
            self.assertEqual(parse_timecode(bad), 0.0)

    def test_rendering_grows_an_hours_field_only_when_needed(self):
        self.assertEqual(timecode(75), "01:15")
        self.assertEqual(timecode(3661), "1:01:01")


class BurstTests(SimpleTestCase):
    def test_offsets_are_centred_and_span_the_spread(self):
        """The burst must straddle the moment, or it defeats its own purpose."""
        self.assertEqual(burst_offsets(5, 6.0), [-6.0, -3.0, 0.0, 3.0, 6.0])
        self.assertEqual(burst_offsets(3, 9.0), [-9.0, 0.0, 9.0])
        self.assertEqual(burst_offsets(1, 6.0), [0.0])

    def test_the_absolute_second_survives_the_filename_round_trip(self):
        self.assertEqual(second_from_name(Path("venom-trigger_392s.jpg")), 392.0)
        self.assertEqual(second_from_name(Path("no-second-here.jpg")), 0.0)


class SlugTests(SimpleTestCase):
    def test_slugs_are_ascii_and_bounded(self):
        self.assertEqual(slugify("Entry & Stop: placement!"), "entry-stop-placement")
        self.assertEqual(slugify(""), "frame")
        self.assertLessEqual(len(slugify("x" * 300)), 60)


class JpegSizeTests(SimpleTestCase):
    def test_dimensions_are_read_past_a_leading_segment(self):
        """The figure markup needs exact integers, and ffprobe may not be installed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _fake_jpeg(Path(tmp) / "f.jpg", 1280, 720)
            self.assertEqual(jpeg_size(path), (1280, 720))

    def test_a_non_jpeg_is_rejected_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jpg"
            path.write_bytes(b"not a jpeg at all")
            with self.assertRaises(Exception):
                jpeg_size(path)


class ThinIndexTests(SimpleTestCase):
    def test_the_index_downsamples_and_keeps_timecodes(self):
        segments = [(i * 5.0, f"line {i}") for i in range(20)]
        lines = thin_index(segments, every_seconds=30).splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("[00:00] "))
        self.assertTrue(lines[1].startswith("[00:30] "))
