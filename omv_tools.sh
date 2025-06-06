#!/bin/bash

# add basic aliases
echo "PS1='\[\e]0;\u@\h: \w\a\]${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w \$\[\033[00m\] '" >> .bashrc
echo "alias la='ls $LS_OPTIONS -lah'" >> ~/.bashrc
echo "alias vpn_test='curl -sS https://am.i.mullvad.net/connected'" >> ~/.bashrc

# disable motd
touch ~/.hushlogin

# install omv-extras
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | bash

# safe tools to say yes to 
apt install vim htop tmux neofetch curl man -y

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
