import unittest

from exscriptor.layer_zones import filter_layers, zone_names


OPEN = "<<<THOMAS>>>"
CLOSE = "<<<END THOMAS>>>"


class ZoneDropTests(unittest.TestCase):
    def test_drops_marked_zone_and_keeps_the_rest(self):
        text = f"before\n{OPEN}\nquoted base text\n{CLOSE}\nafter"

        r = filter_layers(text)

        self.assertIn("before", r["kept"])
        self.assertIn("after", r["kept"])
        self.assertNotIn("quoted base text", r["kept"])
        self.assertIn("quoted base text", r["dropped"])

    def test_drops_every_line_between_markers_including_markers(self):
        text = f"a\n{OPEN}\nx\ny\n{CLOSE}\nb"

        r = filter_layers(text)

        # the marker lines go too, so what is left is the surrounding text
        self.assertEqual(r["kept"].strip(), "a\nb")

    def test_no_zones_means_nothing_dropped(self):
        text = f"a\n{OPEN}\nx\n{CLOSE}\nb"

        r = filter_layers(text, zones=("NOSUCH",))

        self.assertIn("x", r["kept"])

    def test_zone_names_default_to_the_two_voice_convention(self):
        self.assertEqual(zone_names(None), ("THOMAS",))

    def test_zone_names_prefer_explicit_argument_then_env(self):
        self.assertEqual(zone_names(("BASE", "APPARATUS")), ("BASE", "APPARATUS"))
        import os
        os.environ["DIGITIZE_ZONES"] = "ONE,TWO"
        try:
            self.assertEqual(zone_names(None), ("ONE", "TWO"))
        finally:
            del os.environ["DIGITIZE_ZONES"]


class MarkerBalanceTests(unittest.TestCase):
    def test_reports_a_zone_left_open(self):
        r = filter_layers(f"a\n{OPEN}\nx")
        self.assertTrue(any("never closed" in u for u in r["unbalanced"]))

    def test_reports_a_close_with_no_open(self):
        r = filter_layers(f"a\n{CLOSE}\nb")
        self.assertTrue(any("no opening marker" in u for u in r["unbalanced"]))

    def test_reports_nested_open(self):
        r = filter_layers(f"{OPEN}\nx\n{OPEN}\ny\n{CLOSE}\n{CLOSE}")
        self.assertTrue(any("opened inside" in u for u in r["unbalanced"]))

    def test_reports_mismatched_close(self):
        r = filter_layers("<<<BASE>>>\nx\n<<<END OTHER>>>",
                          zones=("BASE", "OTHER"))
        self.assertTrue(any("closes" in u for u in r["unbalanced"]))

    def test_balanced_pair_is_quiet(self):
        r = filter_layers(f"a\n{OPEN}\nx\n{CLOSE}\nb")
        self.assertEqual(r["unbalanced"], [])


class PublishedVoiceCaughtInDroppedZoneTests(unittest.TestCase):
    """The check worth a gate: a zone boundary is an editorial decision."""

    def test_flags_a_verdict_line_caught_inside_a_zone(self):
        # the verdict sits INSIDE the zone, so the assembler would delete it
        text = (f"{OPEN}\nAd primum sic proceditur. Videtur quod…\n"
                f"Conclusio est affirmativa.\n{CLOSE}\n")
        r = filter_layers(text, authorial=("^Conclusio",))

        self.assertTrue(r["authorial_in_dropped"])
        self.assertIn("Conclusio", r["authorial_in_dropped"][0])
        # and it is genuinely gone from the published text
        self.assertNotIn("Conclusio", r["kept"])

    def test_quiet_when_the_verdict_sits_outside_the_zone(self):
        text = (f"{OPEN}\nAd primum sic proceditur.\n{CLOSE}\n"
                f"Conclusio est affirmativa.\n")
        r = filter_layers(text, authorial=("^Conclusio",))

        self.assertEqual(r["authorial_in_dropped"], [])
        self.assertIn("Conclusio", r["kept"])

    def test_authorial_patterns_default_to_none_and_never_fire(self):
        text = f"{OPEN}\nConclusio est affirmativa.\n{CLOSE}\n"
        r = filter_layers(text)
        self.assertEqual(r["authorial_in_dropped"], [])

    def test_dropped_material_is_reported_not_silently_discarded(self):
        r = filter_layers(f"a\n{OPEN}\nx\n{CLOSE}\n")
        self.assertTrue(r["dropped_nonblank"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
