"""Dataset downloads: a third party names the file, so nothing it says is
taken on trust – not the path, not the scheme, not the host, not the size.
"""

import io
import os
import tarfile
import unittest
from pathlib import Path

from helpers import TempEnv

from ob import data


class FilenameTest(unittest.TestCase):
    """The name of a download comes out of a URL we did not write."""

    def test_a_percent_encoded_separator_cannot_escape(self):
        # `%2F` used to survive the split and become a real separator again
        # after unquoting, so this produced an absolute path that
        # `downloads / name` then adopted whole.
        self.assertEqual(data._filename("https://x.example/d/%2Fhome%2Fuser%2F.bashrc"), "bashrc")
        self.assertEqual(data._filename("https://x.example/d/a%2F..%2F..%2F.bashrc"), "bashrc")

    def test_a_traversal_is_flattened(self):
        self.assertEqual(data._filename("https://x.example/../../etc/passwd"), "passwd")
        self.assertEqual(data._filename("https://x.example/d/..%2F..%2Fpasswd"), "passwd")

    def test_an_ordinary_name_survives(self):
        self.assertEqual(data._filename("https://x.example/d/freedict-deu-eng-1.0.src.tar.xz?v=2"),
                         "freedict-deu-eng-1.0.src.tar.xz")
        self.assertEqual(data._filename("https://x.example/Unihan.zip"), "Unihan.zip")

    def test_an_empty_name_gets_a_placeholder(self):
        self.assertEqual(data._filename("https://x.example/"), "download")

    def test_the_containment_check_refuses_an_escape(self):
        root = Path(os.environ.get("TMPDIR", "/tmp")) / "omababel-inside-test"
        root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(data._inside(root, Path("ok.tar")), (root / "ok.tar").resolve())
        for bad in (Path("../escaped"), Path("/etc/passwd"), Path("a/../../escaped")):
            with self.assertRaises(ValueError):
                data._inside(root, bad)


class DownloadUrlTest(unittest.TestCase):
    """For a FreeDict dataset the address itself comes from a remote JSON
    document, so it is checked before anything is fetched."""

    def test_only_https_is_accepted(self):
        for bad in ("http://download.freedict.org/x.tar", "file:///etc/passwd",
                    "ftp://download.freedict.org/x.tar", "/etc/passwd", ""):
            with self.assertRaises(ValueError):
                data.check_download_url(bad)

    def test_only_the_hosts_we_publish_are_accepted(self):
        with self.assertRaises(ValueError):
            data.check_download_url("https://evil.example/freedict-deu-eng.src.tar.xz")
        for good in ("https://download.freedict.org/dictionaries/deu-eng/1.0/x.src.tar.xz",
                     "https://kaikki.org/dictionary/German/x.jsonl",
                     "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
                     "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"):
            data.check_download_url(good)

    def test_a_download_is_refused_before_a_socket_is_opened(self):
        with self.assertRaises(Exception):
            data.download("file:///etc/passwd", Path("/tmp/omababel-should-not-exist"))
        self.assertFalse(Path("/tmp/omababel-should-not-exist").exists())


class DatasetIdTest(TempEnv):
    """`status` and `remove` take the id straight from the request."""

    def test_a_traversing_id_is_refused(self):
        for bad in ("../../../home/user/known_hosts", "/etc/passwd", "..", ".hidden", ""):
            with self.assertRaises(ValueError):
                data.index_path(bad)

    def test_a_catalogue_id_still_works(self):
        self.assertEqual(data.index_path("wiktionary-de").name, "wiktionary-de.sqlite")

    def test_remove_refuses_a_traversing_id(self):
        victim = self.data_dir.parent / "precious.sqlite"
        victim.write_text("keep me", encoding="utf-8")
        with self.assertRaises(ValueError):
            data.remove("../precious")
        self.assertTrue(victim.exists())


class ExtractTest(TempEnv):
    """A dictd tarball is a third party's archive."""

    def make_tar(self, path: Path) -> None:
        with tarfile.open(path, "w") as tf:
            for name, mode in (("deep/../../../escaped.index", 0o4777), ("d/a.dict", 0o777)):
                payload = b"x" * 8
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = mode
                tf.addfile(info, io.BytesIO(payload))
            link = tarfile.TarInfo("evil.dict")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)

    def test_nothing_lands_outside_the_folder_and_nothing_is_setuid(self):
        tarball = self.data_dir / "d.tar"
        self.make_tar(tarball)
        folder = self.data_dir / "unpacked"
        data._extract_dictd(tarball, folder)
        names = sorted(p.name for p in folder.iterdir())
        self.assertEqual(names, ["a.dict", "escaped.index"])
        self.assertFalse((self.data_dir / "escaped.index").exists())
        for p in folder.iterdir():
            self.assertEqual(p.stat().st_mode & 0o7777, 0o600, p.name)
            self.assertFalse(p.is_symlink(), p.name)


if __name__ == "__main__":
    unittest.main()
