# When changing this file, go to
# https://cloud.docker.com/repository/docker/kovidgoyal/kitty-test/builds and
# click the "Trigger" button under Automated builds to rebuild 
FROM ubuntu:latest

# make Apt non-interactive
ENV DEBIAN_FRONTEND=noninteractive
RUN echo 'APT::Get::Assume-Yes "true";' > /etc/apt/apt.conf.d/90circleci \
  && echo 'DPkg::Options "--force-confnew";' >> /etc/apt/apt.conf.d/90circleci \
  && echo 'Acquire::Languages "none";' >> /etc/apt/apt.conf.d/90circleci 

# System setup
RUN apt-get update && mkdir -p /usr/share/man/man1 && apt-get install -y python3-flake8 python3-pip python3-pil clang git apt locales sudo openssh-client ca-certificates tar gzip parallel net-tools netcat unzip zip bzip2 gnupg curl wget build-essential apt-utils

# Setup circleci user
RUN groupadd --gid 3434 circleci \
  && useradd --uid 3434 --gid circleci --shell /bin/bash --create-home circleci \
  && echo 'circleci ALL=NOPASSWD: ALL' >> /etc/sudoers.d/50-circleci \
  && echo 'Defaults    env_keep += "DEBIAN_FRONTEND"' >> /etc/sudoers.d/env_keep \
  && echo 'Defaults    env_keep += "SW"' >> /etc/sudoers.d/env_keep \
  && echo 'Defaults    env_keep += "LANG"' >> /etc/sudoers.d/env_keep

# Set timezone to UTC by default
RUN ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime

# Use unicode
RUN locale-gen en_US.UTF-8 || true
ENV LANG=en_US.UTF-8

# Deps needed for building python
RUN apt-get install -y libreadline-dev zlib1g-dev libssl-dev libbz2-dev libsqlite3-dev libffi-dev

# kitty deps
RUN apt-get install -y libgl1-mesa-dev libxi-dev libxrandr-dev libxinerama-dev libxcursor-dev libxcb-xkb-dev libdbus-1-dev libxkbcommon-dev libharfbuzz-dev libpng-dev libfontconfig-dev libpython3-dev libxkbcommon-x11-dev python3-pygments libcanberra-dev

# Needed to build kitty docs
RUN pip3 install sphinx

# Install multiple pythons
ADD install-python.py /tmp/install-python.py
RUN python3 /tmp/install-python.py py3.5 https://www.python.org/ftp/python/3.5.6/Python-3.5.6.tar.xz
RUN python3 /tmp/install-python.py py3.7 https://www.python.org/ftp/python/3.7.2/Python-3.7.2.tar.xz

# Install kitty bundle
ENV SW=/home/circleci/sw
RUN python3 /tmp/install-python.py bundle https://download.calibre-ebook.com/travis/kitty/linux-64.tar.xz
RUN echo SW=$SW >> /etc/environment

# Clean unused files
RUN apt-get clean -y

USER circleci

LABEL com.circleci.preserve-entrypoint=true
ENTRYPOINT sleep 2h
