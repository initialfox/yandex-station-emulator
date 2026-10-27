#!/bin/sh
while [ ! -S /mini2/run/dbus/system_bus_socket ]; do sleep 1; done
cp /opt/mini2/dbus-control-forward /mini2/tmp/dbus-control-forward
while true; do
    chroot /mini2 /tmp/dbus-control-forward
    sleep 2
done
