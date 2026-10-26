from exscriptor.assemble import split_sections


def test_unnumbered_body_starts_new_section_without_losing_printed_words():
    structure = {
        'headings': {'paragraphus': r'^\*\*\d+\.\*\*'},
        'body_starts': {'paragraphus': r'^Secunda doctrina\b'},
        'sections': [
            {'key': 'p1', 'type': 'paragraphus'},
            {'key': 'unnumbered', 'type': 'paragraphus'},
            {'key': 'p3', 'type': 'paragraphus'},
        ],
    }
    text = '**1.** Primus textus.\n\nSecunda doctrina sine numero.\n\n**3.** Tertius textus.'

    sections, errors = split_sections(text, structure)

    assert errors == []
    assert sections == {
        'p1': 'Primus textus.',
        'unnumbered': 'Secunda doctrina sine numero.',
        'p3': 'Tertius textus.',
    }


def test_body_starts_preserve_bold_openers_without_any_heading_patterns():
    structure = {
        'body_starts': {'paragraphus': r'^\*\*(?:Prima|Secunda) doctrina\*\*'},
        'sections': [
            {'key': 'first', 'type': 'paragraphus'},
            {'key': 'second', 'type': 'paragraphus'},
        ],
    }
    text = '**Prima doctrina** manet.\n\n**Secunda doctrina** quoque manet.'

    sections, errors = split_sections(text, structure)

    assert errors == []
    assert sections == {
        'first': '**Prima doctrina** manet.',
        'second': '**Secunda doctrina** quoque manet.',
    }


def test_bold_body_start_is_not_consumed_as_preceding_heading_title():
    structure = {
        'headings': {'liber': r'^\*\*LIBER'},
        'body_starts': {'paragraphus': r'^\*\*Prima doctrina\*\*$'},
        'title_line': True,
        'node_types': ['liber'],
        'sections': [
            {'key': 'book', 'type': 'liber'},
            {'key': 'first', 'type': 'paragraphus', 'parent': 'book'},
        ],
    }
    text = '**LIBER I.**\n\n**Prima doctrina**\n\nCorpus manet.'

    sections, errors = split_sections(text, structure)

    assert errors == []
    assert sections == {'first': '**Prima doctrina**\n\nCorpus manet.'}
