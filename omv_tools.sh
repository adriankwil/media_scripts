#!/bin/bash

# add basic aliases
echo "PS1='\[\e]0;\u@\h: \w\a\]${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w \$\[\033[00m\] '" >> .bashrc
echo "alias la='ls $LS_OPTIONS -lah'" >> ~/.bashrc
echo "alias vpn='curl -sS https://am.i.mullvad.net/connected'" >> ~/.bashrc
echo "alias audio_strip='python3 ~/media_scripts/audio_strip.py'" >> ~/.bashrc

# disable motd
touch ~/.hushlogin

# install omv-extras
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | bash

# safe tools to say yes to 
apt install vim htop tmux neofetch curl man mediainfo -y

# install latest version of ffmpeg as a static build
# (because apt only has old version which doesnt work well with TrueHD and doesnt detect Atmos)
# wget -O ~/ffmpeg.tar.xz https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n7.1-latest-linux64-gpl-7.1.tar.xz
wget -O ~/ffmpeg.tar.xz https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
tar -xf ~/ffmpeg.tar.xz
mv ~/ffmpeg-*/bin/ffmpeg ~/ffmpeg-*/bin/ffprobe /usr/local/bin/.
rm ~/ffmpeg.tar.xz
# to remove an old ffmpeg/ffprobe version, delete them from /usr/local/bin


# add git st alias
git config --global alias.st status
# make vim default git editor
git config --global core.editor "vim"
# add name to git
git config --global user.name "adrian"
git config --global user.email "adriankwil@gmail.com"

# add neofetch to .profile
echo "neofetch" >> ~/.profile

# modify the samba generation script to get rid of the server type as im only using SMB
sudo sed -i 's/ - SMB\/CIFS//g' /srv/salt/omv/deploy/avahi/services/smb.sls
# then restart the server
sudo omv-salt deploy run avahi


# make tab-autocomlete case-insensitive:
# If ~/.inputrc doesn't exist yet: First include the original /etc/inputrc
# so it won't get overriden
if [ ! -a ~/.inputrc ]; then echo '$include /etc/inputrc' > ~/.inputrc; fi

# Add shell-option to ~/.inputrc to enable case-insensitive tab completion
echo 'set completion-ignore-case On' >> ~/.inputrc

# enable case-insensitive search in less and also enable colored output
export LESS="IR"

# install croc
curl https://getcroc.schollz.com | bash
