from patchnote_prasia.analyze import analyze_patch_note, normalize_plain_text


def test_analyze_patch_note_assigns_class_policy():
    text = """
    신규 클래스 야만투사
    야만투사는 단일 스탠스를 사용합니다.
    야만투사 전승 스킬은 아래와 같습니다.
    """

    analyses = analyze_patch_note("3/25 패치노트", text)

    assert analyses
    tags = [tag for analysis in analyses for tag in analysis.tags]
    class_tags = [tag for tag in tags if tag.topic_type == "class"]
    assert class_tags
    assert any(tag.topic_key == "야만투사" for tag in class_tags)
    assert all(tag.preserve_history for tag in class_tags)
    assert all(not tag.prefer_latest for tag in class_tags)


def test_analyze_patch_note_assigns_event_policy():
    text = """
    봄맞이 출석 이벤트
    이벤트 기간 동안 보상을 획득할 수 있습니다.
    """

    analyses = analyze_patch_note("이벤트 안내", text)

    event_tags = [
        tag
        for analysis in analyses
        for tag in analysis.tags
        if tag.topic_type == "event"
    ]
    assert event_tags
    assert all(tag.preserve_history for tag in event_tags)
    assert all(not tag.prefer_latest for tag in event_tags)


def test_analyze_patch_note_splits_long_sections():
    long_line = "전투 밸런스 조정 내용입니다. " * 120

    analyses = analyze_patch_note("밸런스 조정", long_line)

    assert len(analyses) > 1
    assert all(analysis.chunk.token_count > 0 for analysis in analyses)


def test_normalize_plain_text_merges_broken_heading_lines():
    text = "3/25(\n수) 프라시아 전기 업데이트 내용을 안내 드립니다.\n┃\n야만투사"

    normalized = normalize_plain_text(text)
    analyses = analyze_patch_note("3/25 패치노트", normalized)

    assert "3/25(수) 프라시아 전기 업데이트 내용을 안내 드립니다." in normalized
    assert "┃ 야만투사" in normalized
    assert analyses[0].chunk.chunk_text != "3/25("


def test_analyze_patch_note_filters_generic_world_open_keys():
    text = """
    신규 서버 오픈 안내
    전체 서버 대상 이벤트가 진행됩니다.
    """

    analyses = analyze_patch_note("신규 서버 오픈 안내", text)

    world_tags = [
        tag
        for analysis in analyses
        for tag in analysis.tags
        if tag.topic_type == "world_open"
    ]
    assert world_tags == []


def test_analyze_patch_note_extracts_explicit_world_open_name():
    text = "신규 서버 페넬로페 오픈\n페넬로페 서버가 새롭게 추가됩니다."

    analyses = analyze_patch_note("신규 서버 페넬로페 오픈", text)

    world_tags = [
        tag
        for analysis in analyses
        for tag in analysis.tags
        if tag.topic_type == "world_open"
    ]
    assert any(tag.topic_key == "페넬로페" for tag in world_tags)


def test_analyze_patch_note_ignores_after_world_open_phrase():
    text = "트렌체 월드 오픈 후 보상 이벤트가 진행됩니다."

    analyses = analyze_patch_note("트렌체 월드 오픈 후 이벤트", text)

    world_tags = [
        tag
        for analysis in analyses
        for tag in analysis.tags
        if tag.topic_type == "world_open"
    ]
    assert world_tags == []


def test_analyze_patch_note_assigns_balance_history_policy():
    analyses = analyze_patch_note("밸런스 조정", "전투 밸런스 조정과 상향 내용입니다.")

    balance_tags = [
        tag
        for analysis in analyses
        for tag in analysis.tags
        if tag.topic_type == "balance"
    ]

    assert balance_tags
    assert all(tag.preserve_history for tag in balance_tags)
    assert all(not tag.prefer_latest for tag in balance_tags)


def test_analyze_patch_note_keeps_parent_section_context():
    text = """
    신규 클래스 야만투사
    ┃ 야만투사
    야만투사 소개입니다.
    ◾ 주요 스킬 정보
    늑대의 습격이 추가됩니다.
    """

    analyses = analyze_patch_note("3/25 패치노트", text)

    assert any(
        tag.topic_type == "class" and tag.topic_key == "야만투사"
        for analysis in analyses[1:]
        for tag in analysis.tags
    )
