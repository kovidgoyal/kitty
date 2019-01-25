FROM ubuntu:latest

RUN apt-get update && apt-get install -y libgl1-mesa-dev libxi-dev libxrandr-dev libxinerama-dev libxcursor-dev libxcb-xkb-dev libdbus-1-dev libxkbcommon-dev libharfbuzz-dev libpng-dev python3 python3-flake8 python3-pip python3-pil clang git openssh-client

RUN pip3 install sphinx

LABEL com.circleci.preserve-entrypoint=true
ENTRYPOINT sleep 2h
