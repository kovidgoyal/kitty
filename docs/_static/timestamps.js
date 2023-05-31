// NOTE: After updating timestamps_source.js, please update the term in the ARRAY object as well,
// so it can have the right styling
import timestamps from './timestamps_source.js'

const ARRAY = {
    SPAN: null,
    KBD: ['Ctrl+Shift+g', "Ctrl+Shift+Left-click", '<Ctrl+Shift+P>y', 'Ctrl+Shift+F7', 'Ctrl+Shift+<num>', 'Ctrl+Shift+Esc', 'Ctrl+Shift+<win_nr>'],
    CODE: ['ls --hyperlink=auto', 'launch --allow-remote-control kitty +kitten broadcast', 'kitty +kitten themes -h', 'kitty +kitten themes [options] [theme_name]']
}

function init_timestamps() {
    const timestamps_element = get_timestamps_container(timestamps)
    timestamps_element.addEventListener('click', handle_timestamp_click)

    document.querySelector('.caption-text').insertAdjacentElement('afterend', timestamps_element)
}

function handle_timestamp_click(e) {
    if (e.target.tagName === 'TIME') {
        const timestamp = e.target.getAttribute('datetime')
        if (timestamp) {
            const [minutes, seconds] = timestamp.split(':')
            const totalSeconds = parseInt(minutes) * 60 + parseInt(seconds)
            const video = document.querySelector('video')
            video.currentTime = totalSeconds
            video.play()
        }
    }
}

function get_timestamps_container(file) {
    const timestamps_container = document.createElement('section')

    const rows_array = file.map(entry => {
        const [row_element, timestamp_element, description_element]
            = get_timestamp_elements(entry)

        row_element.append(timestamp_element, description_element)

        return row_element
    })
    rows_array.forEach(row => timestamps_container.appendChild(row))

    timestamps_container.id = 'timestamps'
    return timestamps_container
}

function get_timestamp_elements(entry) {
    return [
        get_simple_element('div', null, 'row'),
        get_simple_element('time', entry.time),
        get_updated_description_element(entry.description)
    ]
}

function get_simple_element(element, text_content = null, class_name = null) {
    const new_element = document.createElement(element)
    if (element === 'time') {
        new_element.dateTime = new_element.textContent = text_content
        return new_element
    }
    if (element === 'kbd' && !text_content) {
        return
    }
    if (text_content) {
        new_element.textContent = text_content
    }
    if (class_name) new_element.className = class_name
    return new_element
}

function get_updated_description_element(description) {
    const span_content_array = []

    const strong = get_strong_object(span_content_array, description)
    const kbd = get_kbd_object(span_content_array, description)
    const code = get_code_object(span_content_array, description)
    const span_element = get_span_element(span_content_array, description)

    const array_of_elements = [strong.element, span_element, kbd.element, code.element].filter(Boolean)

    const description_element = get_simple_element('p')
    description_element.append(...array_of_elements)

    return description_element
}

function get_strong_object(span_content_array, description) {
    const strong = {
        element: null,
        updated_description: null
    }
    set_strong_values(description, strong)

    if (strong.element) {
        span_content_array.push(strong.updated_description)
    }
    return strong
}

function set_strong_values(description, strong) {
    const matches = description.match(/^[^:]+/)
    strong.element = get_simple_element('strong', matches)
    strong.updated_description = delete_keywords_from_description(matches, description)
}

function get_kbd_object(span_content_array, description) {
    const kbd = {
        element: null,
        updated_description: null
    }

    set_kbd_values(span_content_array, description, kbd)

    if (kbd.updated_description) {
        span_content_array[0] = kbd.updated_description
    }

    return kbd
}

function set_kbd_values(span_content_array, description, kbd) {
    const last_updated_description = span_content_array.length > 0 ? span_content_array[0] : description

    const matching_words = get_matched_keyword(ARRAY.KBD, last_updated_description);
    const has_matches = matching_words?.length > 0

    if (!has_matches) return

    kbd.element = get_simple_element('kbd', matching_words)
    kbd.updated_description =
        delete_keywords_from_description(
            matching_words,
            last_updated_description
        )
}

function get_span_element(span_content_array, description) {
    let span_text_content = span_content_array.length < 1 ? description : span_content_array[0]
    span_content_array.push(span_text_content)

    return get_simple_element('span', span_text_content)
}

function get_code_object(span_content_array, description) {
    const code = {
        element: null,
        updated_description: null
    }
    set_code_values(span_content_array, description, code)

    if (code.updated_description) {
        span_content_array[0] = code.updated_description
    }
    return code
}

function set_code_values(span_content_array, description, code) {
    const last_updated_description = span_content_array.length > 0 ? span_content_array[0] : description

    const matching_words = get_matched_keyword(ARRAY.CODE, last_updated_description);

    const has_matches = matching_words?.length > 0

    if (!has_matches) return

    code.element = get_simple_element('code', matching_words)
    code.updated_description =
        delete_keywords_from_description(
            matching_words,
            last_updated_description
        )
}

function get_matched_keyword(substrings, updated_description) {
    if (typeof updated_description !== 'string') return null

    const matches = substrings.filter(substring => {
        return updated_description.includes(substring)
    })
    if (matches.length < 1) return

    return matches
}

function delete_keywords_from_description(matches, description) {
    if (typeof matches === 'string') {
        return description.replace(matches, '')
    }
    const combined_regex = new RegExp(matches.map(escape_regex).join('|'), 'g')
    return description.replace(combined_regex, '')
}

function escape_regex(string) {
    return string.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
}
window.onload = init_timestamps
