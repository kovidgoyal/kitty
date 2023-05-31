/*jshint esversion: 6 */

(function() {
var data = [
    {
        time: "00:00",
        description: "Intro"
    },
    {
        time: "00:39",
        description: "Pager: View command output in same window: <kbd>Ctrl+Shift+g</kbd>"
    },
    {
        time: "01:43",
        description: "Pager: View command output in a separate window"
    },
    {
        time: "02:14",
        description: "Pager: Uses shell integration in kitty"
    },
    {
        time: "02:27",
        description: "Tab text: The output of cwd and last cmd "
    },
    {
        time: "03:03",
        description: "Open files from ls output with mouse: <kbd>Ctrl+Shift+Right-click</kbd>"
    },
    {
        time: "04:04",
        description: "Open files from ls output with keyboard: <kbd>Ctrl+Shift+P>y</kbd>"
    },
    {
        time: "04:26",
        description: "Open files on click: <code>ls --hyperlink=auto</code>"
    },
    {
        time: "05:03",
        description: "Open files on click: Filetype settings in open-actions.conf"
    },
    {
        time: "05:45",
        description: "hyperlinked-grep kitten: Open grep output in editor"
    },
    {
        time: "07:18",
        description: "Remote-file kitten: View remote files locally"
    },
    {
        time: "08:31",
        description: "Remote-file kitten: Edit remote files locally"
    },
    {
        time: "10:01",
        description: "icat kitten: View images directly"
    },
    {
        time: "10:36",
        description: "icat kitten: Download & display image/gif from internet"
    },
    {
        time: "11:03",
        description: "Kitty Graphics Protocol: Live image preview in ranger"
    },
    {
        time: "11:25",
        description: "icat kitten: Display image from remote server"
    },
    {
        time: "12:04",
        description: "unicode-input kitten: Emojis in terminal "
    },
    {
        time: "12:54",
        description: "Windows: Intro"
    },
    {
        time: "13:36",
        description: "Windows: Switch focus: <kbd>Ctrl+Shift+&lt;win_nr&gt;</kbd>"
    },
    {
        time: "13:48",
        description: "Windows: Visual selection: <kbd>Ctrl+Shift+F7</kbd>"
    },
    {
        time: "13:58",
        description: "Windows: Simultaneous input"
    },
    {
        time: "14:15",
        description: "Interactive Kitty Shell: <kbd>Ctrl+Shift+Esc</kbd>"
    },
    {
        time: "14:36",
        description: "Broadcast text: <code>launch --allow-remote-control kitty +kitten broadcast</code>"
    },
    {
        time: "15:18",
        description: "Kitty Remote Control Protocol"
    },
    {
        time: "15:52",
        description: "Interactive Kitty Shell: Help"
    },
    {
        time: "16:34",
        description: "Choose theme interactively: <code>kitty +kitten themes -h</code>"
    },
    {
        time: "17:23",
        description: "Choose theme by name: <code>kitty +kitten themes [options] [theme_name]</code>"
    }
];

function init_timestamps() {
    var loc = document.getElementById('timestamps-for-intro-video');
    if (loc) {
        const timestamps_element = get_timestamps_container(data);
        timestamps_element.addEventListener('click', handle_timestamp_click);
        loc.appendChild(timestamps_element);
    }
}

function handle_timestamp_click(e) {
    if (e.target.tagName.toUpperCase() === 'TIME') {
        const timestamp = e.target.getAttribute('datetime');
        if (timestamp) {
            const [minutes, seconds] = timestamp.split(':');
            const totalSeconds = parseInt(minutes) * 60 + parseInt(seconds);
            const video = document.querySelector('video');
            video.currentTime = totalSeconds;
            video.play();
        }
    }
}

function get_timestamps_container(file) {
    const timestamps_container = document.createElement('section');

    const rows_array = file.map(entry => {
        const [row_element, timestamp_element, description_element] = get_timestamp_elements(entry);

        row_element.append(timestamp_element, description_element);

        return row_element;
    });
    rows_array.forEach(row => timestamps_container.appendChild(row));

    timestamps_container.id = 'timestamps';
    return timestamps_container;
}

function get_timestamp_elements(entry) {
    return [
        get_simple_element('div', null, 'row'),
        get_simple_element('time', entry.time),
        get_updated_description_element(entry.description)
    ];
}

function get_simple_element(element, text_content = null, class_name = null) {
    const new_element = document.createElement(element);
    if (element === 'time') {
        new_element.dateTime = new_element.textContent = text_content;
        return new_element;
    }
    if (element === 'kbd' && !text_content) {
        return;
    }
    if (text_content) {
        new_element.textContent = text_content;
    }
    if (class_name) new_element.className = class_name;
    return new_element;
}

function get_updated_description_element(description) {
    const description_element = get_simple_element('p');
    description_element.innerHTML = description;
    return description_element;
}

window.addEventListener('load', init_timestamps);
})();
