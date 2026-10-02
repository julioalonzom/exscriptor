import json

from typer.testing import CliRunner

from exscriptor import alignment as al

LA = "\n\n".join(f"Latina sententia numero {i} satis longa." for i in range(1, 41))
EN = "\n\n".join(f"English sentence number {i}, long enough." for i in range(1, 41))


def manifest(la=LA, en=EN):
    return {"works": [{"sections": [{"section_key": "q1", "texts": [
        {"language": "la", "content": la}, {"language": "en", "content": en}]}]}]}


def test_screen_flags_final_sample_and_ratio():
    en = EN.replace("English sentence number 7, long enough.", "Short.")
    rep = al.screen(al.pairs_by_section(manifest(en=en), "la", "en"), seed=1)
    flags = {f["index"]: f["kinds"] for f in rep["q1"]["flags"]}
    assert "ratio" in flags[7] and flags[40] == ["final"]
    assert any("sample" in k for k in flags.values())


def test_count_mismatch_is_an_error():
    rep = al.screen(al.pairs_by_section(manifest(en=EN + "\n\nExtra."), "la", "en"))
    assert "mismatch" in rep["q1"]["error"]


def test_check_needs_dispositions_and_unchanged_text():
    pairs = al.pairs_by_section(manifest(), "la", "en")
    rep = {"sections": al.screen(pairs, seed=3)}
    assert al.check(pairs, rep)
    for f in rep["sections"]["q1"]["flags"]:
        f["disposition"] = {"verdict": "aligned", "note": "same argument, same boundary"}
    assert al.check(pairs, rep) == []
    changed = al.pairs_by_section(manifest(en=EN.replace("number 3", "no. 3")), "la", "en")
    assert "changed" in al.check(changed, rep)[0]


def test_rescreen_keeps_dispositions_of_unchanged_sections():
    pairs = al.pairs_by_section(manifest(), "la", "en")
    first = al.screen(pairs, seed=3)
    for f in first["q1"]["flags"]:
        f["disposition"] = {"verdict": "aligned", "note": "ok"}
    again = al.screen(pairs, seed=3, previous=first)
    assert all(f["disposition"] for f in again["q1"]["flags"])


def test_translate_only_source_from_live_snapshot(tmp_path):
    m = {"works": [{"sections": [{"section_key": "q1", "texts": [{"language": "en", "content": EN}]}]}]}
    live = {"sections": [{"section_key": "q1", "texts": {"la": {"content": LA}}}]}
    (tmp_path / "m.json").write_text(json.dumps(m))
    (tmp_path / "live.json").write_text(json.dumps(live))
    rep = tmp_path / "align.json"
    r = CliRunner().invoke(al.app, ["screen", str(tmp_path / "m.json"), "--report", str(rep),
                                    "--source", str(tmp_path / "live.json")])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(al.app, ["check", str(tmp_path / "m.json"), "--report", str(rep),
                                    "--source", str(tmp_path / "live.json")])
    assert r.exit_code == 1 and "no disposition" in r.output


def test_two_works_sharing_section_keys_are_paired_within_their_work():
    from exscriptor.alignment import pairs_by_section
    manifest = {"works": [
        {"slug": "summa", "sections": [
            {"section_key": "q50-a1", "texts": [{"language": "la", "content": "A.\n\nB.\n\nC."}]}]},
        {"slug": "caiet", "sections": [
            {"section_key": "q50-a1", "texts": [
                {"language": "la", "content": "Titulus."},
                {"language": "en", "content": "The title."}]}]}]}
    pairs = pairs_by_section(manifest, "la", "en")
    assert pairs == {"caiet/q50-a1": ("Titulus.", "The title.")}
