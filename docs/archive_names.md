# Archive-name parsing

The parser interprets archive filenames from `staging.rv_files.game_display_name`.
It is intentionally separate from canonical title/release reconciliation.

The structural implementation is [`gamedb/derive/parser/structure.py`](../gamedb/derive/parser/structure.py),
driven by [`data/reference/source_formats.json`](../data/reference/source_formats.json).
`parse_archive_name(romset, archive_name)` returns:

- a provisional `title_candidate`;
- the original ZIP extension;
- ordered raw tags with delimiters and character offsets;
- a `parsed` or `review` status and explicit issues.

For example:

```text
Example (USA) (En,Fr) (Rev A) [b].zip
```

becomes title candidate `Example` plus four raw tags. Raw spelling, order,
duplicates and delimiters are preserved.

## Structural rules

- Balanced `()` and `[]` groups are scanned without splitting their contents.
- No-Intro and Redump metadata starts at a recognized region group.
- TOSEC metadata starts at its date-and-publisher pair.
- Leading square-bracket groups such as `[BIOS]` are retained as tags.
- TOSEC bare version/revision suffixes are retained as delimiter-free tags.
- Parentheses and square brackets before the metadata boundary remain title text.
- Compound TOSEC names joined by a top-level ` & ` become independent records,
  each with its own title and tags.
- Missing ZIP extensions, malformed delimiters, empty values and `ZZZ-UNK-`
  names are retained and flagged rather than silently repaired.

The parser only identifies structure. It does not merge titles or assert that a
filename describes a verified release.

## Exceptions in the retained export

An audit of all 795,980 distinct archive names found 619 TOSEC/TOSEC-ISO names
containing multiple independently tagged records. These now parse as two to six
records instead of one damaged title.

The remaining non-legacy exceptions are source anomalies rather than another
general grammar:

- two No-Intro sound-data names omit the normally mandatory region;
- three TOSEC names have no valid date/publisher pair (one contains a five-digit year);
- nine TOSEC/TOSEC-ISO names have unmatched delimiters in their metadata suffix;
- five TOSEC names place `.pce` between their tag suffix and `.zip`; a few malformed
  bracket suffixes similarly leave text after the parsed tags.

Delimiter-like punctuation before a valid metadata anchor is treated as title
text; only the metadata suffix must balance. Remaining anomalies stay intact with
explicit review issues. TOSEC names beginning with `ZZZ-UNK-` are excluded from
derived data by policy because the source itself does not identify them. Their
raw rows remain available in `staging.rv_files`.

## Tag classification

[`gamedb/derive/parser/classifier.py`](../gamedb/derive/parser/classifier.py) separately interprets raw
tags using the maintained vocabulary in
[`data/reference/tag_vocabulary.json`](../data/reference/tag_vocabulary.json).

Supported collections are English Translations (Maybe-Intro), No-Intro, Redump,
TOSEC and TOSEC-ISO. Classifications
include regions, languages, versions, revisions, dates, publishers, development
status, media, system requirements and dump flags. Rules shared by No-Intro and
Redump are supplemented by collection-specific media and status vocabularies.
Unknown or contextually ambiguous values remain unclassified.

TOSEC translation flags retain the raw descriptor and additionally extract a
recognized target language, partial-translation marker and patch version when
present. Thus `[tr en v1.3 Dejap]` remains one source tag while supplying
`dump_modification=translated`, `language=en` and `version=1.3` to the catalog.

The English Translations profile inherits No-Intro's structural grammar while
interpreting `[T-En by …]`, `[Hack+T-En …]`, `[i]`, and `[n]` explicitly. It
emits English language, translation version/revision, incomplete-translation,
localized-title, and explicit hack facts as appropriate. Documentation archive
names beginning with `_` remain in inventory but do not become releases.

Every stored tag retains its exact `raw_value`. Where the convention has a marker,
the classifier also separates `identifier` and `value`: `v1.2` becomes `v` plus
`1.2`, while `[cr Elite]` becomes `cr` plus `Elite`. Unprefixed tags such as
`(USA)` have a null identifier and retain `USA` as their value.

Inspect both passes without touching the database:

```sh
python -m gamedb parse-name TOSEC \
  'Example v1.2 (1990)(Publisher)(US)(en)[cr Group].zip' --classify
```

Focused behavior is covered by `tests/derive/test_archive_names.py`,
`tests/derive/test_archive_name_classifier.py`, and `tests/derive/test_extractors.py`. The deriver
stores source records, lossless tags, separate classifications, typed assertions,
and media parts as relational tables in one interpretation pass.
