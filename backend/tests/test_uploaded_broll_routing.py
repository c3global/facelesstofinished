from media_routing import (
    classify_scene_kind,
    count_visual_scene_sources,
    uploaded_media_kind,
)


def test_explicit_uploaded_image_and_video_kinds_win():
    assert uploaded_media_kind({"kind": "image", "video_url": "https://x.test/file.mp4"}) == "image"
    assert uploaded_media_kind({"kind": "video", "video_url": "https://x.test/file.png"}) == "video"


def test_legacy_upload_kind_is_inferred_from_url_extension():
    assert uploaded_media_kind({"video_url": "https://x.test/screenshot.PNG?token=1"}) == "image"
    assert uploaded_media_kind({"video_url": "https://x.test/recording.MOV?token=1"}) == "video"


def test_unknown_legacy_upload_defaults_to_video_treatment():
    assert uploaded_media_kind({"video_url": "https://x.test/signed-object"}) == "video"


def test_uploaded_media_has_dedicated_local_only_scene_kinds():
    assert classify_scene_kind({"source": "uploaded", "kind": "image"}, "ai", False) == "uploaded_image"
    assert classify_scene_kind({"source": "uploaded", "kind": "video"}, "ai", True) == "uploaded_video"


def test_only_ai_source_enters_ai_scene_kinds():
    assert classify_scene_kind({"source": "ai"}, "pexels", False) == "ai"
    assert classify_scene_kind({"source": "ai"}, "pexels", True) == "ai_t2v"
    assert classify_scene_kind({"source": "pexels"}, "ai", True) == "stock"


def test_uploaded_scenes_are_excluded_from_ai_visual_cost_count():
    scenes = [
        {"source": "uploaded", "kind": "image"},
        {"source": "uploaded", "kind": "video"},
        {"source": "ai"},
        {"source": "pexels"},
    ]
    assert count_visual_scene_sources(scenes, "ai", 99) == (1, 1, 2)


def test_global_uploaded_source_has_zero_ai_visual_count():
    assert count_visual_scene_sources([], "uploaded", 12) == (0, 0, 12)
