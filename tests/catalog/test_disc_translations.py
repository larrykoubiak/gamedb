from hashlib import sha1, sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from gamedb.catalog.disc_patching import RAW_CD_SECTOR_SIZE, patch_disc_image, repair_xa_form1_checksums
from gamedb.catalog.disc_translations import _publish_project
from gamedb.catalog.patching import PatchError


def ppf_edit(offset, data):
    return b"PPF30\x02" + bytes(54) + offset.to_bytes(8, "little") + bytes([len(data)]) + data


class DiscTranslationTests(unittest.TestCase):
    def test_single_iso_build_keeps_its_launch_filename(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, patch_archive = root / "Example.zip", root / "patch.zip"
            member, step = "Example (USA).iso", "english.ppf"
            original = bytes(2048)
            patched = b"x" + original[1:]
            with ZipFile(source, "w") as rom:
                rom.writestr(member, original)
            with ZipFile(patch_archive, "w") as patches:
                patches.writestr(step, ppf_edit(0, b"x"))
            signature = "a" * 32
            files = {(signature, source.name): [
                {"path": source.name, "name": member, "size": len(original), "verified": True,
                 "sha1": sha1(original).hexdigest()},
            ]}
            review = {"archive": patch_archive.name, "archiveSha256": sha256(patch_archive.read_bytes()).hexdigest(),
                      "discs": [{"archiveName": source.name, "imageMember": member,
                                 "inputSha1": sha1(original).hexdigest(), "outputSha1": sha1(patched).hexdigest(),
                                 "patches": [step]}]}
            build = _publish_project(root, patch_archive, review, "Example", signature, files, root,
                                     {"language": "English", "version": "1.0"})
            with ZipFile(root / "discs" / f"{build['discSet']['sha256']}.zip") as bundle:
                self.assertEqual(bundle.namelist(), [member])
                self.assertEqual(bundle.read(member), patched)

    def test_disc_set_keeps_cues_and_audio_and_creates_a_stable_playlist(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base = bytes(RAW_CD_SECTOR_SIZE)
            audio = bytes([11]) * RAW_CD_SECTOR_SIZE
            translated = b"x" + base[1:]
            signature = "a" * 32
            files, discs, original_members, cues = {}, [], {}, []
            patch_path = root / "patch.zip"
            with ZipFile(patch_path, "w") as patches:
                for number in (1, 2):
                    archive_name = f"Example (USA) (Disc {number}).zip"
                    data_name, audio_name, cue_name = (f"disc {number}.{suffix}"
                                                      for suffix in ("bin", "audio.bin", "cue"))
                    cue = (f'FILE "{data_name}" BINARY\r\n  TRACK 01 MODE2/2352\r\n'
                           f'    INDEX 01 00:00:00\r\nFILE "{audio_name}" BINARY\r\n'
                           f'  TRACK 02 AUDIO\r\n    INDEX 01 00:00:00\r\n').encode()
                    members = {data_name: base, audio_name: audio, cue_name: cue}
                    with ZipFile(root / archive_name, "w") as disc:
                        for name, contents in members.items():
                            disc.writestr(name, contents)
                    files[signature, archive_name] = [
                        {"path": archive_name, "name": name, "size": len(data), "sha1": sha1(data).hexdigest(),
                         "verified": True}
                        for name, data in members.items()
                    ]
                    step = f"disc{number}.ppf"
                    patches.writestr(step, ppf_edit(0, b"x"))
                    discs.append({"archiveName": archive_name, "inputSha1": sha1(base).hexdigest(),
                                  "outputSha1": sha1(translated).hexdigest(), "patches": [step]})
                    original_members.update({**members, data_name: translated})
                    cues.append(cue_name)

            review = {"archive": patch_path.name, "archiveSha256": sha256(patch_path.read_bytes()).hexdigest(),
                      "discs": discs}
            metadata = {"language": "English", "version": "1.0"}
            build = _publish_project(root, patch_path, review, "Example", signature, files, root, metadata)
            self.assertEqual(build, _publish_project(root, patch_path, review, "Example", signature, files,
                                                     root, metadata))
            archive = root / "discs" / f"{build['discSet']['sha256']}.zip"
            original_members["Play.m3u"] = ("\n".join(cues) + "\n").encode()
            with ZipFile(archive) as bundle:
                self.assertEqual(set(bundle.namelist()), original_members.keys())
                for name, contents in original_members.items():
                    self.assertEqual(bundle.read(name), contents)

            discs[0]["outputSha1"] = "0" * 40
            with self.assertRaisesRegex(ValueError, "Patched disc checksum differs"):
                _publish_project(root, patch_path, review, "Example", signature, files, root, metadata)
            self.assertEqual(list(archive.parent.iterdir()), [archive])

    def test_ppf_records_cannot_extend_the_disc(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.bin"
            original.write_bytes(bytes(RAW_CD_SECTOR_SIZE))
            patch = root / "patch.ppf"
            patch.write_bytes(ppf_edit(RAW_CD_SECTOR_SIZE - 1, b"xx"))
            with self.assertRaisesRegex(PatchError, "Invalid PPF3 edit"):
                patch_disc_image(original, patch, root / "patched.bin")
            self.assertEqual(original.read_bytes(), bytes(RAW_CD_SECTOR_SIZE))

    def test_xa_checksum_repair_preserves_data_and_untouched_sectors(self):
        sync_and_header = bytes.fromhex("00 ff ff ff ff ff ff ff ff ff ff 00 00 02 11 02")
        subheader = bytes.fromhex("00 00 08 00") * 2
        payload = sync_and_header + subheader + bytes(range(256)) * 8
        unchanged = bytes([0x5A]) * RAW_CD_SECTOR_SIZE
        with TemporaryDirectory() as directory:
            original = Path(directory) / "original.bin"
            patched = Path(directory) / "patched.bin"
            original.write_bytes(sync_and_header + subheader + bytes(2048 + 280) + unchanged)
            patched.write_bytes(payload + bytes(280) + unchanged)
            repair_xa_form1_checksums(original, patched)
            repaired = patched.read_bytes()
            self.assertEqual(repaired[:len(payload)], payload)
            self.assertEqual(repaired[RAW_CD_SECTOR_SIZE:], unchanged)
            # The reference suffix was generated by ECM's Mode 2 Form 1 encoder.
            self.assertEqual(sha256(repaired[len(payload):RAW_CD_SECTOR_SIZE]).hexdigest(),
                             "8054cecdb86891b6bf127e291c93650a6c92b4c1d955cf6de9e683fcdb26a211")
