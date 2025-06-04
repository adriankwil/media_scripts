#!/bin/bash

# safe tools to say yes to 
apt install vim htop tmux neofetch  -y

# install omv-extras
wget -O - https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | bash
