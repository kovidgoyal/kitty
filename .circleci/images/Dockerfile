FROM ubuntu:latest

# System setup
RUN apt-get update && apt-get install -y python3-flake8 python3-pip python3-pil clang git openssh-client build-essential libreadline-dev zlib1g-dev libssl-dev libbz2-dev libsqlite3-dev libffi-dev 

# kitty deps
RUN apt-get install -y libgl1-mesa-dev libxi-dev libxrandr-dev libxinerama-dev libxcursor-dev libxcb-xkb-dev libdbus-1-dev libxkbcommon-dev libharfbuzz-dev libpng-dev libfontconfig-dev libpython3-dev libxkbcommon-x11-dev python3-pygments

# Needed to build kitty docs
RUN pip3 install sphinx

# Install multiple pythons
ADD install-python.py /tmp/install-python.py
RUN python3 /tmp/install-python.py py3.5 https://www.python.org/ftp/python/3.5.6/Python-3.5.6.tar.xz
RUN python3 /tmp/install-python.py py3.7 https://www.python.org/ftp/python/3.7.2/Python-3.7.2.tar.xz

LABEL com.circleci.preserve-entrypoint=true
ENTRYPOINT sleep 2h
