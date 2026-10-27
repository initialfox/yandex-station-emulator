# Mini 2 adapter for yandex-station-web v0.1.4

Copy **all three files** beside the panel's `profiles.py`:

- `mini2_profile.py`
- `mini2_yam.py`
- `mini2_display.py`

Then register the profile once, at the end of `profiles.py`:

```python
from mini2_profile import register
register(globals())
```

Select `model: mini2` in the multi-panel configuration. Use the actual ADB
address; a virtual instance can use its loopback-forwarded ADB port.
Restart the panel to load the adapter. Back up the previous adapter first.

## YAM

The Apps page can install the latest official `yamd-aarch64-linux-musl`,
verify its release SHA256, test the staged executable and start it from
`/data/local/yam`. A 32-bit firmware userspace with an AArch64 kernel can run
this static binary. An ARM32-only kernel is rejected before downloading or
writing the daemon; it needs a separately supported ARM32 release.

YAM listens on **127.0.0.1:8099 inside the speaker**. The authenticated panel
reaches it through ADB forwarding. No unauthenticated YAM port is opened on
the LAN. Packages/settings survive replacement of the daemon; the previous
binary and settings are backed up before replacement. Failed startup restores
the previous binary when one exists. Automatic daemon updates are initially
disabled. Binary package execution retains YAM's explicit opt-in setting.

Package installation, oneshot execution, service start/stop and service
enable/disable use the corresponding YAM APIs. Service stop is `/stop`, not
`/service/stop`, in YAM 0.1.18. Package compatibility checks remain enabled.

Autostart is opt-in. The Linux VM bootstrap checks the persistent flag
`/mini2/bkupgrade/data/local/yam/autostart` and runs the data-only start script
inside the firmware chroot. It creates `/emulator/yam-autostart-supported` only
when that hook is available. `/mini2/data` is an absolute symlink and must not
be dereferenced from outside the chroot as if it were a host-relative path.

On a physical Mini 2 the adapter supports the separate native SysV `S98yam`
hook only when `/etc/init.d` is writable and the existing `rcS` explicitly
runs its `S` scripts. An unrelated existing hook is never overwritten. A
read-only or unknown boot layout keeps manual YAM startup and reports that
autostart is unsupported. Physical hardware was not available for this test;
successful VM tests do not certify persistence on every retail firmware.

## Display and limits

The adapter maps the browser's 36-slot frame to Mini 2's seven-segment digits
1–4 and separate degree/colon/dash LEDs. The eighth segment in each browser
digit has no equivalent and is ignored. Every destination LED is checked
before writing. Frame/text-editor output, pinned frames, date and countdown
are supported; stop and countdown completion restore the saved display.
Temperature requires the real thermal sysfs sensor; the headless VM does
not provide one. A countdown is a visual function, not a verified audible
alarm. Native boot animations, boot sounds, alarms and destructive firmware
restore remain disabled. Onboarding, Bluetooth radio and audible output are
separate emulator features.

The Mini 2 worker serializes its legacy ADB shell requests and shares a
one-second LED cache between polling and streaming. Physical Station 2 and
Mini 3 Pro workers retain their existing profiles.

Validation: eight Linux regression tests; actual VM install/start, release
hash and model detection, temporary Lua oneshot/service and registry binary
package, display write/readback/pin/date/countdown/restore, and YAM autostart
after a real VM reboot. Temporary test packages are removed afterwards.
