#!/usr/bin/python3
"""Expose the firmware's onboarding GATT through an unused host BlueZ adapter.

Requires python3-dbus/python3-gi and a loopback ADB forward to the guest's
system bus. No pairing payloads or credentials are logged or stored here.
"""
import argparse
import logging
import subprocess
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

PROPS = 'org.freedesktop.DBus.Properties'
MANAGER = 'org.freedesktop.DBus.ObjectManager'
CHAR = 'org.bluez.GattCharacteristic1'
SERVICE = 'org.bluez.GattService1'
ADV = 'org.bluez.LEAdvertisement1'
DEST = 'ru.yandex.quasar'
ROOT = '/ru/yandex/quasar/gatt'


class Mirror(dbus.service.Object):
    def __init__(self, host, guest, path, interface, properties):
        super().__init__(host, path)
        self.object_path = str(path)
        self.interface = interface
        self.properties = dict(properties)
        if interface == CHAR and 'read' not in self.properties.get('Flags', []):
            self.properties.pop('Value', None)
        self.remote = guest.get_object(DEST, path)
        self.notifying = False

    def call_remote(self, method, *args):
        try:
            return self.remote.get_dbus_method(method, CHAR)(*args, timeout=30)
        except dbus.DBusException as error:
            logging.warning('GATT %s %s failed: %s', self.object_path.rsplit('/', 1)[-1],
                            method, error.get_dbus_name())
            # Firmware errors may include Wi-Fi or account payloads.
            raise dbus.DBusException('Firmware operation failed',
                                    name='org.bluez.Error.Failed') from None

    @dbus.service.method(PROPS, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return self.properties if interface == self.interface else {}

    @dbus.service.method(PROPS, in_signature='ss', out_signature='v')
    def Get(self, interface, name):
        return self.GetAll(interface)[name]

    @dbus.service.method(PROPS, in_signature='ssv', out_signature='')
    def Set(self, interface, name, value):
        if interface != self.interface or name != 'Handle':
            raise dbus.exceptions.DBusException('Read only', name='org.bluez.Error.NotPermitted')
        self.properties[name] = value

    @dbus.service.signal(PROPS, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    @dbus.service.method(CHAR, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        # Device is a host BlueZ object path, not a guest device.
        options = {k: v for k, v in options.items() if k != 'device'}
        value = self.call_remote('ReadValue', options)
        logging.info('GATT read %s (%d bytes)', self.object_path.rsplit('/', 1)[-1], len(value))
        return value

    @dbus.service.method(CHAR, in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        options = {k: v for k, v in options.items() if k != 'device'}
        self.call_remote('WriteValue', value, options)
        logging.info('GATT write %s (%d bytes)', self.object_path.rsplit('/', 1)[-1], len(value))

    @dbus.service.method(CHAR, in_signature='', out_signature='')
    def StartNotify(self):
        logging.info('GATT notify start %s', self.object_path.rsplit('/', 1)[-1])
        if not self.notifying:
            self.call_remote('StartNotify')
            self.notifying = True

    @dbus.service.method(CHAR, in_signature='', out_signature='')
    def StopNotify(self):
        logging.info('GATT notify stop %s', self.object_path.rsplit('/', 1)[-1])
        if self.notifying:
            self.call_remote('StopNotify')
            self.notifying = False

    @dbus.service.method(CHAR, in_signature='', out_signature='')
    def Confirm(self):
        self.call_remote('Confirm')

    @dbus.service.method(ADV, in_signature='', out_signature='')
    def Release(self):
        logging.info('Advertisement released')


class Application(dbus.service.Object):
    def __init__(self, host, guest):
        super().__init__(host, ROOT)
        objects = guest.get_object(DEST, ROOT).GetManagedObjects(dbus_interface=MANAGER)
        self.objects = {}
        for path, interfaces in objects.items():
            for interface, properties in interfaces.items():
                if interface in (SERVICE, CHAR):
                    # Stable ATT handles prevent stale iOS caches after a bridge
                    # reconnect. Reserve a range beyond built-in host services.
                    offsets = [2, 4, 6, 8, 11, 13]
                    offset = 0 if interface == SERVICE else offsets[int(str(path).rsplit('char', 1)[1])]
                    properties['Handle'] = dbus.UInt16(0x100 + offset)
                    self.objects[str(path)] = Mirror(host, guest, path, interface, properties)
        path = '/ru/yandex/quasar/advertising'
        props = guest.get_object(DEST, path).GetAll(ADV, dbus_interface=PROPS)
        self.advertisement = Mirror(host, guest, path, ADV, props)
        guest.add_signal_receiver(self.changed, signal_name='PropertiesChanged',
                                  dbus_interface=PROPS, bus_name=DEST, path_keyword='path')

    @dbus.service.method(MANAGER, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        return {p: {o.interface: o.properties} for p, o in self.objects.items()}

    def changed(self, interface, changed, invalidated, path=None):
        obj = self.objects.get(str(path))
        if obj and interface == CHAR:
            changed = dict(changed)
            if 'read' not in obj.properties.get('Flags', []):
                changed.pop('Value', None)
            obj.properties.update(changed)
            obj.PropertiesChanged(interface, changed, invalidated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest-bus-port', type=int, default=15557)
    parser.add_argument('--adapter', default='/org/bluez/hci0')
    parser.add_argument('--adb-device', default='127.0.0.1:5556')
    parser.add_argument('--direct-guest-bus', action='store_true', help='Use a private QEMU-forwarded control bus, independently of ADB')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    DBusGMainLoop(set_as_default=True)
    if not args.direct_guest_bus:
        subprocess.run(['adb', 'connect', args.adb_device], check=True, timeout=15,
                       stdout=subprocess.DEVNULL)
        subprocess.run(['adb', '-s', args.adb_device, 'forward',
                        f'tcp:{args.guest_bus_port}',
                        'localfilesystem:/run/dbus/system_bus_socket'], check=True)
    guest = dbus.bus.BusConnection(f'tcp:host=127.0.0.1,port={args.guest_bus_port}')
    host = dbus.SystemBus()
    adapter = host.get_object('org.bluez', args.adapter)
    adapter.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True), dbus_interface=PROPS)
    app = Application(host, guest)
    loop = GLib.MainLoop()
    failed_registration = []

    def failed(error):
        failed_registration.append(True)
        logging.error('BlueZ registration failed: %s', error.get_dbus_name())
        loop.quit()

    def owner_changed(name, old_owner, new_owner):
        if old_owner and old_owner != new_owner:
            failed_registration.append(True)
            logging.info('Bluetooth or firmware service changed; reconnecting')
            loop.quit()

    for bus, name in ((guest, DEST), (host, 'org.bluez')):
        bus.add_signal_receiver(owner_changed, signal_name='NameOwnerChanged',
            dbus_interface='org.freedesktop.DBus', arg0=name)

    def registered():
        adapter.RegisterAdvertisement(app.advertisement.object_path, {},
            dbus_interface='org.bluez.LEAdvertisingManager1',
            reply_handler=lambda: logging.info('Firmware GATT and host BLE advertising ready'),
            error_handler=failed)

    adapter.RegisterApplication(ROOT, {}, dbus_interface='org.bluez.GattManager1',
                                reply_handler=registered, error_handler=failed)
    def health():
        try:
            guest.get_object(DEST, ROOT).Ping(dbus_interface='org.freedesktop.DBus.Peer', timeout=5)
            if not guest.get_is_connected():
                raise RuntimeError('Guest disconnected')
        except Exception:
            failed_registration.append(True)
            logging.error('Guest bus unavailable; reconnecting')
            loop.quit()
            return False
        return True
    GLib.timeout_add_seconds(5, health)
    loop.run()
    if failed_registration:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
