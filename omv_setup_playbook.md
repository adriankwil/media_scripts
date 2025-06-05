OMV Setup Playbook
===
This file will serve as a guide for setting up OMV through the gui or 
by manually editing or moving files through the terminal. This is to 
instruct all of the things that cant just be run with omv_tools.sh

Ignore the lid being closed
---
find the file `/etc/systemd/logind.conf`
and set these to ignore:
```
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
```
Create a personal user account in OMV
---
Go to OMV user tab and make a user for yourself. Leave all the settings as default. Just ensure its in the users group.\
Permissions can be ignored, these will be set automatically by ext4 and its file permissions.

Mount your filesystems
---
Go to `storage > File Systems` and click the play icon to add existing drives.\

Install omv-extras
---
In a terminal, run:
```
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | bash
```

Set up mergerfs
---
1. Install the mergerfs plugin
2. Create a new pool and use the path option to point to the `media` folder on both the drives.\
   Leave all the setting default and adjust minimum free space to your liking.

Share some folders
---
There are a number of folders that are needed or wanted. Needed folders are really just for docker to use. 
All of the docker_ ones can ideally be put on the internal disk, but for that you need to install the docker 
plugin first, and enable compose. Might need to reboot after this for the internal storage to show up.
Alternatively the plugin `openmediavault-sharerootfs` can be installed to mount the OS drive for use.\
Add all of the below:
|name|path|notes|
|---|---|---|
|docker_compose_files|internal_drive/docker_compose_files|-|
|docker_backup|internal_drive/docker_backup|-|
|docker_data|internal_drive/docker_data|-|
|movies|/srv/mergerfs/media/movies|-|
|tv|/srv/mergerfs/media/tv|-|
|movies0|drive_0/media/movies|**Spinup Prevention**|
|movies1|drive_1/media/movies|**Spinup Prevention**|
|tv0|drive_0/media/tv|**Spinup Prevention**|
|tv1|drive_1/media/tv|**Spinup Prevention**|
- **Spinup Prevention** This is useful for sharing directly to kodi or any media centre as it will stop
  all drives spinning up each time one of them is accessed, as would happen if just the mergerfs
  `movies` or `tv` folder was accessed. These shares can be hidden from samba, but still accessed with
  the path directly.


SMB setup
---
1. Go to `Services > SMB/CIFS > Settings` and check the enabled box. Click save.
2. Go to the 

Copy ssh public key to github
---
go to `github > settings > ssh keys`
and add your key from `/root/.ssh/id_rsa.pub`

Set up wireguard
---
1. Install the wireguard plugin.
2. log into mullvad and generate a new config file.
3. copy that file into the wireguard

Install docker
---
After installing omv-extras, enable `Docker repo` under `system > omv-etras`\
Also install the `compose` plugin.


Install qBittorrent
---
find qBittorrent on dockerhub and copy paste the compose file into `Services > Compose > Files > +` 
but ensure the PUID is 1000 and GUID is 100 so that it behaves as a user and can write to your storage.
