"""Optional yandex-station-web v0.1.4 profile for this Mini 2 emulator.

Copy beside profiles.py, then append `from mini2_profile import register;
register(globals())` to profiles.py. Does not replace existing model profiles.
"""
import shlex
import threading
import time


def register(namespace):
    namespace['PROFILES']['mini2'] = dict(
        name='Станция Мини 2 (виртуальная)', platform='mini2',
        clock=True, boot=False, alarms=False, light=True, experimental=True,
    )
    original = namespace['install']

    def install(server, model='lite2', auto=False):
        base_methods = {name: getattr(server.Panel, name) for name in ('display_status', 'clock_frames') if hasattr(server.Panel, name)}
        original(server, model, auto)
        if model != 'mini2':
            return
        import mini2_yam
        mini2_yam.install(server)
        if base_methods:
            import mini2_display
            mini2_display.install(server, base_methods)
        original_shell = server.Adb.shell

        def serialized_shell(self, command, timeout=15, check=True):
            # This legacy ARM32 daemon is shared by all requests in its worker.
            # Keep concurrent tabs from opening overlapping shell sessions.
            with self.lock:
                return original_shell(self, command, timeout=timeout, check=check)

        server.Adb.shell = serialized_shell
        snapshot_lock = threading.Lock()
        snapshot = {'adb': None, 'at': 0, 'value': None}
        ring_names = [f'mini2:{color}:ring{i}' for i in range(1, 7) for color in ('red', 'green', 'blue')]
        # Map the Mini 2 seven-segment display to the panel's eight-segment slots.
        clock_names = [f'mini2:white:clock{segment}{digit}' for digit in range(1, 5) for segment in 'ABCDEFG']

        def leds(self):
            names = clock_names + ring_names
            # The emulated sysfs uses regular files. A firmware truncate/write
            # can briefly expose an empty value; preserve its slot as zero.
            command = ('cd /sys/class/leds; for n in ' + ' '.join(map(shlex.quote, names)) +
                       '; do v=; IFS= read -r v < "$n/brightness" || :; '
                       'case "$v" in ""|*[!0-9]*) v=0;; esac; printf "%s\\n" "$v"; done')
            output, _, _ = self.adb.shell(command)
            values = [int(line) for line in output.split() if line.isdigit()]
            if len(values) != 46:
                raise server.AdbError('Неполное состояние светодиодов Мини 2')
            clock = []
            for digit in range(4):
                clock += values[digit * 7:digit * 7 + 7] + [0]
            clock += [0] * (len(server.CLOCK_LEDS) - len(clock))
            rings = [values[28+i*3:31+i*3] for i in range(6)]
            return {'v': clock, 'ring': rings[::2], 'ring_all': rings}

        def cached_leds(self):
            # Share one snapshot between the direct clock API and LED stream.
            with snapshot_lock:
                if snapshot['adb'] is not self.adb or time.monotonic() - snapshot['at'] >= 1:
                    value = leds(self)
                    snapshot.update(adb=self.adb, at=time.monotonic(), value=value)
                return snapshot['value']

        server.Panel.clock_state = cached_leds

        class LedStream:
            def __init__(self, adb):
                self.adb = adb

            def get(self):
                return cached_leds(self)

        server.LedStream = LedStream

        def ring(self, data):
            rgb = [max(0, min(255, int(data.get(color, 0)))) for color in ('red', 'green', 'blue')]
            commands = ['cd /sys/class/leds']
            commands += [f'echo {rgb[i % 3]} > {shlex.quote(name + "/brightness")}' for i, name in enumerate(ring_names)]
            self.adb.shell('; '.join(commands))
            return {'ok': True}

        server.Panel.ring = ring

        def reset(self):
            # Firmware owns its animation again on its next frame.
            return ring(self, {'red': 0, 'green': 0, 'blue': 0})

        server.Panel.ring_reset = reset

    namespace['install'] = install
