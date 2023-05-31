/*jshint esversion: 6 */

(function() {
    function init_timestamps() {
        document.querySelectorAll('.timestamp-list').forEach(loc => {
            var dl = loc.querySelector('dl');
            dl.querySelectorAll('dt').forEach(dt => {
                dt.innerHTML = '<a href="javascript:void(0)" style="text-decoration: none"><time>' + dt.innerHTML + '</time></a>';
                dt.style.display = 'inline';
            });
            dl.addEventListener('click', handle_timestamp_click);
        });
    }

    function handle_timestamp_click(e) {
        if (e.target.tagName.toUpperCase() === 'TIME') {
            const timestamp = e.target.textContent;
            if (timestamp) {
                const [minutes, seconds] = timestamp.split(':');
                const totalSeconds = parseInt(minutes) * 60 + parseInt(seconds);
                const video = document.querySelector('video');
                video.currentTime = totalSeconds;
                video.play();
            }
        }
    }

    window.addEventListener('load', init_timestamps);
})();
