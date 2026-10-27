#!/bin/sh
# Firmware clients use chroot-local UNIX socket addresses: run the proxy there.
while [ ! -S /mini2/run/wpa-lan-backend/wlan0 ]; do sleep 1; done
mkdir -p /mini2/run/wpa_supplicant
cp /opt/mini2/wpa-lan-proxy /mini2/tmp/wpa-lan-proxy
while true; do
    chroot /mini2 /tmp/wpa-lan-proxy /run/wpa_supplicant/wlan0 /run/wpa-lan-backend/wlan0 /proc/1/root/opt/mini2/wifi-scan-results
    sleep 2
done
