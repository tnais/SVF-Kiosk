#!/bin/sh
# Minimal X11 session for the kiosk (started by svf-x11.service through xinit).
# Responsibilities: disable screen saver/blanking/DPMS and hide the idle cursor.
# The player itself runs as the user service svf-kiosk.service.

# Inhibit screen saver, blanking and DPMS power saving.
xset s off -dpms
xset s noblank

# Hide the mouse cursor after 0.5 s of inactivity.
unclutter -idle 0.5 -root &

# Keep the X session alive for as long as the X server runs.
exec sleep infinity
