import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

INTEGRATION = Path(__file__).resolve().parents[1] / 'integrations/yandex_station_web'
sys.path.insert(0, str(INTEGRATION))
import mini2_display
import mini2_yam


class Mini2Features(unittest.TestCase):
    def test_arm32_kernel_rejected_before_download_or_writes(self):
        server = types.SimpleNamespace(Panel=type('Panel', (), {}), AdbError=RuntimeError)
        mini2_yam.install(server)
        panel = server.Panel()
        panel.adb = Mock()
        panel.adb.shell.return_value = ('armv7l\n', '', 0)
        with patch.object(mini2_yam.urllib.request, 'urlopen') as download:
            with self.assertRaisesRegex(RuntimeError, 'ARM32'):
                panel.yam_install_daemon()
            download.assert_not_called()
        panel.adb.push.assert_not_called()
        panel.adb.shell.assert_called_once_with('uname -m')

    def test_service_lifecycle_uses_separate_api_and_oneshot_keeps_old_path(self):
        original = Mock(return_value={'ok': True})
        server = types.SimpleNamespace(Panel=type('Panel', (), {'yam_action': original}))
        mini2_yam.install(server)
        panel = server.Panel()
        panel.yam_plugins = lambda: [{'manifest': {'id': 'background', 'launch': {'mode': 'service'}}}]
        panel._yam = Mock()
        panel.yam_action('run', 'background')
        panel._yam.assert_called_with('POST', '/api/plugins/background/service/start')
        panel.yam_action('stop', 'background')
        panel._yam.assert_called_with('POST', '/api/plugins/background/stop')
        panel.yam_action('run', 'oneshot')
        original.assert_called_once_with(panel, 'run', 'oneshot')

    def test_native_autostart_never_overwrites_an_unrelated_init_script(self):
        server = types.SimpleNamespace(Panel=type('Panel', (), {}), AdbError=RuntimeError)
        mini2_yam.install(server)
        panel = server.Panel()
        panel.yam_status = lambda: {'installed': True}
        panel.adb = Mock()
        panel.adb.shell.side_effect = [('', '', 0), ('native', '', 0), ('# owned by someone else', '', 0)]
        with self.assertRaisesRegex(RuntimeError, 'сохранён'):
            panel.yam_autostart(True)
        panel.adb.push.assert_not_called()

    @unittest.skipIf(sys.platform == 'win32', 'generated shell integration runs on Linux')
    def test_actual_generated_frame_script_writes_only_mini2_paths_and_restores(self):
        server = types.SimpleNamespace(Panel=type('Panel', (), {}), AdbError=RuntimeError)
        mini2_display.install(server, {'display_status': lambda self: None, 'clock_frames': lambda self: None})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / 'leds/mini2:white:clock'
            for name in mini2_display.NAMES:
                target = Path(str(prefix) + name) / 'brightness'
                target.parent.mkdir(parents=True)
                target.write_text('7\n')
            uploaded = root / 'once.sh'
            snapshot = root / 'snapshot'

            class Adb:
                def push(self, source, remote):
                    script = Path(source).read_text().replace('/sys/class/leds/mini2:white:clock', str(prefix))
                    script = script.replace('/tmp/mini2-panel-clock.before', str(snapshot))
                    uploaded.write_text(script)

                def shell(self, command, **kwargs):
                    if command == 'sh /tmp/mini2-panel-once.sh':
                        subprocess.run(['sh', str(uploaded)], check=True, capture_output=True)
                    elif command.startswith('L='):
                        command = command.replace('/sys/class/leds/mini2:white:clock', str(prefix))
                        command = command.replace('/tmp/mini2-panel-clock.before', str(snapshot))
                        subprocess.run(['sh', '-c', command], check=True, capture_output=True)
                    return '', '', 0

            panel = server.Panel()
            panel.adb = Adb()
            frame = [index for index in range(36)]
            panel.clock({'v': frame})
            for name, value in zip(mini2_display.SLOTS, frame):
                if name:
                    self.assertEqual(int((Path(str(prefix) + name) / 'brightness').read_text()), value)
            panel.display_stop()
            for name in mini2_display.NAMES:
                self.assertEqual(int((Path(str(prefix) + name) / 'brightness').read_text()), 7)


if __name__ == '__main__':
    unittest.main()
