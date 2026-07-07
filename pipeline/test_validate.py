# PBT harness for pipeline/make_reel.py validate() — extracted verbatim (module imports
# google.genai which isn't needed for this pure function).
from make_reel import TRACKS, validate
from hypothesis import HealthCheck, given, settings, strategies as st

settings.register_profile("pbt", suppress_health_check=[HealthCheck.too_slow],
                          deadline=None)
settings.load_profile("pbt")


clip_names = st.text(st.characters(codec="ascii", categories=["L", "N"]),
                     min_size=1, max_size=20)


@st.composite
def catalog_st(draw):
    names = draw(st.lists(clip_names, min_size=1, max_size=10, unique=True))
    return {n: {"duration": draw(st.floats(10, 300))} for n in names}


@st.composite
def good_plan(draw, catalog):
    keys = list(catalog)
    n = draw(st.integers(5, 7))
    cuts = []
    for _ in range(n):
        k = draw(st.sampled_from(keys))
        dur = draw(st.floats(2.5, 4.5))
        start = draw(st.floats(0, max(0.0, catalog[k]["duration"] - dur)))
        cuts.append({"clip": k, "start_s": start, "duration_s": dur})
    return {"cuts": cuts, "audio_track": draw(st.sampled_from(list(TRACKS))),
            "audio_start_s": 58,
            "caption": draw(st.text(st.characters(codec="ascii"), min_size=1, max_size=40))}


# P1 soundness: if validate passes, every postcondition ffmpeg relies on actually holds
@settings(max_examples=500)
@given(st.data())
def test_soundness(data):
    catalog = data.draw(catalog_st())
    p = data.draw(good_plan(catalog))
    try:
        validate(p, catalog)
    except ValueError:
        return  # rejection is always safe
    for c in p["cuts"]:
        assert c["clip"] in catalog
        s, d = float(c["start_s"]), float(c["duration_s"])
        assert s >= 0 and 1.0 <= d <= 6.0
        assert s + d <= catalog[c["clip"]]["duration"] + 0.5
    assert 12 <= sum(float(c["duration_s"]) for c in p["cuts"]) <= 35
    assert p["audio_track"] in TRACKS
    assert p["caption"].strip()


# P2 completeness: one bad mutation of a good plan must be rejected
BAD = [
    lambda p, c: p["cuts"][0].update(clip="NOT_IN_CATALOG_xx"),
    lambda p, c: p["cuts"][0].update(start_s=-1),
    lambda p, c: p["cuts"][0].update(duration_s=0.2),
    lambda p, c: p["cuts"][0].update(duration_s=9.0),
    lambda p, c: p["cuts"][0].update(start_s=c[p["cuts"][0]["clip"]]["duration"] + 5),
    lambda p, c: p.update(audio_track="freebird"),
    lambda p, c: p.update(caption="   "),
    lambda p, c: p.update(cuts=p["cuts"][:2]),
    lambda p, c: p.update(cuts=p["cuts"] * 4),
]


@settings(max_examples=500)
@given(st.data())
def test_completeness(data):
    catalog = data.draw(catalog_st())
    p = data.draw(good_plan(catalog))
    try:
        validate(p, catalog)  # only mutate plans that were valid to begin with
    except ValueError:
        return
    mut = data.draw(st.sampled_from(BAD))
    mut(p, catalog)
    try:
        validate(p, catalog)
        raise AssertionError(f"bad plan accepted after mutation {BAD.index(mut)}: {p}")
    except ValueError:
        pass


# P3 clean failure: arbitrary hallucinated JSON must raise ValueError, never render.
# (KeyError/TypeError also abort the cron run, but ValueError is the documented contract.)
json_junk = st.recursive(
    st.none() | st.booleans() | st.floats(allow_nan=True) | st.text(max_size=8),
    lambda ch: st.lists(ch, max_size=4) | st.dictionaries(st.text(max_size=6), ch, max_size=4),
    max_leaves=12)


@settings(max_examples=1000)
@given(plan=st.dictionaries(st.sampled_from(
    ["cuts", "audio_track", "caption", "audio_start_s", "extra"]), json_junk, max_size=5),
    data=st.data())
def test_junk_raises_cleanly(plan, data):
    catalog = data.draw(catalog_st())
    try:
        validate(plan, catalog)
        # if it passed, soundness postconditions must hold
        for c in plan["cuts"]:
            assert c["clip"] in catalog
    except ValueError:
        pass  # the contract


if __name__ == "__main__":
    for t in [test_soundness, test_completeness, test_junk_raises_cleanly]:
        t()
        print("PASS", t.__name__)
