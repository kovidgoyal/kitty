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

function mark_current_link(sidebar_tree, a, onload) {
    console.log(onload);
    var li = a.closest('li.has-children');
    while (li) {
        li.querySelector('input[type=checkbox]').setAttribute('checked', 'checked');
        li = li.parentNode.closest('li.has-children');
    }
    sidebar_tree.querySelectorAll('.current').forEach(function (elem) {
        elem.classList.remove('current');
    });
    if (onload) a.scrollIntoView();
    a.classList.add('current');
}

function show_hash_in_sidebar(onload) {
    var sidebar_tree = document.querySelector('.sidebar-tree');
    if (document.location.hash.length > 1) {
        var a = sidebar_tree.querySelector('a[href="' + document.location.hash + '"]');
        if (a) mark_current_link(sidebar_tree, a, onload);
    } else {
        if (onload) sidebar_tree.querySelector('.current-page a').scrollIntoView();
    }
}

document.addEventListener("DOMContentLoaded", function() {
    show_hash_in_sidebar(true);
    window.addEventListener('hashchange', show_hash_in_sidebar.bind(null, false));
});

}());

