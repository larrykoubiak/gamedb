import unittest

from gamedb.exo.works import source_work_aliases


def source(entry, source_list, title, *, aliases=(), choices=None, **fields):
    record = {
        "entry_key": entry,
        "source_list": source_list,
        "title": title,
        "aliases": [{"Name": name} for name in aliases],
        "fields": fields,
    }
    editions = [
        {
            "entry_key": entry,
            "work_key": work,
            "work_title": name,
            "label": label,
            "is_mod": False,
        }
        for work, name, label in (choices or [(entry, title, title)])
    ]
    return record, editions


def reconcile(*sources, reviewed=()):
    rows = source_work_aliases(
        [record for record, _ in sources],
        [edition for _, editions in sources for edition in editions],
        reviewed,
    )
    return {r["alias_key"]: r["work_key"] for r in rows}


class SourceWorksTests(unittest.TestCase):
    def test_one_game_across_new_year_and_platform_specific_database_ids(self):
        name = "3 Skulls of the Toltecs"
        sources = [
            source(
                "dos",
                "MS-DOS",
                name,
                Developer="Revistronic",
                DatabaseID="31494",
                ReleaseDate="1996-01-01",
            ),
            source(
                "scumm",
                "ScummVM",
                name,
                Developer="Revistronic",
                DatabaseID="31494",
                ReleaseDate="1995-12-31",
            ),
            source(
                "win",
                "Windows 9x",
                name,
                Developer="Revistronic",
                DatabaseID="458570",
                ReleaseDate="1996-01-01",
            ),
        ]
        for records in (sources, reversed(sources)):
            self.assertEqual(reconcile(*records), {"win": "dos", "scumm": "dos"})

    def test_documented_alternate_title_requires_independent_evidence(self):
        fields = {
            "Developer": "Revolution",
            "Publisher": "Virgin",
            "ReleaseDate": "1996-10-01",
        }
        dos = source(
            "dos", "MS-DOS", "Circle of Blood", aliases=["Broken Sword"], **fields
        )
        scumm = source("scumm", "ScummVM", "Broken Sword", **fields)
        self.assertEqual(reconcile(dos, scumm), {"scumm": "dos"})
        same_name = source(
            "other",
            "Windows 9x",
            "Broken Sword",
            Developer="Another studio",
            ReleaseDate="1996-10-01",
        )
        self.assertEqual(reconcile(dos, same_name), {})

    def test_reused_ids_and_bad_alternate_names_cannot_join_sequels_or_remakes(self):
        fields = {
            "Developer": "Sierra",
            "DatabaseID": "123",
            "ReleaseDate": "1995-01-01",
        }
        for title in ("Space Quest II", "Space Quest (Remake)", "Space Quest (Demo)"):
            dos = source("dos", "MS-DOS", "Space Quest", aliases=[title], **fields)
            scumm = source("scumm", "ScummVM", title, **fields)
            self.assertEqual(reconcile(dos, scumm), {})
        hack = source(
            "win", "Windows 9x", "Space Quest", ReleaseType="ROM Hack", **fields
        )
        self.assertEqual(reconcile(dos, hack), {})

    def test_bundle_metadata_only_identifies_its_original_game(self):
        fields = {
            "Developer": "Trilobyte",
            "Publisher": "Virgin",
            "ReleaseDate": "1995-01-01",
        }
        dos = source("dos", "MS-DOS", "The 11th Hour", **fields)
        scumm = source(
            "scumm",
            "ScummVM",
            "11th Hour, The",
            choices=[
                ("original", "11th Hour, The", "The 11th Hour (DOS CD)"),
                ("film", "11th Hour, The - Making Of", "The 11th Hour - Making Of"),
                ("sequel", "The 7th Guest", "The 7th Guest (DOS)"),
            ],
            **fields,
        )
        self.assertEqual(reconcile(dos, scumm), {"original": "dos"})
        remake = source(
            "remake-pack",
            "ScummVM",
            "The 11th Hour",
            choices=[
                ("redrawn", "The 11th Hour", "The 11th Hour (DOS Remake)"),
                ("sequel", "A sequel", "A sequel (DOS)"),
            ],
            **fields,
        )
        self.assertEqual(reconcile(dos, remake), {})

    def test_an_ambiguous_record_cannot_bridge_independent_games(self):
        fields = {
            "Developer": "Studio",
            "Publisher": "Publisher",
            "ReleaseDate": "1995-01-01",
        }
        one = source("one", "MS-DOS", "One", **fields)
        two = source("two", "MS-DOS", "Two", **fields)
        bridge = source(
            "bridge", "ScummVM", "Mixed attribution", aliases=["One", "Two"], **fields
        )
        self.assertEqual(reconcile(one, bridge, two), {})

    def test_reviewed_edition_keeps_a_direct_link_when_a_third_source_matches(self):
        fields = {"Developer": "Studio", "ReleaseDate": "1996-01-01"}
        dos = source("dos", "MS-DOS", "Title", **fields)
        win = source("win", "Windows 9x", "Title", **fields)
        scumm = source("scumm", "ScummVM", "Different localized title")
        reviewed = [
            {
                "alias_key": "scumm",
                "work_key": "win",
                "match_basis": "matching game data",
            }
        ]
        self.assertEqual(
            reconcile(scumm, win, dos, reviewed=reviewed),
            {"win": "dos", "scumm": "dos"},
        )
        self.assertEqual(reconcile(dos, scumm, reviewed=reviewed), {})
