/*jshint esversion: 11 */
import timestamps from './timestamps_source.js';

(function() {

function init_timestamps() {
    var loc = document.getElementById('timestamps-for-intro-video');
    if (loc) {
        const timestamps_element = get_timestamps_container(timestamps);
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
