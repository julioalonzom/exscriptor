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
        f["disposition"] = {"verdict": "aligned", "note": f"block {f['index']}: same argument and the same closing boundary"}
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


def test_a_reconcile_aligns_only_the_sections_it_changes():
    import hashlib
    def text(lang, content, changed=False):
        live = content if not changed else content + " (old)"
        return {"language": lang, "content": content, "role": "translation",
                "expected_current_content_sha256": hashlib.sha256(live.encode()).hexdigest()}
    m = {"works": [{"slug": "w", "import_mode": "reconcile_existing", "sections": [
        {"section_key": "s1", "texts": [text("la", "Textus."), text("en", "Text.")]},
        {"section_key": "s2", "texts": [text("la", "Alius."), text("en", "Other.", changed=True)]},
    ]}]}
    assert set(al.pairs_by_section(m, "la", "en")) == {"s2"}
    for s in m["works"][0]["sections"]:
        s["texts"][1]["expected_current_content_sha256"] = hashlib.sha256(
            s["texts"][1]["content"].encode()).hexdigest()
    assert al.pairs_by_section(m, "la", "en") == {}


def test_dispose_refuses_boilerplate_and_merges_specific_notes(tmp_path):
    m = {"works": [{"slug": "w", "sections": [
        {"section_key": f"s{i}", "texts": [{"language": "la", "content": f"Primum {i}.\n\nSecundum {i}."},
                                          {"language": "en", "content": f"First {i}.\n\nSecond {i}."}]}
        for i in (1, 2)]}]}
    mp, rp = tmp_path / "m.json", tmp_path / "r.json"
    mp.write_text(json.dumps(m))
    runner = CliRunner()
    assert runner.invoke(al.app, ["screen", str(mp), "--report", str(rp)]).exit_code == 0
    shown = runner.invoke(al.app, ["show", str(mp), "--report", str(rp)]).output
    keys = [line.split()[1] for line in shown.splitlines() if line.startswith("=== ")]
    assert keys and all("@" in k for k in keys)
    dp = tmp_path / "d.json"
    dp.write_text(json.dumps({k: {"verdict": "aligned", "note": "content matches the source well"}
                              for k in keys}))
    r = runner.invoke(al.app, ["dispose", str(mp), "--report", str(rp), "--dispositions", str(dp)])
    assert r.exit_code == 1 and "same note" in r.output
    dp.write_text(json.dumps({k: {"verdict": "aligned", "note": "ok"} for k in keys[:1]}))
    assert "too short" in runner.invoke(
        al.app, ["dispose", str(mp), "--report", str(rp), "--dispositions", str(dp)]).output
    dp.write_text(json.dumps({k: {"verdict": "misaligned", "note": "x " * 8} for k in keys[:1]}))
    assert "re-screened" in runner.invoke(
        al.app, ["dispose", str(mp), "--report", str(rp), "--dispositions", str(dp)]).output
    dp.write_text(json.dumps({k: {"verdict": "aligned", "note": f"pair {k}: first and second ordinal both rendered"}
                              for k in keys}))
    r = runner.invoke(al.app, ["dispose", str(mp), "--report", str(rp), "--dispositions", str(dp)])
    assert r.exit_code == 0, r.output
    assert runner.invoke(al.app, ["check", str(mp), "--report", str(rp)]).exit_code == 0
    stale = {k.split("@")[0] + "@0000000000": {"verdict": "aligned", "note": "a reading of a text since edited"}
             for k in keys[:1]}
    dp.write_text(json.dumps(stale))
    assert "read again" in runner.invoke(
        al.app, ["dispose", str(mp), "--report", str(rp), "--dispositions", str(dp)]).output
