/* vim:fileencoding=utf-8
 *
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPLv3 license
 */

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
    var sidebar_tree = document.querySelector('.sidebar-tree');
    if (document.location.hash.length > 1) {
        var a = sidebar_tree.querySelector('a[href="' + document.location.hash + '"]');
        if (a) mark_current_link(sidebar_tree, a, onload);
    } else {
        if (onload) scroll_sidebar_node_into_view(sidebar_tree.querySelector('.current-page a'));
    }
}

document.addEventListener("DOMContentLoaded", function() {
    show_hash_in_sidebar(true);
    window.addEventListener('hashchange', show_hash_in_sidebar.bind(null, false));
});

}());

