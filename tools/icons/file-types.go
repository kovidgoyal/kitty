package icons

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

var _ = fmt.Print

// file types {{
const (
	AUDIO           rune = 0xf001  // 
	BINARY          rune = 0xeae8  // 
	BOOK            rune = 0xe28b  // 
	CACHE           rune = 0xf49b  // 
	CAD             rune = 0xf0eeb // 󰻫
	CALENDAR        rune = 0xeab0  // 
	CLOCK           rune = 0xf43a  // 
	COMPRESSED      rune = 0xf410  // 
	CONFIG          rune = 0xe615  // 
	CSS3            rune = 0xe749  // 
	DATABASE        rune = 0xf1c0  // 
	DIFF            rune = 0xf440  // 
	DISK_IMAGE      rune = 0xe271  // 
	DOCKER          rune = 0xe650  // 
	DOCUMENT        rune = 0xf1c2  // 
	DOWNLOAD        rune = 0xf01da // 󰇚
	EDA_PCB         rune = 0xeabe  // 
	EDA_SCH         rune = 0xf0b45 // 󰭅
	EMACS           rune = 0xe632  // 
	ESLINT          rune = 0xe655  // 
	FILE            rune = 0xf15b  // 
	FILE_3D         rune = 0xf01a7 // 󰆧
	FILE_OUTLINE    rune = 0xf016  // 
	FOLDER          rune = 0xe5ff  // 
	FOLDER_CONFIG   rune = 0xe5fc  // 
	FOLDER_EXERCISM rune = 0xebe5  // 
	FOLDER_GIT      rune = 0xe5fb  // 
	FOLDER_GITHUB   rune = 0xe5fd  // 
	FOLDER_HIDDEN   rune = 0xf179e // 󱞞
	FOLDER_KEY      rune = 0xf08ac // 󰢬
	FOLDER_NPM      rune = 0xe5fa  // 
	FOLDER_OCAML    rune = 0xe67a  // 
	FOLDER_OPEN     rune = 0xf115  // 
	FONT            rune = 0xf031  // 
	FREECAD         rune = 0xf336  // 
	GIMP            rune = 0xf338  // 
	GIST_SECRET     rune = 0xeafa  // 
	GIT             rune = 0xf1d3  // 
	GODOT           rune = 0xe65f  // 
	GRADLE          rune = 0xe660  // 
	GRAPH           rune = 0xf1049 // 󱁉
	GRAPHQL         rune = 0xe662  // 
	GRUNT           rune = 0xe611  // 
	GTK             rune = 0xf362  // 
	GULP            rune = 0xe610  // 
	HTML5           rune = 0xf13b  // 
	IMAGE           rune = 0xf1c5  // 
	INFO            rune = 0xf129  // 
	INTELLIJ        rune = 0xe7b5  // 
	JSON            rune = 0xe60b  // 
	KDENLIVE        rune = 0xf33c  // 
	KEY             rune = 0xeb11  // 
	KEYPASS         rune = 0xf23e  // 
	KICAD           rune = 0xf34c  // 
	KRITA           rune = 0xf33d  // 
	LANG_ARDUINO    rune = 0xf34b  // 
	LANG_ASSEMBLY   rune = 0xe637  // 
	LANG_C          rune = 0xe61e  // 
	LANG_CPP        rune = 0xe61d  // 
	LANG_CSHARP     rune = 0xf031b // 󰌛
	LANG_D          rune = 0xe7af  // 
	LANG_ELIXIR     rune = 0xe62d  // 
	LANG_FENNEL     rune = 0xe6af  // 
	LANG_FORTRAN    rune = 0xf121a // 󱈚
	LANG_FSHARP     rune = 0xe7a7  // 
	LANG_GLEAM      rune = 0xf09a5 // 󰦥
	LANG_GO         rune = 0xe65e  // 
	LANG_GROOVY     rune = 0xe775  // 
	LANG_HASKELL    rune = 0xe777  // 
	LANG_HDL        rune = 0xf035b // 󰍛
	LANG_HOLYC      rune = 0xf00a2 // 󰂢
	LANG_JAVA       rune = 0xe256  // 
	LANG_JAVASCRIPT rune = 0xe74e  // 
	LANG_KOTLIN     rune = 0xe634  // 
	LANG_LUA        rune = 0xe620  // 
	LANG_NIM        rune = 0xe677  // 
	LANG_OCAML      rune = 0xe67a  // 
	LANG_PERL       rune = 0xe67e  // 
	LANG_PHP        rune = 0xe73d  // 
	LANG_PYTHON     rune = 0xe606  // 
	LANG_R          rune = 0xe68a  // 
	LANG_RUBY       rune = 0xe739  // 
	LANG_RUBYRAILS  rune = 0xe73b  // 
	LANG_RUST       rune = 0xe68b  // 
	LANG_SASS       rune = 0xe603  // 
	LANG_SCHEME     rune = 0xe6b1  // 
	LANG_STYLUS     rune = 0xe600  // 
	LANG_TEX        rune = 0xe69b  // 
	LANG_TYPESCRIPT rune = 0xe628  // 
	LANG_V          rune = 0xe6ac  // 
	LIBRARY         rune = 0xeb9c  // 
	LICENSE         rune = 0xf02d  // 
	LOCK            rune = 0xf023  // 
	LOG             rune = 0xf18d  // 
	MAKE            rune = 0xe673  // 
	MARKDOWN        rune = 0xf48a  // 
	MUSTACHE        rune = 0xe60f  // 
	NAMED_PIPE      rune = 0xf07e5 // 󰟥
	NODEJS          rune = 0xe718  // 
	NOTEBOOK        rune = 0xe678  // 
	NPM             rune = 0xe71e  // 
	OS_ANDROID      rune = 0xe70e  // 
	OS_APPLE        rune = 0xf179  // 
	OS_LINUX        rune = 0xf17c  // 
	OS_WINDOWS      rune = 0xf17a  // 
	OS_WINDOWS_CMD  rune = 0xebc4  // 
	PLAYLIST        rune = 0xf0cb9 // 󰲹
	POWERSHELL      rune = 0xebc7  // 
	PRIVATE_KEY     rune = 0xf0306 // 󰌆
	PUBLIC_KEY      rune = 0xf0dd6 // 󰷖
	QT              rune = 0xf375  // 
	RAZOR           rune = 0xf1fa  // 
	REACT           rune = 0xe7ba  // 
	README          rune = 0xf00ba // 󰂺
	SHEET           rune = 0xf1c3  // 
	SHELL           rune = 0xf1183 // 󱆃
	SHELL_CMD       rune = 0xf489  // 
	SHIELD_CHECK    rune = 0xf0565 // 󰕥
	SHIELD_KEY      rune = 0xf0bc4 // 󰯄
	SHIELD_LOCK     rune = 0xf099d // 󰦝
	SIGNED_FILE     rune = 0xf19c3 // 󱧃
	SLIDE           rune = 0xf1c4  // 
	SOCKET          rune = 0xf0427 // 󰐧
	SQLITE          rune = 0xe7c4  // 
	SUBLIME         rune = 0xe7aa  // 
	SUBTITLE        rune = 0xf0a16 // 󰨖
	SYMLINK         rune = 0xf481  // 
	SYMLINK_TO_DIR  rune = 0xf482  // 
	TERRAFORM       rune = 0xf1062 // 󱁢
	TEXT            rune = 0xf15c  // 
	TMUX            rune = 0xebc8  // 
	TOML            rune = 0xe6b2  // 
	TRANSLATION     rune = 0xf05ca // 󰗊
	TYPST           rune = 0xf37f  // 
	UNITY           rune = 0xe721  // 
	VECTOR          rune = 0xf0559 // 󰕙
	VIDEO           rune = 0xf03d  // 
	VIM             rune = 0xe7c5  // 
	WRENCH          rune = 0xf0ad  // 
	XML             rune = 0xf05c0 // 󰗀
	YAML            rune = 0xe6a8  // 
	YARN            rune = 0xe6a7  // 
) // }}}

var DirectoryNameMap = sync.OnceValue(func() map[string]rune { // {{{
	return map[string]rune{
		".config":       FOLDER_CONFIG,   // 
		".exercism":     FOLDER_EXERCISM, // 
		".git":          FOLDER_GIT,      // 
		".github":       FOLDER_GITHUB,   // 
		".npm":          FOLDER_NPM,      // 
		".opam":         FOLDER_OCAML,    // 
		".ssh":          FOLDER_KEY,      // 󰢬
		".Trash":        0xf1f8,          // 
		"cabal":         LANG_HASKELL,    // 
		"config":        FOLDER_CONFIG,   // 
		"Contacts":      0xf024c,         // 󰉌
		"cron.d":        FOLDER_CONFIG,   // 
		"cron.daily":    FOLDER_CONFIG,   // 
		"cron.hourly":   FOLDER_CONFIG,   // 
		"cron.minutely": FOLDER_CONFIG,   // 
		"cron.monthly":  FOLDER_CONFIG,   // 
		"cron.weekly":   FOLDER_CONFIG,   // 
		"Desktop":       0xf108,          // 
		"Downloads":     0xf024d,         // 󰉍
		"etc":           FOLDER_CONFIG,   // 
		"Favorites":     0xf069d,         // 󰚝
		"hidden":        FOLDER_HIDDEN,   // 󱞞
		"home":          0xf10b5,         // 󱂵
		"~":             0xf10b5,         // 󱂵
		"include":       FOLDER_CONFIG,   // 
		"Mail":          0xf01f0,         // 󰇰
		"Movies":        0xf0fce,         // 󰿎
		"Music":         0xf1359,         // 󱍙
		"node_modules":  FOLDER_NPM,      // 
		"npm_cache":     FOLDER_NPM,      // 
		"pam.d":         FOLDER_KEY,      // 󰢬
		"Pictures":      0xf024f,         // 󰉏
		"ssh":           FOLDER_KEY,      // 󰢬
		"sudoers.d":     FOLDER_KEY,      // 󰢬
		"Videos":        0xf03d,          // 
		"xbps.d":        FOLDER_CONFIG,   // 
		"xorg.conf.d":   FOLDER_CONFIG,   // 
	}
}) // }}}

var FileNameMap = sync.OnceValue(func() map[string]rune { // {{{
	return map[string]rune{

		"._DS_Store":                 OS_APPLE,        // 
		".aliases":                   SHELL,           // 󱆃
		".atom":                      0xe764,          // 
		".bash_aliases":              SHELL,           // 󱆃
		".bash_history":              SHELL,           // 󱆃
		".bash_logout":               SHELL,           // 󱆃
		".bash_profile":              SHELL,           // 󱆃
		".bashrc":                    SHELL,           // 󱆃
		".CFUserTextEncoding":        OS_APPLE,        // 
		".clang-format":              CONFIG,          // 
		".clang-tidy":                CONFIG,          // 
		".codespellrc":               0xf04c6,         // 󰓆
		".condarc":                   0xe715,          // 
		".cshrc":                     SHELL,           // 󱆃
		".DS_Store":                  OS_APPLE,        // 
		".editorconfig":              0xe652,          // 
		".emacs":                     EMACS,           // 
		".envrc":                     0xf462,          // 
		".eslintignore":              ESLINT,          // 
		".eslintrc.cjs":              ESLINT,          // 
		".eslintrc.js":               ESLINT,          // 
		".eslintrc.json":             ESLINT,          // 
		".eslintrc.yaml":             ESLINT,          // 
		".eslintrc.yml":              ESLINT,          // 
		".fennelrc":                  LANG_FENNEL,     // 
		".gcloudignore":              0xf11f6,         // 󱇶
		".git-blame-ignore-revs":     GIT,             // 
		".gitattributes":             GIT,             // 
		".gitconfig":                 GIT,             // 
		".gitignore":                 GIT,             // 
		".gitignore_global":          GIT,             // 
		".gitlab-ci.yml":             0xf296,          // 
		".gitmodules":                GIT,             // 
		".gtkrc-2.0":                 GTK,             // 
		".gvimrc":                    VIM,             // 
		".htaccess":                  CONFIG,          // 
		".htpasswd":                  CONFIG,          // 
		".idea":                      INTELLIJ,        // 
		".ideavimrc":                 VIM,             // 
		".inputrc":                   CONFIG,          // 
		".kshrc":                     SHELL,           // 󱆃
		".login":                     SHELL,           // 󱆃
		".logout":                    SHELL,           // 󱆃
		".luacheckrc":                CONFIG,          // 
		".luaurc":                    CONFIG,          // 
		".mailmap":                   GIT,             // 
		".nanorc":                    0xe838,          // 
		".node_repl_history":         NODEJS,          // 
		".npmignore":                 NPM,             // 
		".npmrc":                     NPM,             // 
		".nuxtrc":                    0xf1106,         // 󱄆
		".ocamlinit":                 LANG_OCAML,      // 
		".parentlock":                LOCK,            // 
		".pre-commit-config.yaml":    0xf06e2,         // 󰛢
		".prettierignore":            0xe6b4,          // 
		".prettierrc":                0xe6b4,          // 
		".profile":                   SHELL,           // 󱆃
		".pylintrc":                  CONFIG,          // 
		".python_history":            LANG_PYTHON,     // 
		".rustfmt.toml":              LANG_RUST,       // 
		".rvm":                       LANG_RUBY,       // 
		".rvmrc":                     LANG_RUBY,       // 
		".SRCINFO":                   0xf303,          // 
		".stowrc":                    0xeef1,          // 
		".tcshrc":                    SHELL,           // 󱆃
		".viminfo":                   VIM,             // 
		".vimrc":                     VIM,             // 
		".Xauthority":                CONFIG,          // 
		".xinitrc":                   CONFIG,          // 
		".Xresources":                CONFIG,          // 
		".yarnrc":                    YARN,            // 
		".zlogin":                    SHELL,           // 󱆃
		".zlogout":                   SHELL,           // 󱆃
		".zprofile":                  SHELL,           // 󱆃
		".zsh_history":               SHELL,           // 󱆃
		".zsh_sessions":              SHELL,           // 󱆃
		".zshenv":                    SHELL,           // 󱆃
		".zshrc":                     SHELL,           // 󱆃
		"_gvimrc":                    VIM,             // 
		"_vimrc":                     VIM,             // 
		"a.out":                      SHELL_CMD,       // 
		"authorized_keys":            0xf08c0,         // 󰣀
		"AUTHORS":                    0xedca,          // 
		"AUTHORS.txt":                0xedca,          // 
		"bashrc":                     SHELL,           // 󱆃
		"Brewfile":                   0xf1116,         // 󱄖
		"Brewfile.lock.json":         0xf1116,         // 󱄖
		"bspwmrc":                    0xf355,          // 
		"build.gradle.kts":           GRADLE,          // 
		"build.zig.zon":              0xe6a9,          // 
		"bun.lockb":                  0xe76f,          // 
		"cantorrc":                   0xf373,          // 
		"Cargo.lock":                 LANG_RUST,       // 
		"Cargo.toml":                 LANG_RUST,       // 
		"CMakeLists.txt":             0xe794,          // 
		"CODE_OF_CONDUCT":            0xf4ae,          // 
		"CODE_OF_CONDUCT.md":         0xf4ae,          // 
		"COMMIT_EDITMSG":             GIT,             // 
		"compose.yaml":               DOCKER,          // 
		"compose.yml":                DOCKER,          // 
		"composer.json":              LANG_PHP,        // 
		"composer.lock":              LANG_PHP,        // 
		"config":                     CONFIG,          // 
		"config.ru":                  LANG_RUBY,       // 
		"config.status":              CONFIG,          // 
		"configure":                  WRENCH,          // 
		"configure.ac":               CONFIG,          // 
		"configure.in":               CONFIG,          // 
		"constraints.txt":            LANG_PYTHON,     // 
		"COPYING":                    LICENSE,         // 
		"COPYRIGHT":                  LICENSE,         // 
		"crontab":                    CONFIG,          // 
		"crypttab":                   CONFIG,          // 
		"csh.cshrc":                  SHELL,           // 󱆃
		"csh.login":                  SHELL,           // 󱆃
		"csh.logout":                 SHELL,           // 󱆃
		"docker-compose.yaml":        DOCKER,          // 
		"docker-compose.yml":         DOCKER,          // 
		"Dockerfile":                 DOCKER,          // 
		"dune":                       LANG_OCAML,      // 
		"dune-project":               WRENCH,          // 
		"Earthfile":                  0xf0ac,          // 
		"environment":                CONFIG,          // 
		"favicon.ico":                0xe623,          // 
		"fennelrc":                   LANG_FENNEL,     // 
		"flake.lock":                 0xf313,          // 
		"fonts.conf":                 FONT,            // 
		"fp-info-cache":              KICAD,           // 
		"fp-lib-table":               KICAD,           // 
		"FreeCAD.conf":               FREECAD,         // 
		"Gemfile":                    LANG_RUBY,       // 
		"Gemfile.lock":               LANG_RUBY,       // 
		"GNUmakefile":                MAKE,            // 
		"go.mod":                     LANG_GO,         // 
		"go.sum":                     LANG_GO,         // 
		"go.work":                    LANG_GO,         // 
		"gradle":                     GRADLE,          // 
		"gradle.properties":          GRADLE,          // 
		"gradlew":                    GRADLE,          // 
		"gradlew.bat":                GRADLE,          // 
		"group":                      LOCK,            // 
		"gruntfile.coffee":           GRUNT,           // 
		"gruntfile.js":               GRUNT,           // 
		"gruntfile.ls":               GRUNT,           // 
		"gshadow":                    LOCK,            // 
		"gtkrc":                      GTK,             // 
		"gulpfile.coffee":            GULP,            // 
		"gulpfile.js":                GULP,            // 
		"gulpfile.ls":                GULP,            // 
		"heroku.yml":                 0xe77b,          // 
		"hostname":                   CONFIG,          // 
		"hypridle.conf":              0xf359,          // 
		"hyprland.conf":              0xf359,          // 
		"hyprlock.conf":              0xf359,          // 
		"hyprpaper.conf":             0xf359,          // 
		"i3blocks.conf":              0xf35a,          // 
		"i3status.conf":              0xf35a,          // 
		"id_dsa":                     PRIVATE_KEY,     // 󰌆
		"id_ecdsa":                   PRIVATE_KEY,     // 󰌆
		"id_ecdsa_sk":                PRIVATE_KEY,     // 󰌆
		"id_ed25519":                 PRIVATE_KEY,     // 󰌆
		"id_ed25519_sk":              PRIVATE_KEY,     // 󰌆
		"id_rsa":                     PRIVATE_KEY,     // 󰌆
		"index.theme":                0xee72,          // 
		"inputrc":                    CONFIG,          // 
		"Jenkinsfile":                0xe66e,          // 
		"jsconfig.json":              LANG_JAVASCRIPT, // 
		"Justfile":                   WRENCH,          // 
		"justfile":                   WRENCH,          // 
		"kalgebrarc":                 0xf373,          // 
		"kdeglobals":                 0xf373,          // 
		"kdenlive-layoutsrc":         KDENLIVE,        // 
		"kdenliverc":                 KDENLIVE,        // 
		"kitty.conf":                 '🐱',
		"known_hosts":                0xf08c0,         // 󰣀
		"kritadisplayrc":             KRITA,           // 
		"kritarc":                    KRITA,           // 
		"LICENCE":                    LICENSE,         // 
		"LICENCE.md":                 LICENSE,         // 
		"LICENCE.txt":                LICENSE,         // 
		"LICENSE":                    LICENSE,         // 
		"LICENSE-APACHE":             LICENSE,         // 
		"LICENSE-MIT":                LICENSE,         // 
		"LICENSE.md":                 LICENSE,         // 
		"LICENSE.txt":                LICENSE,         // 
		"localized":                  OS_APPLE,        // 
		"localtime":                  CLOCK,           // 
		"lock":                       LOCK,            // 
		"LOCK":                       LOCK,            // 
		"log":                        LOG,             // 
		"LOG":                        LOG,             // 
		"lxde-rc.xml":                0xf363,          // 
		"lxqt.conf":                  0xf364,          // 
		"Makefile":                   MAKE,            // 
		"makefile":                   MAKE,            // 
		"Makefile.ac":                MAKE,            // 
		"Makefile.am":                MAKE,            // 
		"Makefile.in":                MAKE,            // 
		"MANIFEST":                   LANG_PYTHON,     // 
		"MANIFEST.in":                LANG_PYTHON,     // 
		"mix.lock":                   LANG_ELIXIR,     // 
		"mpv.conf":                   0xf36e,          // 
		"npm-shrinkwrap.json":        NPM,             // 
		"npmrc":                      NPM,             // 
		"package-lock.json":          NPM,             // 
		"package.json":               NPM,             // 
		"passwd":                     LOCK,            // 
		"php.ini":                    LANG_PHP,        // 
		"PKGBUILD":                   0xf303,          // 
		"platformio.ini":             0xe682,          // 
		"pom.xml":                    0xe674,          // 
		"Procfile":                   0xe77b,          // 
		"profile":                    SHELL,           // 󱆃
		"PrusaSlicer.ini":            0xf351,          // 
		"PrusaSlicerGcodeViewer.ini": 0xf351,          // 
		"pyproject.toml":             LANG_PYTHON,     // 
		"pyvenv.cfg":                 LANG_PYTHON,     // 
		"qt5ct.conf":                 QT,              // 
		"qt6ct.conf":                 QT,              // 
		"QtProject.conf":             QT,              // 
		"Rakefile":                   LANG_RUBY,       // 
		"README":                     README,          // 󰂺
		"README.md":                  README,          // 󰂺
		"release.toml":               LANG_RUST,       // 
		"renovate.json":              0xf027c,         // 󰉼
		"requirements.txt":           LANG_PYTHON,     // 
		"robots.txt":                 0xf06a9,         // 󰚩
		"rubydoc":                    LANG_RUBYRAILS,  // 
		"rvmrc":                      LANG_RUBY,       // 
		"SECURITY":                   0xf0483,         // 󰒃
		"SECURITY.md":                0xf0483,         // 󰒃
		"settings.gradle.kts":        GRADLE,          // 
		"shadow":                     LOCK,            // 
		"shells":                     CONFIG,          // 
		"sudoers":                    LOCK,            // 
		"sxhkdrc":                    CONFIG,          // 
		"sym-lib-table":              KICAD,           // 
		"timezone":                   CLOCK,           // 
		"tmux.conf":                  TMUX,            // 
		"tmux.conf.local":            TMUX,            // 
		"tsconfig.json":              LANG_TYPESCRIPT, // 
		"Vagrantfile":                0x2371,          // ⍱
		"vlcrc":                      0xf057c,         // 󰕼
		"webpack.config.js":          0xf072b,         // 󰜫
		"weston.ini":                 0xf367,          // 
		"xmobarrc":                   0xf35e,          // 
		"xmobarrc.hs":                0xf35e,          // 
		"xmonad.hs":                  0xf35e,          // 
		"yarn.lock":                  YARN,            // 
		"zlogin":                     SHELL,           // 󱆃
		"zlogout":                    SHELL,           // 󱆃
		"zprofile":                   SHELL,           // 󱆃
		"zshenv":                     SHELL,           // 󱆃
		"zshrc":                      SHELL,           // 󱆃
	}
}) // }}}

var ExtensionMap = sync.OnceValue(func() map[string]rune { // {{{
	return map[string]rune{
		"123dx":            CAD,             // 󰻫
		"3dm":              CAD,             // 󰻫
		"3g2":              VIDEO,           // 
		"3gp":              VIDEO,           // 
		"3gp2":             VIDEO,           // 
		"3gpp":             VIDEO,           // 
		"3gpp2":            VIDEO,           // 
		"3mf":              FILE_3D,         // 󰆧
		"7z":               COMPRESSED,      // 
		"a":                OS_LINUX,        // 
		"aac":              AUDIO,           // 
		"acf":              0xf1b6,          // 
		"age":              SHIELD_LOCK,     // 󰦝
		"ai":               0xe7b4,          // 
		"aif":              AUDIO,           // 
		"aifc":             AUDIO,           // 
		"aiff":             AUDIO,           // 
		"alac":             AUDIO,           // 
		"android":          OS_ANDROID,      // 
		"ape":              AUDIO,           // 
		"apk":              OS_ANDROID,      // 
		"app":              BINARY,          // 
		"apple":            OS_APPLE,        // 
		"applescript":      OS_APPLE,        // 
		"ar":               COMPRESSED,      // 
		"arj":              COMPRESSED,      // 
		"arw":              IMAGE,           // 
		"asc":              SHIELD_LOCK,     // 󰦝
		"asm":              LANG_ASSEMBLY,   // 
		"asp":              0xf121,          // 
		"ass":              SUBTITLE,        // 󰨖
		"avi":              VIDEO,           // 
		"avif":             IMAGE,           // 
		"avro":             JSON,            // 
		"awk":              SHELL_CMD,       // 
		"bash":             SHELL_CMD,       // 
		"bat":              OS_WINDOWS_CMD,  // 
		"bats":             SHELL_CMD,       // 
		"bdf":              FONT,            // 
		"bib":              LANG_TEX,        // 
		"bin":              BINARY,          // 
		"blend":            0xf00ab,         // 󰂫
		"bmp":              IMAGE,           // 
		"br":               COMPRESSED,      // 
		"brd":              EDA_PCB,         // 
		"brep":             CAD,             // 󰻫
		"bst":              LANG_TEX,        // 
		"bundle":           OS_APPLE,        // 
		"bz":               COMPRESSED,      // 
		"bz2":              COMPRESSED,      // 
		"bz3":              COMPRESSED,      // 
		"c":                LANG_C,          // 
		"c++":              LANG_CPP,        // 
		"cab":              OS_WINDOWS,      // 
		"cache":            CACHE,           // 
		"cast":             VIDEO,           // 
		"catpart":          CAD,             // 󰻫
		"catproduct":       CAD,             // 󰻫
		"cbr":              IMAGE,           // 
		"cbz":              IMAGE,           // 
		"cc":               LANG_CPP,        // 
		"cert":             GIST_SECRET,     // 
		"cfg":              CONFIG,          // 
		"cjs":              LANG_JAVASCRIPT, // 
		"class":            LANG_JAVA,       // 
		"clj":              0xe768,          // 
		"cljc":             0xe768,          // 
		"cljs":             0xe76a,          // 
		"cls":              LANG_TEX,        // 
		"cmake":            0xe794,          // 
		"cmd":              OS_WINDOWS,      // 
		"coffee":           0xf0f4,          // 
		"com":              0xe629,          // 
		"conda":            0xe715,          // 
		"conf":             CONFIG,          // 
		"config":           CONFIG,          // 
		"cow":              0xf019a,         // 󰆚
		"cp":               LANG_CPP,        // 
		"cpio":             COMPRESSED,      // 
		"cpp":              LANG_CPP,        // 
		"cr":               0xe62f,          // 
		"cr2":              IMAGE,           // 
		"crdownload":       DOWNLOAD,        // 󰇚
		"crt":              GIST_SECRET,     // 
		"cs":               LANG_CSHARP,     // 󰌛
		"csh":              SHELL_CMD,       // 
		"cshtml":           RAZOR,           // 
		"csproj":           LANG_CSHARP,     // 󰌛
		"css":              CSS3,            // 
		"csv":              SHEET,           // 
		"csx":              LANG_CSHARP,     // 󰌛
		"cts":              LANG_TYPESCRIPT, // 
		"cu":               0xe64b,          // 
		"cue":              PLAYLIST,        // 󰲹
		"cxx":              LANG_CPP,        // 
		"d":                LANG_D,          // 
		"dart":             0xe798,          // 
		"db":               DATABASE,        // 
		"db3":              SQLITE,          // 
		"dconf":            DATABASE,        // 
		"deb":              0xe77d,          // 
		"desktop":          0xebd1,          // 
		"di":               LANG_D,          // 
		"diff":             DIFF,            // 
		"djv":              DOCUMENT,        // 
		"djvu":             DOCUMENT,        // 
		"dll":              LIBRARY,         // 
		"dmg":              DISK_IMAGE,      // 
		"doc":              DOCUMENT,        // 
		"dockerfile":       DOCKER,          // 
		"dockerignore":     DOCKER,          // 
		"docm":             DOCUMENT,        // 
		"docx":             DOCUMENT,        // 
		"dot":              GRAPH,           // 󱁉
		"download":         DOWNLOAD,        // 󰇚
		"drawio":           0xebba,          // 
		"dump":             DATABASE,        // 
		"dvi":              IMAGE,           // 
		"dwg":              CAD,             // 󰻫
		"dxf":              CAD,             // 󰻫
		"dylib":            OS_APPLE,        // 
		"ebook":            BOOK,            // 
		"ebuild":           0xf30d,          // 
		"editorconfig":     0xe652,          // 
		"edn":              0xe76a,          // 
		"eex":              LANG_ELIXIR,     // 
		"ejs":              0xe618,          // 
		"el":               EMACS,           // 
		"elc":              EMACS,           // 
		"elf":              BINARY,          // 
		"elm":              0xe62c,          // 
		"eml":              0xf003,          // 
		"env":              0xf462,          // 
		"eot":              FONT,            // 
		"eps":              VECTOR,          // 󰕙
		"epub":             BOOK,            // 
		"erb":              LANG_RUBYRAILS,  // 
		"erl":              0xe7b1,          // 
		"ex":               LANG_ELIXIR,     // 
		"exe":              OS_WINDOWS_CMD,  // 
		"exs":              LANG_ELIXIR,     // 
		"f":                LANG_FORTRAN,    // 󱈚
		"f#":               LANG_FSHARP,     // 
		"f3d":              CAD,             // 󰻫
		"f3z":              CAD,             // 󰻫
		"f90":              LANG_FORTRAN,    // 󱈚
		"fbx":              FILE_3D,         // 󰆧
		"fcbak":            FREECAD,         // 
		"fcmacro":          FREECAD,         // 
		"fcmat":            FREECAD,         // 
		"fcparam":          FREECAD,         // 
		"fcscript":         FREECAD,         // 
		"fcstd":            FREECAD,         // 
		"fcstd1":           FREECAD,         // 
		"fctb":             FREECAD,         // 
		"fctl":             FREECAD,         // 
		"fdmdownload":      DOWNLOAD,        // 󰇚
		"fish":             SHELL_CMD,       // 
		"flac":             AUDIO,           // 
		"flc":              FONT,            // 
		"flf":              FONT,            // 
		"flv":              VIDEO,           // 
		"fnl":              LANG_FENNEL,     // 
		"fnt":              FONT,            // 
		"fodg":             0xf379,          // 
		"fodp":             0xf37a,          // 
		"fods":             0xf378,          // 
		"fodt":             0xf37c,          // 
		"fon":              FONT,            // 
		"font":             FONT,            // 
		"for":              LANG_FORTRAN,    // 󱈚
		"fs":               LANG_FSHARP,     // 
		"fsi":              LANG_FSHARP,     // 
		"fsproj":           LANG_FSHARP,     // 
		"fsscript":         LANG_FSHARP,     // 
		"fsx":              LANG_FSHARP,     // 
		"gba":              0xf1393,         // 󱎓
		"gbl":              EDA_PCB,         // 
		"gbo":              EDA_PCB,         // 
		"gbp":              EDA_PCB,         // 
		"gbr":              EDA_PCB,         // 
		"gbs":              EDA_PCB,         // 
		"gcode":            0xf0af4,         // 󰫴
		"gd":               GODOT,           // 
		"gdoc":             DOCUMENT,        // 
		"gem":              LANG_RUBY,       // 
		"gemfile":          LANG_RUBY,       // 
		"gemspec":          LANG_RUBY,       // 
		"gform":            0xf298,          // 
		"gif":              IMAGE,           // 
		"git":              GIT,             // 
		"gleam":            LANG_GLEAM,      // 󰦥
		"gm1":              EDA_PCB,         // 
		"gml":              EDA_PCB,         // 
		"go":               LANG_GO,         // 
		"godot":            GODOT,           // 
		"gpg":              SHIELD_LOCK,     // 󰦝
		"gql":              GRAPHQL,         // 
		"gradle":           GRADLE,          // 
		"graphql":          GRAPHQL,         // 
		"gresource":        GTK,             // 
		"groovy":           LANG_GROOVY,     // 
		"gsheet":           SHEET,           // 
		"gslides":          SLIDE,           // 
		"gtl":              EDA_PCB,         // 
		"gto":              EDA_PCB,         // 
		"gtp":              EDA_PCB,         // 
		"gts":              EDA_PCB,         // 
		"guardfile":        LANG_RUBY,       // 
		"gv":               GRAPH,           // 󱁉
		"gvy":              LANG_GROOVY,     // 
		"gz":               COMPRESSED,      // 
		"h":                LANG_C,          // 
		"h++":              LANG_CPP,        // 
		"h264":             VIDEO,           // 
		"haml":             0xe664,          // 
		"hbs":              MUSTACHE,        // 
		"hc":               LANG_HOLYC,      // 󰂢
		"heic":             IMAGE,           // 
		"heics":            VIDEO,           // 
		"heif":             IMAGE,           // 
		"hex":              0xf12a7,         // 󱊧
		"hh":               LANG_CPP,        // 
		"hi":               BINARY,          // 
		"hpp":              LANG_CPP,        // 
		"hrl":              0xe7b1,          // 
		"hs":               LANG_HASKELL,    // 
		"htm":              HTML5,           // 
		"html":             HTML5,           // 
		"hxx":              LANG_CPP,        // 
		"iam":              CAD,             // 󰻫
		"ical":             CALENDAR,        // 
		"icalendar":        CALENDAR,        // 
		"ico":              IMAGE,           // 
		"ics":              CALENDAR,        // 
		"ifb":              CALENDAR,        // 
		"ifc":              CAD,             // 󰻫
		"ige":              CAD,             // 󰻫
		"iges":             CAD,             // 󰻫
		"igs":              CAD,             // 󰻫
		"image":            DISK_IMAGE,      // 
		"img":              DISK_IMAGE,      // 
		"iml":              INTELLIJ,        // 
		"info":             INFO,            // 
		"ini":              CONFIG,          // 
		"inl":              LANG_C,          // 
		"ino":              LANG_ARDUINO,    // 
		"ipt":              CAD,             // 󰻫
		"ipynb":            NOTEBOOK,        // 
		"iso":              DISK_IMAGE,      // 
		"j2c":              IMAGE,           // 
		"j2k":              IMAGE,           // 
		"jad":              LANG_JAVA,       // 
		"jar":              LANG_JAVA,       // 
		"java":             LANG_JAVA,       // 
		"jfi":              IMAGE,           // 
		"jfif":             IMAGE,           // 
		"jif":              IMAGE,           // 
		"jl":               0xe624,          // 
		"jmd":              MARKDOWN,        // 
		"jp2":              IMAGE,           // 
		"jpe":              IMAGE,           // 
		"jpeg":             IMAGE,           // 
		"jpf":              IMAGE,           // 
		"jpg":              IMAGE,           // 
		"jpx":              IMAGE,           // 
		"js":               LANG_JAVASCRIPT, // 
		"json":             JSON,            // 
		"json5":            JSON,            // 
		"jsonc":            JSON,            // 
		"jsx":              REACT,           // 
		"jwmrc":            0xf35b,          // 
		"jxl":              IMAGE,           // 
		"kbx":              SHIELD_KEY,      // 󰯄
		"kdb":              KEYPASS,         // 
		"kdbx":             KEYPASS,         // 
		"kdenlive":         KDENLIVE,        // 
		"kdenlivetitle":    KDENLIVE,        // 
		"key":              KEY,             // 
		"kicad_dru":        KICAD,           // 
		"kicad_mod":        KICAD,           // 
		"kicad_pcb":        KICAD,           // 
		"kicad_prl":        KICAD,           // 
		"kicad_pro":        KICAD,           // 
		"kicad_sch":        KICAD,           // 
		"kicad_sym":        KICAD,           // 
		"kicad_wks":        KICAD,           // 
		"ko":               OS_LINUX,        // 
		"kpp":              KRITA,           // 
		"kra":              KRITA,           // 
		"krz":              KRITA,           // 
		"ksh":              SHELL_CMD,       // 
		"kt":               LANG_KOTLIN,     // 
		"kts":              LANG_KOTLIN,     // 
		"latex":            LANG_TEX,        // 
		"lbr":              LIBRARY,         // 
		"lck":              LOCK,            // 
		"ldb":              DATABASE,        // 
		"leex":             LANG_ELIXIR,     // 
		"less":             0xe758,          // 
		"lff":              FONT,            // 
		"lhs":              LANG_HASKELL,    // 
		"lib":              LIBRARY,         // 
		"license":          LICENSE,         // 
		"lisp":             0xf0172,         // 󰅲
		"localized":        OS_APPLE,        // 
		"lock":             LOCK,            // 
		"log":              LOG,             // 
		"lpp":              EDA_PCB,         // 
		"lrc":              SUBTITLE,        // 󰨖
		"ltx":              LANG_TEX,        // 
		"lua":              LANG_LUA,        // 
		"luac":             LANG_LUA,        // 
		"luau":             LANG_LUA,        // 
		"lz":               COMPRESSED,      // 
		"lz4":              COMPRESSED,      // 
		"lzh":              COMPRESSED,      // 
		"lzma":             COMPRESSED,      // 
		"lzo":              COMPRESSED,      // 
		"m":                LANG_C,          // 
		"m2ts":             VIDEO,           // 
		"m2v":              VIDEO,           // 
		"m3u":              PLAYLIST,        // 󰲹
		"m3u8":             PLAYLIST,        // 󰲹
		"m4a":              AUDIO,           // 
		"m4v":              VIDEO,           // 
		"magnet":           0xf076,          // 
		"markdown":         MARKDOWN,        // 
		"md":               MARKDOWN,        // 
		"md5":              SHIELD_CHECK,    // 󰕥
		"mdb":              DATABASE,        // 
		"mdx":              MARKDOWN,        // 
		"mid":              0xf08f2,         // 󰣲
		"mjs":              LANG_JAVASCRIPT, // 
		"mk":               MAKE,            // 
		"mka":              AUDIO,           // 
		"mkd":              MARKDOWN,        // 
		"mkv":              VIDEO,           // 
		"ml":               LANG_OCAML,      // 
		"mli":              LANG_OCAML,      // 
		"mll":              LANG_OCAML,      // 
		"mly":              LANG_OCAML,      // 
		"mm":               LANG_CPP,        // 
		"mo":               TRANSLATION,     // 󰗊
		"mobi":             BOOK,            // 
		"mov":              VIDEO,           // 
		"mp2":              AUDIO,           // 
		"mp3":              AUDIO,           // 
		"mp4":              VIDEO,           // 
		"mpeg":             VIDEO,           // 
		"mpg":              VIDEO,           // 
		"msf":              0xf370,          // 
		"msi":              OS_WINDOWS,      // 
		"mts":              LANG_TYPESCRIPT, // 
		"mustache":         MUSTACHE,        // 
		"nef":              IMAGE,           // 
		"nfo":              INFO,            // 
		"nim":              LANG_NIM,        // 
		"nimble":           LANG_NIM,        // 
		"nims":             LANG_NIM,        // 
		"ninja":            0xf0774,         // 󰝴
		"nix":              0xf313,          // 
		"node":             NODEJS,          // 
		"norg":             0xe847,          // 
		"nsp":              0xF07E1,         // 󰟡
		"nu":               SHELL_CMD,       // 
		"o":                BINARY,          // 
		"obj":              FILE_3D,         // 󰆧
		"odb":              DATABASE,        // 
		"odf":              0xf37b,          // 
		"odg":              0xf379,          // 
		"odp":              0xf37a,          // 
		"ods":              0xf378,          // 
		"odt":              0xf37c,          // 
		"ogg":              AUDIO,           // 
		"ogm":              VIDEO,           // 
		"ogv":              VIDEO,           // 
		"opml":             XML,             // 󰗀
		"opus":             AUDIO,           // 
		"orf":              IMAGE,           // 
		"org":              0xe633,          // 
		"otf":              FONT,            // 
		"out":              0xeb2c,          // 
		"p12":              KEY,             // 
		"par":              COMPRESSED,      // 
		"part":             DOWNLOAD,        // 󰇚
		"patch":            DIFF,            // 
		"pbm":              IMAGE,           // 
		"pcbdoc":           EDA_PCB,         // 
		"pcm":              AUDIO,           // 
		"pdf":              0xf1c1,          // 
		"pem":              KEY,             // 
		"pfx":              KEY,             // 
		"pgm":              IMAGE,           // 
		"phar":             LANG_PHP,        // 
		"php":              LANG_PHP,        // 
		"pkg":              0xeb29,          // 
		"pl":               LANG_PERL,       // 
		"plist":            OS_APPLE,        // 
		"pls":              PLAYLIST,        // 󰲹
		"plx":              LANG_PERL,       // 
		"ply":              FILE_3D,         // 󰆧
		"pm":               LANG_PERL,       // 
		"png":              IMAGE,           // 
		"pnm":              IMAGE,           // 
		"po":               TRANSLATION,     // 󰗊
		"pod":              LANG_PERL,       // 
		"pot":              TRANSLATION,     // 󰗊
		"pp":               0xe631,          // 
		"ppm":              IMAGE,           // 
		"pps":              SLIDE,           // 
		"ppsx":             SLIDE,           // 
		"ppt":              SLIDE,           // 
		"pptx":             SLIDE,           // 
		"prjpcb":           EDA_PCB,         // 
		"procfile":         LANG_RUBY,       // 
		"properties":       JSON,            // 
		"prql":             DATABASE,        // 
		"ps":               VECTOR,          // 󰕙
		"ps1":              POWERSHELL,      // 
		"psb":              0xe7b8,          // 
		"psd":              0xe7b8,          // 
		"psd1":             POWERSHELL,      // 
		"psf":              FONT,            // 
		"psm":              CAD,             // 󰻫
		"psm1":             POWERSHELL,      // 
		"pub":              PUBLIC_KEY,      // 󰷖
		"purs":             0xe630,          // 
		"pxd":              LANG_PYTHON,     // 
		"pxm":              IMAGE,           // 
		"py":               LANG_PYTHON,     // 
		"pyc":              LANG_PYTHON,     // 
		"pyd":              LANG_PYTHON,     // 
		"pyi":              LANG_PYTHON,     // 
		"pyo":              LANG_PYTHON,     // 
		"pyw":              LANG_PYTHON,     // 
		"pyx":              LANG_PYTHON,     // 
		"qcow":             DISK_IMAGE,      // 
		"qcow2":            DISK_IMAGE,      // 
		"qm":               TRANSLATION,     // 󰗊
		"qml":              QT,              // 
		"qrc":              QT,              // 
		"qss":              QT,              // 
		"r":                LANG_R,          // 
		"rake":             LANG_RUBY,       // 
		"rakefile":         LANG_RUBY,       // 
		"rar":              COMPRESSED,      // 
		"raw":              IMAGE,           // 
		"razor":            RAZOR,           // 
		"rb":               LANG_RUBY,       // 
		"rdata":            LANG_R,          // 
		"rdb":              0xe76d,          // 
		"rdoc":             MARKDOWN,        // 
		"rds":              LANG_R,          // 
		"readme":           README,          // 󰂺
		"rkt":              LANG_SCHEME,     // 
		"rlib":             LANG_RUST,       // 
		"rmd":              MARKDOWN,        // 
		"rmeta":            LANG_RUST,       // 
		"rpm":              0xe7bb,          // 
		"rs":               LANG_RUST,       // 
		"rspec":            LANG_RUBY,       // 
		"rspec_parallel":   LANG_RUBY,       // 
		"rspec_status":     LANG_RUBY,       // 
		"rss":              0xf09e,          // 
		"rst":              TEXT,            // 
		"rtf":              TEXT,            // 
		"ru":               LANG_RUBY,       // 
		"rubydoc":          LANG_RUBYRAILS,  // 
		"s":                LANG_ASSEMBLY,   // 
		"s3db":             SQLITE,          // 
		"sal":              0xf147b,         // 󱑻
		"sass":             LANG_SASS,       // 
		"sbt":              SUBTITLE,        // 󰨖
		"scad":             0xf34e,          // 
		"scala":            0xe737,          // 
		"sch":              EDA_SCH,         // 󰭅
		"schdoc":           EDA_SCH,         // 󰭅
		"scm":              LANG_SCHEME,     // 
		"scss":             LANG_SASS,       // 
		"service":          0xeba2,          // 
		"sf2":              0xf0f70,         // 󰽰
		"sfz":              0xf0f70,         // 󰽰
		"sh":               SHELL_CMD,       // 
		"sha1":             SHIELD_CHECK,    // 󰕥
		"sha224":           SHIELD_CHECK,    // 󰕥
		"sha256":           SHIELD_CHECK,    // 󰕥
		"sha384":           SHIELD_CHECK,    // 󰕥
		"sha512":           SHIELD_CHECK,    // 󰕥
		"shell":            SHELL_CMD,       // 
		"shtml":            HTML5,           // 
		"sig":              SIGNED_FILE,     // 󱧃
		"signature":        SIGNED_FILE,     // 󱧃
		"skp":              CAD,             // 󰻫
		"sl3":              SQLITE,          // 
		"sld":              LANG_SCHEME,     // 
		"sldasm":           CAD,             // 󰻫
		"sldprt":           CAD,             // 󰻫
		"slim":             LANG_RUBYRAILS,  // 
		"sln":              0xe70c,          // 
		"slvs":             CAD,             // 󰻫
		"so":               OS_LINUX,        // 
		"sql":              DATABASE,        // 
		"sqlite":           SQLITE,          // 
		"sqlite3":          SQLITE,          // 
		"sr":               0xf147b,         // 󱑻
		"srt":              SUBTITLE,        // 󰨖
		"ss":               LANG_SCHEME,     // 
		"ssa":              SUBTITLE,        // 󰨖
		"ste":              CAD,             // 󰻫
		"step":             CAD,             // 󰻫
		"stl":              FILE_3D,         // 󰆧
		"stp":              CAD,             // 󰻫
		"sty":              LANG_TEX,        // 
		"styl":             LANG_STYLUS,     // 
		"stylus":           LANG_STYLUS,     // 
		"sub":              SUBTITLE,        // 󰨖
		"sublime-build":    SUBLIME,         // 
		"sublime-keymap":   SUBLIME,         // 
		"sublime-menu":     SUBLIME,         // 
		"sublime-options":  SUBLIME,         // 
		"sublime-package":  SUBLIME,         // 
		"sublime-project":  SUBLIME,         // 
		"sublime-session":  SUBLIME,         // 
		"sublime-settings": SUBLIME,         // 
		"sublime-snippet":  SUBLIME,         // 
		"sublime-theme":    SUBLIME,         // 
		"sv":               LANG_HDL,        // 󰍛
		"svelte":           0xe697,          // 
		"svg":              VECTOR,          // 󰕙
		"svh":              LANG_HDL,        // 󰍛
		"swf":              AUDIO,           // 
		"swift":            0xe755,          // 
		"t":                LANG_PERL,       // 
		"tape":             0xF0A1B,         // 󰨛
		"tar":              COMPRESSED,      // 
		"taz":              COMPRESSED,      // 
		"tbc":              0xf06d3,         // 󰛓
		"tbz":              COMPRESSED,      // 
		"tbz2":             COMPRESSED,      // 
		"tc":               DISK_IMAGE,      // 
		"tcl":              0xf06d3,         // 󰛓
		"tex":              LANG_TEX,        // 
		"tf":               TERRAFORM,       // 󱁢
		"tfstate":          TERRAFORM,       // 󱁢
		"tfvars":           TERRAFORM,       // 󱁢
		"tgz":              COMPRESSED,      // 
		"tif":              IMAGE,           // 
		"tiff":             IMAGE,           // 
		"tlz":              COMPRESSED,      // 
		"tml":              CONFIG,          // 
		"tmux":             TMUX,            // 
		"toml":             TOML,            // 
		"torrent":          0xe275,          // 
		"tres":             GODOT,           // 
		"ts":               LANG_TYPESCRIPT, // 
		"tscn":             GODOT,           // 
		"tsv":              SHEET,           // 
		"tsx":              REACT,           // 
		"ttc":              FONT,            // 
		"ttf":              FONT,            // 
		"twig":             0xe61c,          // 
		"txt":              TEXT,            // 
		"txz":              COMPRESSED,      // 
		"typ":              TYPST,           // 
		"tz":               COMPRESSED,      // 
		"tzo":              COMPRESSED,      // 
		"ui":               0xf2d0,          // 
		"unity":            UNITY,           // 
		"unity3d":          UNITY,           // 
		"v":                LANG_V,          // 
		"vala":             0xe8d1,          // 
		"vdi":              DISK_IMAGE,      // 
		"vhd":              DISK_IMAGE,      // 
		"vhdl":             LANG_HDL,        // 󰍛
		"vhs":              0xF0A1B,         // 󰨛
		"vi":               0xe81e,          // 
		"video":            VIDEO,           // 
		"vim":              VIM,             // 
		"vmdk":             DISK_IMAGE,      // 
		"vob":              VIDEO,           // 
		"vsix":             0xf0a1e,         // 󰨞
		"vue":              0xf0844,         // 󰡄
		"war":              LANG_JAVA,       // 
		"wav":              AUDIO,           // 
		"webm":             VIDEO,           // 
		"webmanifest":      JSON,            // 
		"webp":             IMAGE,           // 
		"whl":              LANG_PYTHON,     // 
		"windows":          OS_WINDOWS,      // 
		"wma":              AUDIO,           // 
		"wmv":              VIDEO,           // 
		"woff":             FONT,            // 
		"woff2":            FONT,            // 
		"wrl":              FILE_3D,         // 󰆧
		"wrz":              FILE_3D,         // 󰆧
		"wv":               AUDIO,           // 
		"x_b":              CAD,             // 󰻫
		"x_t":              CAD,             // 󰻫
		"xaml":             0xf0673,         // 󰙳
		"xcf":              GIMP,            // 
		"xci":              0xF07E1,         // 󰟡
		"xhtml":            HTML5,           // 
		"xlr":              SHEET,           // 
		"xls":              SHEET,           // 
		"xlsm":             SHEET,           // 
		"xlsx":             SHEET,           // 
		"xml":              XML,             // 󰗀
		"xpi":              0xeae6,          // 
		"xpm":              IMAGE,           // 
		"xul":              XML,             // 󰗀
		"xz":               COMPRESSED,      // 
		"yaml":             YAML,            // 
		"yml":              YAML,            // 
		"z":                COMPRESSED,      // 
		"z64":              0xf1393,         // 󱎓
		"zig":              0xe6a9,          // 
		"zip":              COMPRESSED,      // 
		"zsh":              SHELL_CMD,       // 
		"zsh-theme":        SHELL,           // 󱆃
		"zst":              COMPRESSED,      // 
	}
}) // }}}

func IconForPath(path string) string {
	bn := filepath.Base(path)
	if ans, found := FileNameMap()[bn]; found {
		return string(ans)
	}
	if _, ext, found := strings.Cut(bn, "."); found {
		if ans, found := ExtensionMap()[strings.ToLower(ext)]; found {
			return string(ans)
		}
	}
	return string(FILE)
}

func IconForFileWithMode(path string, mode fs.FileMode, follow_symlinks bool) string {
	switch mode & fs.ModeType {
	case fs.ModeDir:
		bn := filepath.Base(path)
		if ans, found := DirectoryNameMap()[bn]; found {
			return string(ans)
		}
		return string(FOLDER)
	case fs.ModeSymlink:
		if follow_symlinks {
			if dest, err := os.Readlink(path); err == nil {
				if st, err := os.Stat(dest); err == nil {
					if st.IsDir() {
						return string(SYMLINK_TO_DIR)
					}
					return IconForFileWithMode(dest, st.Mode(), follow_symlinks)
				}
			}
		}
		return string(SYMLINK)
	case fs.ModeNamedPipe:
		return string(NAMED_PIPE)
	case fs.ModeSocket:
		return string(SOCKET)
	default:
		return IconForPath(path)
	}
}
