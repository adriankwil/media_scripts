#!/bin/bash

# add basic aliases
echo "PS1='\[\e]0;\u@\h: \w\a\]${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w \$\[\033[00m\] '" >> .bashrc
echo "alias la='ls -lah'" >> ~/.bashrc
echo "alias vpn_test='curl -sS https://am.i.mullvad.net/connected'" >> ~/.bashrc

# disable motd
touch ~/.hushlogin

# install omv-extras
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | bash

# safe tools to say yes to 
apt install vim htop tmux neofetch curl -y

# add neofetch to .profile
echo "neofetch" >> ~/.profile
