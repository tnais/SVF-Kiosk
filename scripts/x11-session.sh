#!/bin/sh
# Minimal X11 session for the kiosk: no screen blanking, hidden cursor.
# The player itself runs as the user service svf-kiosk.service.

xset s off -dpms
xset s noblank

unclutter -idle 0.5 -root &

# Keep the X session alive for as long as the X server runs.
exec sleep infinity
