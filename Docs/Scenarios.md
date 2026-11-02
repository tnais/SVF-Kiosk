# SVF Kiosk 

This is the use-case-like description of the application used to play videos in a small museum hall.

Due budget constraints, the software will be the most resource effective possible.

Even if this document is in English and the official language of the code will be in English, user messages must be in Italian.

## Systen description

The system will be an off the shelf computer running Debian. It will have a main display, a Bluetooth keyboard and be on a wired network of its own. Operators will hook a laptop to the network and access the system using ssh and a non root user.

# Everyday scenario

In a small museum hall, the guide, a volunteer of the association running the museum, is talking about the activities of the association that keeps that museo alive plus other activities. The "SVF-Kiosk" application is running several videos on a tv screen a sequence of videos all related to the association activties.

But the volunteer needs a peculiar video played. She has a remote that we can assume at this time being something being both a Bluetooth mouse and keyboard, presses a button to trigger a certain video. The current video is interrupted, the requested one starts. Once the requested video ends, the normal rotation of videos restarts.

# Daily routine

The system boots, activates reads the videos list and starts the rotation.

The scenario where the volunteer starts a peculiar video may happen anytime.

# New videos 

1. An SSH connection is used to transfer files to the video repository;
2. A removable media (USB) is mounted by a user connected to the system via SSH. Then he uses normal OS command to copy/move files;
3. With her SSH connection, the user launches a tool that identifies new videos, lists them, and for each video the user will:
   3.1. start the playing of the video on the main computer display to ckeck and identify it;
   3.2. add a display title to be shown in the videos list
   3.3. add a brief description that is shown when the video is selected

The database is stored in a sql-lite storage. Backup is run when the editing tool is started and once the editing is completed. Each video will therefore have an ID, the file path (this allow using subdirectories), the display title (20 characters) and the brief description up to 150 characters.

# Editing the playlist

The playlist is stored in a JSON file with an automatic backup. 

The playlist editor will be a console application with two panels where videos are shown by display title. Black background, white foreground.

The playlist editor will show the available videos on the left panel, the selected playlist on the right panel. 

Available videos will be sorted by display title, playlist videos will be sorted by their playlist position.

TAB key passes the focus from the available video list to the playlist.

When the focus is on the available video list, arrow up moves the selection upward (never above the first video), the down arrow downward (never after the last video). The "C" key causes the deletion of tha video from the database and the file system. Ask confirmation twice!

Enter key causes the selected video to be added at the end of the playlist. The selection is shown by showing the row in reverse. Videos selected in the playlist turn blue and can not be deleted (beep and error). 

When the focus is on the playlist, arrow up moves the selection upward (never above the first video), the down arrow downward (never after the last video). As usual, the selected video is in reverse. Enter key activates the current video, turning the color green. 

Once the video is active arrow up moves the video up (never above the first positin), the down arrow down (never after the last position). The "D" key removes the video from the list (it returns white in the available video list, if displayed). Enter key on an active video "deactivates" it.
