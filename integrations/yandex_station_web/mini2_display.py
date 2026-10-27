"""Mini 2 seven-segment display; never writes Light 2 LED names."""
from pathlib import Path
import tempfile

# Browser uses four eight-segment cells followed by degree/colon/dash.
# Mini 2 has seven segments per digit and separate PLUS/MINUS indicators.
SLOTS = [f'{segment}{digit}' if segment != 'H' else None
         for digit in range(1, 5) for segment in 'ABCDEFGH'] + ['DEGREE', 'PLUS1', 'PLUS2', 'MINUS']
NAMES = [name for name in SLOTS if name]


def install(s, base_methods):
    prefix = '/sys/class/leds/mini2:white:clock'
    snapshot = '/tmp/mini2-panel-clock.before'

    def restore_sh():
        return (f'L={prefix}; S={snapshot}\n'
                'save() { [ -f "$S" ] && return; : >"$S"; '
                f'for n in {" ".join(NAMES)}; do v=; IFS= read -r v <"$L$n/brightness" || :; '
                'printf "%s %s\\n" "$n" "${v:-0}"; done >"$S"; }\n'
                'restore() { if [ -f "$S" ]; then while read -r n v; do '
                'echo "$v" >"$L$n/brightness"; done <"$S"; rm -f "$S"; fi; }\n')

    def write(frame):
        return '\n'.join(f'echo {value} >"${{L}}{name}/brightness"' for name, value in zip(SLOTS, frame) if name)

    def normalize(frame):
        if not isinstance(frame, list) or len(frame) != 36:
            raise s.AdbError('Нужно 36 значений кадра')
        return [max(0, min(255, int(value))) for value in frame]

    def launch(self, script):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'display.sh'
            path.write_bytes(script.encode('utf8'))
            self.adb.push(path, '/tmp/mini2-panel-display.sh')
        self.detach('display', 'exec sh /tmp/mini2-panel-display.sh')

    def stop(self):
        self.adb.shell('f=/tmp/webpanel_display.sd; if [ -f "$f" ]; then '
                       'p=$(cat "$f"); kill "$p" 2>/dev/null; '
                       'for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$p" 2>/dev/null || break; usleep 100000; done; '
                       'rm -f "$f"; fi; true')
        self.adb.shell(restore_sh() + 'restore; rm -f /tmp/webpanel_display.mode; true')
        return {'mode': None}

    def preflight(self):
        # Validate every mapped LED before touching a display on real hardware.
        self.adb.shell(f'L={prefix}; for n in {" ".join(NAMES)}; do '
                       'test -r "$L$n/brightness" && test -w "$L$n/brightness" || exit 1; done')

    def clock(self, data):
        preflight(self)
        if 'v' not in data:
            raise s.AdbError('Для Мини 2 передайте кадр v из редактора дисплея')
        frame = normalize(data['v'])
        stop(self)
        # Upload instead of exceeding the legacy adbd command-length limit.
        script = '#!/bin/sh\n' + restore_sh() + 'save\n' + write(frame) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'once.sh'
            path.write_bytes(script.encode('utf8'))
            self.adb.push(path, '/tmp/mini2-panel-once.sh')
        self.adb.shell('sh /tmp/mini2-panel-once.sh')
        return {'ok': True}

    def display(self, data):
        preflight(self)
        mode = data.get('mode')
        if mode not in ('frame', 'date', 'temp', 'timer'):
            raise s.AdbError('Неизвестный режим дисплея')
        frame = normalize(data['v']) if mode == 'frame' else None
        bright = max(1, min(255, int(data.get('brightness', 160))))
        seconds = max(1, min(5999, int(data.get('seconds', 1))))
        if mode == 'temp':
            self.adb.shell('test -r /sys/class/thermal/thermal_zone0/temp')
        stop(self)
        script = '#!/bin/sh\n' + restore_sh() + 'save\n'
        script += 'finish() { restore; rm -f /tmp/webpanel_display.mode; exit 0; }; trap finish TERM INT\n'
        script += f'B={bright}\n'
        cases = ' '.join(f'{digit}) segments={segments};;' for digit, segments in s.SEGMENTS.items() if digit.isdigit())
        script += ('draw() { i=1; for c in $(echo "$1" | sed "s/./& /g"); do '
                   f'case "$c" in {cases} *) segments=;; esac; '
                   'for g in A B C D E F G; do case "$segments" in *"$g"*) v=$B;; *) v=0;; esac; '
                   'echo "$v" >"$L$g$i/brightness"; done; i=$((i+1)); done; }\n')
        if mode == 'timer':
            script += f'END=$(( $(date +%s) + {seconds} )); echo "timer $END" >/tmp/webpanel_display.mode\n'
            body = 'r=$((END-$(date +%s))); [ "$r" -gt 0 ] || break; draw "$(printf "%02d%02d" $((r/60)) $((r%60)))"'
        else:
            script += f'echo {mode} >/tmp/webpanel_display.mode\n'
            body = write(frame) if frame else ('draw "$(date +%d%m)"' if mode == 'date' else
                                              't=$(cat /sys/class/thermal/thermal_zone0/temp); draw "$(printf "%4d" $((t/1000)) | tr " " x)"')
        script += 'echo 0 >"${L}PLUS1/brightness"; echo 0 >"${L}PLUS2/brightness"; echo 0 >"${L}MINUS/brightness"; echo 0 >"${L}DEGREE/brightness"\n' if mode != 'frame' else ''
        if mode == 'timer':
            script += 'echo $B >"${L}PLUS1/brightness"; echo $B >"${L}PLUS2/brightness"\n'
        if mode == 'temp':
            script += 'echo $B >"${L}DEGREE/brightness"\n'
        script += 'while :; do\n' + body + '\nusleep 500000\ndone\nfinish\n'
        launch(self, script)
        return {'mode': mode, **({'left': seconds} if mode == 'timer' else {})}

    def animation(self, frames, seconds):
        normalized = s.decode_clock_pattern('.binscled', s.encode_clock_pattern(frames))
        preflight(self)
        stop(self)
        duration = max(1, min(300, int(seconds)))
        script = '#!/bin/sh\n' + restore_sh() + 'save\n'
        script += 'finish() { restore; exit 0; }; trap finish TERM INT\n'
        script += f'END=$(( $(date +%s) + {duration} ))\nwhile [ "$(date +%s)" -lt "$END" ]; do\n'
        for frame in normalized:
            script += write(normalize(frame['v'])) + f'\nusleep {frame["ms"] * 1000}\n'
        script += 'done\nfinish\n'
        launch(self, script)
        return {'ok': True, 'frames': len(normalized)}

    s.Panel.clock = clock
    s.Panel.display_set = display
    s.Panel.display_stop = stop
    s.Panel.display_status = base_methods['display_status']
    s.Panel.play_clock = animation
    s.Panel.clock_frames = base_methods['clock_frames']
    s.Panel.stop_pattern = lambda self, kind=None: stop(self) if kind in (None, 'clock') else self.ring_reset()
