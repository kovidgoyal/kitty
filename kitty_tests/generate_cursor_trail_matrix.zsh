#!/usr/bin/env zsh

# Generate focused/unfocused screenshots for every cursor-trail combination.
# This runs Kitty inside a nested KWin/Xwayland virtual framebuffer, so it does
# not open windows on the user's desktop.

set -e
set -u

if [[ -z ${KITTY_MATRIX_INNER:-} ]]; then
    matrix_runtime=$(mktemp -d /tmp/kitty-cursor-trail-matrix.XXXXXX)
    mkdir -p "$matrix_runtime/runtime"
    chmod 700 "$matrix_runtime/runtime"
    export KITTY_MATRIX_RUNTIME="$matrix_runtime"
    export XDG_RUNTIME_DIR="$matrix_runtime/runtime"
    export KITTY_MATRIX_INNER=1
    exec dbus-run-session -- "$0" "$@" 2>$matrix_runtime/dbus.log
fi

repo_dir=${0:A:h:h}
output_dir=${1:-$repo_dir/kitty_tests/cursor_trail_matrix}
kitty_bin=${KITTY_BIN:-$repo_dir/linux-package/bin/kitty}
kitten_bin=${KITTEN_BIN:-$repo_dir/linux-package/bin/kitten}
target_script=$repo_dir/kitty_tests/cursor_trail_matrix_target.sh

mkdir -p "$output_dir"

export PYTHONHOME=${PYTHONHOME:-$repo_dir/dependencies/linux-amd64}
export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/lib:$repo_dir/dependencies/linux-amd64/lib

kwin_wayland --virtual --xwayland --socket=kitty-matrix --width=774 --height=580 \
    --no-global-shortcuts >$KITTY_MATRIX_RUNTIME/kwin.log 2>&1 &
kwin_pid=$!

target_pid=0
helper_pid=0
target_socket=$KITTY_MATRIX_RUNTIME/target.sock
capture_delay=${KITTY_MATRIX_CAPTURE_DELAY:-0.02}
motion_blur_samples=${KITTY_MATRIX_MOTION_BLUR_SAMPLES:-64}
antialiasing_samples=${KITTY_MATRIX_ANTIALIASING_SAMPLES:-16}
matrix_limit=${KITTY_MATRIX_LIMIT:-48}
case_filter=${KITTY_MATRIX_CASE_FILTER:-}
captured=0

cleanup() {
    if (( target_pid )); then kill $target_pid 2>/dev/null || true; fi
    if (( helper_pid )); then kill $helper_pid 2>/dev/null || true; fi
    kill $kwin_pid 2>/dev/null || true
    rm -rf $KITTY_MATRIX_RUNTIME
}
trap cleanup EXIT INT TERM

while [[ ! -S $XDG_RUNTIME_DIR/kitty-matrix ]]; do
    sleep 0.05
done

xwayland_display=:1
while [[ ! -S /tmp/.X11-unix/X${xwayland_display#:} ]]; do
    sleep 0.05
done

remote() {
    env -u PYTHONHOME -u PYTHONPATH \
        LD_LIBRARY_PATH=$LD_LIBRARY_PATH \
        $kitten_bin @ --to "unix:$1" ${@[2,-1]}
}

wait_for_socket() {
    local socket=$1
    local count=0
    while [[ ! -S $socket ]]; do
        sleep 0.05
        (( ++count ))
        (( count < 200 )) || return 1
    done
}

run_case() {
    local shape=$1
    local aa=$2
    local blur=$3
    local mode=$4
    local focus=$5
    local stem=${shape}-${aa}-${blur}-${mode}-${focus}
    local go_file=$KITTY_MATRIX_RUNTIME/$stem.go
    local screenshot=$output_dir/$stem.png
    local raw_screenshot=$KITTY_MATRIX_RUNTIME/$stem.raw.png

    rm -f $target_socket

    env -u WAYLAND_DISPLAY DISPLAY=$xwayland_display \
    KITTY_MATRIX_GO=$go_file \
    $kitty_bin --config NONE \
        --start-as normal \
        --position=0x0 \
        -o remember_window_size=no \
        -o initial_window_width=387 \
        -o initial_window_height=580 \
        --listen-on "unix:$target_socket" \
        -o allow_remote_control=socket \
        -o cursor_trail=1 \
        -o cursor_shape=$shape \
        -o cursor_shape_unfocused=$shape \
        -o cursor_blink_interval=0 \
        -o cursor_trail_decay='2.0 10.0' \
        -o cursor_trail_start_threshold=1 \
        -o cursor_trail_motion_blur=$blur \
        -o cursor_trail_motion_blur_mode=$mode \
        -o cursor_trail_antialiasing=$aa \
        -o cursor_trail_motion_blur_samples=$motion_blur_samples \
        -o cursor_trail_antialiasing_samples=$antialiasing_samples \
        -o background_opacity=1 \
        -o shell_integration=no-cursor \
        $target_script >$KITTY_MATRIX_RUNTIME/$stem.kitty.log 2>&1 &
    target_pid=$!
    wait_for_socket $target_socket
    sleep 0.25

    env -u WAYLAND_DISPLAY DISPLAY=$xwayland_display \
    $kitty_bin --config NONE \
        --start-as normal \
        --position=387x0 \
        -o remember_window_size=no \
        -o initial_window_width=387 \
        -o initial_window_height=580 \
        -o cursor_trail=0 \
        -T matrix-helper \
        /bin/sh -c 'sleep 30' >$KITTY_MATRIX_RUNTIME/$stem.helper.log 2>&1 &
    helper_pid=$!
    sleep 0.25

    local target_id
    target_id=$(remote $target_socket ls | env -u PYTHONHOME -u PYTHONPATH /usr/bin/python3 -c \
        'import json, sys; print(json.load(sys.stdin)[0]["tabs"][0]["windows"][0]["id"])')

    if [[ $focus == active ]]; then
        remote $target_socket focus-window --match id:$target_id >/dev/null
    fi
    sleep 0.15
    rm -f $go_file
    : > $go_file
    sleep $capture_delay

    remote $target_socket screenshot --match id:$target_id $raw_screenshot
    [[ -s $raw_screenshot ]]
    convert $raw_screenshot -trim -bordercolor '#000000' -border 20 $screenshot
    [[ -s $screenshot ]]

    kill $target_pid 2>/dev/null || true
    target_pid=0
    kill $helper_pid 2>/dev/null || true
    helper_pid=0
    sleep 0.15
}

for shape in block beam underline; do
    for aa in no yes; do
        for blur in no yes; do
            for mode in disconnected connected; do
                for focus in active inactive; do
                    case_stem=${shape}-${aa}-${blur}-${mode}-${focus}
                    [[ -z $case_filter || $case_stem == $case_filter ]] || continue
                    (( captured >= matrix_limit )) && exit 0
                    print "capturing $shape / aa=$aa / blur=$blur / mode=$mode / $focus"
                    run_case $shape $aa $blur $mode $focus
                    (( ++captured ))
                done
            done
        done
    done
done

print "generated $captured screenshots in $output_dir"
