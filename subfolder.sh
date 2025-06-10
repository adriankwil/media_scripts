#!/usr/bin/env bash
# move_mkvs_into_folders.sh
# Finds every .mkv in the current directory, makes a folder
# with the same basename, and moves the file inside it.

shopt -s nullglob        # ignore patterns that match nothing
for f in *.mp4; do
    basename="${f%.*}"                      # strip the extension
    echo "mkdir -p -- $basename"            # create the folder if it doesn't exist
    mkdir -p -- "$basename"                # create the folder if it doesn't exist
    
    echo "mv -- $f $basename/."             # move the file into the folder 
    mv -- "$f" "$basename/."               # move the file into the folder 
    
    echo "touch -r $basename/$f $basename"  # apply the modification date of the file to its folder
    touch -r "$basename/$f" "$basename"
    
    echo
done
