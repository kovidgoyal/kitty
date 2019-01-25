FROM ubuntu:bionic

RUN apt-get update && apt-get install -y libgl1-mesa-dev libxi-dev libxrandr-dev libxinerama-dev libxcursor-dev libxcb-xkb-dev libdbus-1-dev libxkbcommon-dev libharfbuzz-dev python3

LABEL com.circleci.preserve-entrypoint=true
ENTRYPOINT python -c "import time; time.sleep(100000)"
