import tempfile

import rhsm.config
from rhsm.config import RhsmConfigParser
from rhsmlib.services.config import Config, ConfigSection

import unittest
import pytest


TEST_CONFIG = r"""
[foo]
bar =
quux = baz
bigger_than_32_bit = 21474836470
bigger_than_64_bit = 123456789009876543211234567890

[server]
hostname = server.example.com
prefix = /candlepin
port = 8443
insecure = 1
proxy_hostname =
proxy_port =
proxy_user =
proxy_password =

[rhsm]
ca_cert_dir = /etc/rhsm/ca-test/
baseurl = https://content.example.com
repomd_gpg_url =
repo_ca_cert = %(ca_cert_dir)sredhat-uep-non-default.pem
productCertDir = /etc/pki/product
entitlementCertDir = /etc/pki/entitlement
consumerCertDir = /etc/pki/consumer
report_package_profile = 1
pluginDir = /usr/lib/rhsm-plugins
some_option = %(repo_ca_cert)stest
manage_repos =

[rhsmcertd]
certCheckInterval = 245

[logging]
default_log_level = DEBUG
"""


@pytest.mark.skip("Enable when 'test_attach.py' is removed.")
class _TestConfigClass(unittest.TestCase):
    expected_sections = ("foo", "server", "rhsm", "rhsmcertd", "logging")

    @classmethod
    def write_temp_file(cls, data) -> tempfile._TemporaryFileWrapper:
        fid = tempfile.NamedTemporaryFile(mode="w+", suffix=".tmp")
        fid.write(data)
        fid.seek(0)
        return fid

    def setUp(self):
        super().setUp()
        self.fid = self.write_temp_file(TEST_CONFIG)
        self.parser = RhsmConfigParser(self.fid.name)
        self.config = Config(self.parser)
        self.addCleanup(self.fid.close)


class TestConfig(_TestConfigClass):
    def test_config_contains(self):
        self.assertTrue("server" in self.config)
        self.assertTrue("not_here" not in self.config)

    def test_config_len(self):
        self.assertEqual(
            len(self.expected_sections),
            len(self.config),
        )

    def test_keys(self):
        self.assertEqual(
            set(self.expected_sections),
            set(self.config.keys()),
        )

    def test_values(self):
        values = list(self.config.values())
        for v in values:
            self.assertIsInstance(v, ConfigSection)

    def test_set_new_section(self):
        self.config['new_section'] = {'hello': 'world'}
        self.assertEqual(['hello'], self.config._parser.options('new_section'))
        self.assertEqual('world', self.config._parser.get('new_section', 'hello'))

    def test_set_old_section(self):
        self.config['foo'] = {'hello': 'world'}
        self.assertEqual(['hello'], self.config._parser.options('foo'))
        self.assertEqual('world', self.config._parser.get('foo', 'hello'))
        self.assertRaises(rhsm.config.NoOptionError, self.config._parser.get, 'foo', 'quux')

    def test_get_item(self):
        self.assertIsInstance(self.config['server'], ConfigSection)

    def test_persist(self):
        self.config['foo'] = {'hello': 'world'}
        self.config.persist()
        reparsed = RhsmConfigParser(self.fid.name)
        self.assertEqual('world', reparsed.get('foo', 'hello'))
        self.assertRaises(rhsm.config.NoOptionError, reparsed.get, 'foo', 'quux')

    def test_auto_persists(self):
        config = Config(self.parser, auto_persist=True)
        config['foo'] = {'hello': 'world'}
        reparsed = RhsmConfigParser(self.fid.name)
        self.assertEqual('world', reparsed.get('foo', 'hello'))
        self.assertRaises(rhsm.config.NoOptionError, reparsed.get, 'foo', 'quux')

    def test_does_not_auto_persist_by_default(self):
        config = Config(self.parser, auto_persist=False)
        config['foo'] = {'hello': 'world'}
        reparsed = RhsmConfigParser(self.fid.name)
        self.assertEqual('baz', reparsed.get('foo', 'quux'))
        self.assertRaises(rhsm.config.NoOptionError, reparsed.get, 'foo', 'hello')

    def test_del_item(self):
        del self.config['foo']
        self.assertFalse(self.config._parser.has_section('foo'))

    def test_iter(self):
        sections = [s for s in self.config]
        self.assertEqual(set(self.expected_sections), set(sections))


class TestConfigSection(_TestConfigClass):
    def test_get_value(self):
        self.assertEqual('1', self.config['server']['insecure'])

    def test_get_missing_value(self):
        with self.assertRaises(KeyError):
            self.config['server']['missing']

    def test_set_item(self):
        self.assertEqual('baz', self.config['foo']['quux'])
        self.config['foo']['quux'] = 'fizz'
        self.assertEqual('fizz', self.config['foo']['quux'])

    def test_auto_persist(self):
        config = Config(self.parser, auto_persist=True)
        self.assertEqual('baz', config['foo']['quux'])
        config['foo']['quux'] = 'fizz'
        self.assertEqual('fizz', config['foo']['quux'])

        reparsed = RhsmConfigParser(self.fid.name)
        self.assertEqual('fizz', reparsed.get('foo', 'quux'))

    def test_persist_cascades(self):
        config = Config(self.parser, auto_persist=False)
        self.assertEqual('baz', config['foo']['quux'])
        config['foo']['quux'] = 'fizz'
        config.persist()
        self.assertEqual('fizz', config['foo']['quux'])

        reparsed = RhsmConfigParser(self.fid.name)
        self.assertEqual('fizz', reparsed.get('foo', 'quux'))

    def test_del_item(self):
        del self.config['foo']['quux']
        self.assertNotIn('quux', self.config['foo'])

        with self.assertRaises(KeyError):
            del self.config['foo']['missing_key']

    def test_len(self):
        self.assertEqual(4, len(self.config['foo']))

    def test_in(self):
        self.assertIn("quux", self.config['foo'])
        self.assertNotIn("missing", self.config['foo'])
