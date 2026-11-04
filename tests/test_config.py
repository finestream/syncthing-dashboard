import tempfile
import unittest
from pathlib import Path

from syncthing_dashboard.config import ConfigError, load_hosts


class LoadHostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "nas.key").write_text("abc123\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text: str) -> Path:
        path = self.dir / "hosts.toml"
        path.write_text(text)
        return path

    def test_reads_key_from_relative_file_and_strips_newline(self):
        hosts = load_hosts(self.write('[[hosts]]\nname="nas"\nurl="http://nas.example.internal:8384/"\napi_key_file="nas.key"\n'))
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].api_key, "abc123")
        self.assertEqual(hosts[0].url, "http://nas.example.internal:8384")
        self.assertIsNone(hosts[0].ca_file)

    def test_ca_file_relative_to_config(self):
        hosts = load_hosts(self.write('[[hosts]]\nname="nas"\nurl="https://nas:8384"\napi_key_file="nas.key"\nca_file="ca.pem"\n'))
        self.assertEqual(hosts[0].ca_file, str(self.dir / "ca.pem"))

    def test_repr_hides_key(self):
        hosts = load_hosts(self.write('[[hosts]]\nname="nas"\nurl="http://nas:8384"\napi_key_file="nas.key"\n'))
        self.assertNotIn("abc123", repr(hosts[0]))
        self.assertNotIn("abc123", str(hosts))

    def test_inline_key_refused(self):
        with self.assertRaisesRegex(ConfigError, "inline api_key"):
            load_hosts(self.write('[[hosts]]\nname="nas"\nurl="http://nas:8384"\napi_key="abc"\napi_key_file="nas.key"\n'))

    def test_missing_key_file(self):
        with self.assertRaisesRegex(ConfigError, "cannot read api_key_file"):
            load_hosts(self.write('[[hosts]]\nname="nas"\nurl="http://nas:8384"\napi_key_file="missing"\n'))

    def test_empty_key_file(self):
        (self.dir / "empty").write_text("\n")
        with self.assertRaisesRegex(ConfigError, "is empty"):
            load_hosts(self.write('[[hosts]]\nname="nas"\nurl="http://nas:8384"\napi_key_file="empty"\n'))

    def test_duplicate_name(self):
        with self.assertRaisesRegex(ConfigError, "duplicate"):
            load_hosts(self.write(
                '[[hosts]]\nname="nas"\nurl="http://a:8384"\napi_key_file="nas.key"\n'
                '[[hosts]]\nname="nas"\nurl="http://b:8384"\napi_key_file="nas.key"\n'
            ))

    def test_missing_fields_and_no_hosts(self):
        with self.assertRaisesRegex(ConfigError, "needs a string 'url'"):
            load_hosts(self.write('[[hosts]]\nname="nas"\napi_key_file="nas.key"\n'))
        with self.assertRaisesRegex(ConfigError, "at least one"):
            load_hosts(self.write("title = 'x'\n"))

    def test_missing_file_and_bad_toml(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_hosts(self.dir / "nope.toml")
        with self.assertRaises(ConfigError):
            load_hosts(self.write("[[hosts]\n"))


if __name__ == "__main__":
    unittest.main()
