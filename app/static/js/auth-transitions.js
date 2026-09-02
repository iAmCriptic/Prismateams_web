(function () {
    'use strict';

    var container = document.getElementById('authSplitRoot') || document.querySelector('.auth-split-container');
    if (!container) return;

    var TRANSITION_KEY = 'authPageTransition';
    var EXIT_MS = 320;
    var ENTER_FALLBACK_MS = 520;

    function finishEnterTransition() {
        container.classList.remove(
            'auth-transition-enter',
            'auth-transition-enter-to-register',
            'auth-transition-enter-to-login'
        );
        container.classList.add('auth-transition-done');
    }

    function watchEnterAnimation() {
        var card = container.querySelector('.auth-split-form .auth-card');
        var brandInner = container.querySelector('.auth-split-brand-inner');
        var finishedTargets = new Set();
        var finished = false;

        function maybeFinish(eventTarget) {
            if (eventTarget) finishedTargets.add(eventTarget);
            var expected = (card ? 1 : 0) + (brandInner ? 1 : 0);
            if (finished || finishedTargets.size < expected) return;
            finished = true;
            finishEnterTransition();
        }

        function onEnd(event) {
            if (event.target !== card && event.target !== brandInner) return;
            maybeFinish(event.target);
        }

        if (card) card.addEventListener('animationend', onEnd, { once: true });
        if (brandInner) brandInner.addEventListener('animationend', onEnd, { once: true });

        window.setTimeout(function () {
            if (!finished) {
                finished = true;
                finishEnterTransition();
            }
        }, ENTER_FALLBACK_MS);
    }

    if (container.classList.contains('auth-transition-enter')) {
        watchEnterAnimation();
    } else {
        container.classList.add('auth-initial-mount');
        window.setTimeout(function () {
            container.classList.remove('auth-initial-mount');
            container.classList.add('auth-transition-done');
        }, 680);
    }

    document.querySelectorAll('.auth-page-switch').forEach(function (link) {
        link.addEventListener('click', function (event) {
            var transition = link.getAttribute('data-auth-transition');
            if (!transition || event.defaultPrevented) return;

            event.preventDefault();
            sessionStorage.setItem(TRANSITION_KEY, transition);
            container.classList.add('auth-transition-exit', 'auth-transition-exit-' + transition);

            window.setTimeout(function () {
                window.location.href = link.href;
            }, EXIT_MS);
        });
    });
})();
