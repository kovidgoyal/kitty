/*jshint esversion: 6 */

(function() {
    'use strict';

    function init_timestamps() {
        document.querySelectorAll('.video-with-timestamps').forEach(loc => {
            if (loc.dataset.inited === 'true') return;
            loc.dataset.inited = 'true';
            const container_id = loc.id;
            const dl = loc.querySelector('dl');
            dl.querySelectorAll('dt').forEach(dt => {
                dt.innerHTML = '<a href="javascript:void(0)" style="text-decoration: none"><time>' + dt.innerHTML + '</time></a>';
                dt.style.display = 'inline';
            });
            dl.addEventListener('click', handle_timestamp_click.bind(null, container_id));
        });
    }

    function handle_timestamp_click(container_id, e) {
        if (e.target.tagName.toUpperCase() === 'TIME') {
            const timestamp = e.target.textContent;
            if (timestamp) {
                const [minutes, seconds] = timestamp.split(':');
                const total_seconds = parseInt(minutes) * 60 + parseInt(seconds);
                const video = document.querySelector('#' + container_id + ' video');
                video.currentTime = total_seconds;
                video.play();
            }
        }
    }

    init_timestamps();
    document.addEventListener('DOMContentloaded', init_timestamps);
})();
