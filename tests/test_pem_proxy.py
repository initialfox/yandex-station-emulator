"""Exercise the adapter protocol with disposable keys and dummy payloads."""
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'qemu/mini2/optee/pem_proxy.c'


def wrap(field, data):
    def varint(value):
        result = bytearray()
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
        return bytes(result)
    return varint(field * 8 + 2) + varint(len(data)) + data


@unittest.skipUnless(shutil.which('cc') and shutil.which('openssl') and hasattr(socket, 'AF_UNIX'),
                     'Requires a Unix C toolchain and OpenSSL development libraries')
class PemProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pem-proxy-')
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / 'proxy'
        # Native start code is used for this protocol test; ARM32 runtime is
        # separately built against the firmware libraries and tested in QEMU.
        subprocess.run(['cc', '-O2', '-Wno-deprecated-declarations', str(SOURCE),
                        '-lcrypto', '-o', str(cls.binary)], check=True, capture_output=True)
        cls.private = cls.root / 'private.pem'
        cls.public = cls.root / 'public.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                        'rsa_keygen_bits:2048', '-out', str(cls.private)],
                       check=True, capture_output=True)
        cls.private.chmod(0o600)
        subprocess.run(['openssl', 'pkey', '-in', str(cls.private), '-pubout',
                        '-out', str(cls.public)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.sock = self.root / 'proxy.sock'
        self.process = subprocess.Popen([str(self.binary), str(self.private),
                                         str(self.public), str(self.sock)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        for _ in range(100):
            if self.sock.exists():
                return
            if self.process.poll() is not None:
                self.fail('Adapter exited before listening')
            time.sleep(0.01)
        self.fail('Adapter did not listen')

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=3)
        self.sock.unlink(missing_ok=True)

    def query(self, request):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(self.sock))
            connection.sendall(b'\x42\xfa\x85\x1f' + struct.pack('>I', len(request)) + request)
            def exact(length):
                data = b''
                while len(data) < length:
                    part = connection.recv(length - len(data))
                    self.assertTrue(part)
                    data += part
                return data
            header = exact(8)
            self.assertEqual(header[:4], b'\x42\xfa\x85\x1f')
            return exact(struct.unpack('>I', header[4:])[0])

    def test_export_is_spki_der(self):
        expected = subprocess.check_output(['openssl', 'pkey', '-pubin', '-in',
                                            str(self.public), '-outform', 'DER'])
        self.assertEqual(self.query(wrap(3, b'')), wrap(4, wrap(1, expected)))

    def test_decryption_and_invalid_ciphertext(self):
        plaintext = b'Disposable onboarding regression fixture'
        for mode in ('pkcs1', 'oaep', 'oaep-sha256'):
            with self.subTest(mode=mode):
                args = ['openssl', 'pkeyutl', '-encrypt', '-pubin', '-inkey', str(self.public),
                        '-pkeyopt', 'rsa_padding_mode:' + ('oaep' if 'oaep' in mode else 'pkcs1')]
                if mode == 'oaep-sha256':
                    args += ['-pkeyopt', 'rsa_oaep_md:sha256']
                ciphertext = subprocess.check_output(args, input=plaintext)
                self.assertEqual(self.query(wrap(2, wrap(1, ciphertext))), wrap(3, wrap(1, plaintext)))
        # All-zero RSA input must fail padding checks, never return raw bytes.
        self.assertEqual(self.query(wrap(2, wrap(1, bytes(256)))), wrap(1, b'\x08\x01'))

    def test_signature_matches_openssl(self):
        payload = b'Disposable signing regression fixture'
        signature = subprocess.check_output(['openssl', 'dgst', '-sha256', '-sign',
                                             str(self.private)], input=payload)
        self.assertEqual(self.query(wrap(1, wrap(1, payload))), wrap(2, wrap(1, signature)))

    def test_mismatched_pair_rejected(self):
        other = self.root / 'other-public.pem'
        private = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'RSA',
                                           '-pkeyopt', 'rsa_keygen_bits:2048'], stderr=subprocess.DEVNULL)
        other.write_bytes(subprocess.check_output(['openssl', 'pkey', '-pubout'], input=private))
        result = subprocess.run([str(self.binary), str(self.private), str(other),
                                 str(self.root / 'mismatch.sock')], capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 5)
        self.assertFalse((self.root / 'mismatch.sock').exists())


if __name__ == '__main__':
    unittest.main()
