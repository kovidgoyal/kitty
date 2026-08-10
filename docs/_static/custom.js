/* vim:fileencoding=utf-8
 *
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPLv3 license
 */
/*jshint esversion: 6 */

(function() {
"use strict";

function get_sidebar_tree() {
    return document.querySelector('.sidebar-tree');
}

function scroll_sidebar_node_into_view(a) {
    var ss = get_sidebar_tree().closest('.sidebar-scroll');
    if (!ss || !a) return;
    ss.style.position = 'relative';
    var pos = 0;
    while (true) {
        pos += a.offsetTop;
        a = a.offsetParent;
        if (!a || a == ss) break;
    }
    ss.scrollTo({top: pos, behavior: 'instant'});
}

function mark_current_link(sidebar_tree, a, onload) {
    var li = a.closest('li.has-children');
    while (li) {
        li.querySelector('input[type=checkbox]').setAttribute('checked', 'checked');
        li = li.parentNode.closest('li.has-children');
    }
    sidebar_tree.querySelectorAll('.current').forEach(function (elem) {
        elem.classList.remove('current');
    });
    if (onload) scroll_sidebar_node_into_view(a);
    a.classList.add('current');
}

function show_hash_in_sidebar(onload) {
    const sidebar_tree = get_sidebar_tree();
    if (document.location.hash.length > 1) {
        var a = sidebar_tree.querySelector('a[href="' + document.location.hash + '"]');
        if (a) mark_current_link(sidebar_tree, a, onload);
    } else {
        if (onload) scroll_sidebar_node_into_view(sidebar_tree.querySelector('.current-page a'));
    }
}

function init_sidebar() {
    const sidebar_tree = document.querySelector('.sidebar-tree');
    if (!sidebar_tree || sidebar_tree.dataset.inited === 'true') return;
    sidebar_tree.dataset.inited = 'true';
    show_hash_in_sidebar(true);
    window.addEventListener('hashchange', show_hash_in_sidebar.bind(null, false));
}

document.addEventListener("DOMContentLoaded", init_sidebar);
init_sidebar();

function init_shader_modals() {
    var cards = document.querySelectorAll('.shader-demo-card');
    if (!cards.length) return;

    var overlay = document.createElement('div');
    overlay.id = 'shader-video-modal';
    overlay.className = 'shader-modal-overlay';
    overlay.innerHTML =
        '<div class="shader-modal-container">' +
        '<button class="shader-modal-close" aria-label="Close">×</button>' +
        '<video class="shader-modal-video" autoplay loop muted playsinline controls></video>' +
        '</div>';
    document.body.appendChild(overlay);

    var video = overlay.querySelector('.shader-modal-video');
    var close_btn = overlay.querySelector('.shader-modal-close');

    var saved_scroll_y = 0;

    function open_modal(video_src) {
        saved_scroll_y = window.scrollY;
        video.innerHTML = '<source src="' + video_src + '" type="video/webm">';
        video.addEventListener('loadedmetadata', function on_meta() {
            video.style.width = video.videoWidth + 'px';
            video.removeEventListener('loadedmetadata', on_meta);
        });
        video.load();
        video.play();
        overlay.classList.add('active');
        document.documentElement.classList.add('shader-modal-open');
    }

    function close_modal() {
        overlay.classList.remove('active');
        video.pause();
        video.innerHTML = '';
        video.style.width = '';
        document.documentElement.classList.remove('shader-modal-open');
        window.scrollTo({top: saved_scroll_y, left: 0, behavior: 'instant'});
    }

    cards.forEach(function(card) {
        var link = card.querySelector('a.sd-stretched-link');
        if (!link) return;
        var href = link.getAttribute('href');
        if (!href || href.slice(-5) !== '.webm') return;
        link.addEventListener('click', function(e) {
            e.preventDefault();
            open_modal(href);
        });
    });

    close_btn.addEventListener('click', close_modal);
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) close_modal();
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') close_modal();
    });
}

document.addEventListener("DOMContentLoaded", init_shader_modals);

}());

