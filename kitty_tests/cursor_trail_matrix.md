# Cursor-trail screenshot matrix

These screenshots were generated with `kitty_tests/generate_cursor_trail_matrix.zsh`
using the release build from this checkout. Each case uses the same large cursor
jump; `active` means the target window is focused and `inactive` means the helper
window is focused. The motion-blur mode is ignored when motion blur is disabled,
but both values are included to make that behavior explicit.

## Disconnected mode

| Focus | Cursor type | none | +AA | +MB | +AA +MB |
|---|---|---|---|---|---|
| active | `block` | ![block-no-no-disconnected-active](cursor_trail_matrix/block-no-no-disconnected-active.png) | ![block-yes-no-disconnected-active](cursor_trail_matrix/block-yes-no-disconnected-active.png) | ![block-no-yes-disconnected-active](cursor_trail_matrix/block-no-yes-disconnected-active.png) | ![block-yes-yes-disconnected-active](cursor_trail_matrix/block-yes-yes-disconnected-active.png) |
| active | `beam` | ![beam-no-no-disconnected-active](cursor_trail_matrix/beam-no-no-disconnected-active.png) | ![beam-yes-no-disconnected-active](cursor_trail_matrix/beam-yes-no-disconnected-active.png) | ![beam-no-yes-disconnected-active](cursor_trail_matrix/beam-no-yes-disconnected-active.png) | ![beam-yes-yes-disconnected-active](cursor_trail_matrix/beam-yes-yes-disconnected-active.png) |
| active | `underline` | ![underline-no-no-disconnected-active](cursor_trail_matrix/underline-no-no-disconnected-active.png) | ![underline-yes-no-disconnected-active](cursor_trail_matrix/underline-yes-no-disconnected-active.png) | ![underline-no-yes-disconnected-active](cursor_trail_matrix/underline-no-yes-disconnected-active.png) | ![underline-yes-yes-disconnected-active](cursor_trail_matrix/underline-yes-yes-disconnected-active.png) |
| inactive | `block` | ![block-no-no-disconnected-inactive](cursor_trail_matrix/block-no-no-disconnected-inactive.png) | ![block-yes-no-disconnected-inactive](cursor_trail_matrix/block-yes-no-disconnected-inactive.png) | ![block-no-yes-disconnected-inactive](cursor_trail_matrix/block-no-yes-disconnected-inactive.png) | ![block-yes-yes-disconnected-inactive](cursor_trail_matrix/block-yes-yes-disconnected-inactive.png) |
| inactive | `beam` | ![beam-no-no-disconnected-inactive](cursor_trail_matrix/beam-no-no-disconnected-inactive.png) | ![beam-yes-no-disconnected-inactive](cursor_trail_matrix/beam-yes-no-disconnected-inactive.png) | ![beam-no-yes-disconnected-inactive](cursor_trail_matrix/beam-no-yes-disconnected-inactive.png) | ![beam-yes-yes-disconnected-inactive](cursor_trail_matrix/beam-yes-yes-disconnected-inactive.png) |
| inactive | `underline` | ![underline-no-no-disconnected-inactive](cursor_trail_matrix/underline-no-no-disconnected-inactive.png) | ![underline-yes-no-disconnected-inactive](cursor_trail_matrix/underline-yes-no-disconnected-inactive.png) | ![underline-no-yes-disconnected-inactive](cursor_trail_matrix/underline-no-yes-disconnected-inactive.png) | ![underline-yes-yes-disconnected-inactive](cursor_trail_matrix/underline-yes-yes-disconnected-inactive.png) |

## Connected mode

| Focus | Cursor type | none | +AA | +MB | +AA +MB |
|---|---|---|---|---|---|
| active | `block` | ![block-no-no-connected-active](cursor_trail_matrix/block-no-no-connected-active.png) | ![block-yes-no-connected-active](cursor_trail_matrix/block-yes-no-connected-active.png) | ![block-no-yes-connected-active](cursor_trail_matrix/block-no-yes-connected-active.png) | ![block-yes-yes-connected-active](cursor_trail_matrix/block-yes-yes-connected-active.png) |
| active | `beam` | ![beam-no-no-connected-active](cursor_trail_matrix/beam-no-no-connected-active.png) | ![beam-yes-no-connected-active](cursor_trail_matrix/beam-yes-no-connected-active.png) | ![beam-no-yes-connected-active](cursor_trail_matrix/beam-no-yes-connected-active.png) | ![beam-yes-yes-connected-active](cursor_trail_matrix/beam-yes-yes-connected-active.png) |
| active | `underline` | ![underline-no-no-connected-active](cursor_trail_matrix/underline-no-no-connected-active.png) | ![underline-yes-no-connected-active](cursor_trail_matrix/underline-yes-no-connected-active.png) | ![underline-no-yes-connected-active](cursor_trail_matrix/underline-no-yes-connected-active.png) | ![underline-yes-yes-connected-active](cursor_trail_matrix/underline-yes-yes-connected-active.png) |
| inactive | `block` | ![block-no-no-connected-inactive](cursor_trail_matrix/block-no-no-connected-inactive.png) | ![block-yes-no-connected-inactive](cursor_trail_matrix/block-yes-no-connected-inactive.png) | ![block-no-yes-connected-inactive](cursor_trail_matrix/block-no-yes-connected-inactive.png) | ![block-yes-yes-connected-inactive](cursor_trail_matrix/block-yes-yes-connected-inactive.png) |
| inactive | `beam` | ![beam-no-no-connected-inactive](cursor_trail_matrix/beam-no-no-connected-inactive.png) | ![beam-yes-no-connected-inactive](cursor_trail_matrix/beam-yes-no-connected-inactive.png) | ![beam-no-yes-connected-inactive](cursor_trail_matrix/beam-no-yes-connected-inactive.png) | ![beam-yes-yes-connected-inactive](cursor_trail_matrix/beam-yes-yes-connected-inactive.png) |
| inactive | `underline` | ![underline-no-no-connected-inactive](cursor_trail_matrix/underline-no-no-connected-inactive.png) | ![underline-yes-no-connected-inactive](cursor_trail_matrix/underline-yes-no-connected-inactive.png) | ![underline-no-yes-connected-inactive](cursor_trail_matrix/underline-no-yes-connected-inactive.png) | ![underline-yes-yes-connected-inactive](cursor_trail_matrix/underline-yes-yes-connected-inactive.png) |
