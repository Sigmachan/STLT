// LuaTools button injection (standalone plugin)

// ============================================
// GAMEPAD NAVIGATION SYSTEM - Inline Version
// ============================================
(function () {
    'use strict';

    // Inject gamepad navigation CSS
    const gamepadCSS = document.createElement('style');
    gamepadCSS.id = 'gamepad-navigation-styles';
    gamepadCSS.textContent = `
        .active-focus {
            outline: 3px solid #66c0f4 !important;
            outline-offset: 2px !important;
            box-shadow: 0 0 0 4px rgba(102, 192, 244, 0.3),
                        0 0 12px rgba(102, 192, 244, 0.5) !important;
            position: relative !important;
            z-index: 9999 !important;
            transition: outline 0.15s ease, box-shadow 0.15s ease !important;
        }

        @keyframes gamepad-focus-pulse {
            0%, 100% {
                box-shadow: 0 0 0 4px rgba(102, 192, 244, 0.3),
                            0 0 12px rgba(102, 192, 244, 0.5);
            }
            50% {
                box-shadow: 0 0 0 4px rgba(102, 192, 244, 0.5),
                            0 0 16px rgba(102, 192, 244, 0.7);
            }
        }

        .active-focus {
            animation: gamepad-focus-pulse 1.5s ease-in-out infinite;
        }

        button.active-focus,
        a.active-focus {
            background-color: rgba(102, 192, 244, 0.15) !important;
            transform: scale(1.02);
        }

        .BasicUI .active-focus,
        .touch .active-focus {
            outline-width: 4px !important;
            outline-offset: 3px !important;
        }

        input.active-focus,
        select.active-focus,
        textarea.active-focus {
            border-color: #66c0f4 !important;
            background-color: rgba(102, 192, 244, 0.1) !important;
        }

        .active-focus:focus {
            outline: 3px solid #66c0f4 !important;
        }

        button,
        a,
        input,
        select,
        textarea,
        .focusable {
            transition: transform 0.15s ease, background-color 0.15s ease !important;
        }

        .luatools-button.active-focus,
        .luatools-restart-button.active-focus,
        .luatools-icon-button.active-focus {
            transform: scale(1.05) !important;
            background: linear-gradient(135deg, rgba(102, 192, 244, 0.3), rgba(102, 192, 244, 0.2)) !important;
        }

        .btnv6_blue_hoverfade.active-focus {
            background: linear-gradient(to right, #47bfff 5%, #1a9fff 95%) !important;
        }

        .active-focus {
            scroll-margin: 20px;
        }
    `;
    document.head.appendChild(gamepadCSS);

    // Gamepad Navigation System
    // ALL LuaTools overlays that should block Steam navigation
    const OVERLAY_SELECTORS = [
        '.luatools-overlay',
        '.luatools-settings-overlay',
        '.luatools-fixes-results-overlay',
        '.luatools-loading-fixes-overlay',
        '.luatools-unfix-overlay',
        '.luatools-settings-manager-overlay',
        '.luatools-alert-overlay',
        '.luatools-confirm-overlay',
        '.luatools-loadedapps-overlay'
    ];
    const OVERLAY_SELECTOR_STRING = OVERLAY_SELECTORS.join(', ');

    const CONFIG = {
        deadzone: 0.4, // Increased from 0.3 to prevent unwanted drift
        debounceTime: 200,
        pollRate: 16,
        stickThreshold: 0.7, // Increased threshold for stick navigation
        buttonMap: {
            A: 0,
            B: 1,
            X: 2,
            Y: 3,
            LB: 4,
            RB: 5,
            LT: 6,
            RT: 7,
            SELECT: 8,
            START: 9,
            L3: 10,
            R3: 11,
            DPAD_UP: 12,
            DPAD_DOWN: 13,
            DPAD_LEFT: 14,
            DPAD_RIGHT: 15
        },
        axesMap: {
            LEFT_STICK_X: 0,
            LEFT_STICK_Y: 1,
            RIGHT_STICK_X: 2,
            RIGHT_STICK_Y: 3
        }
    };

    const state = {
        gamepadConnected: false,
        gamepadIndex: null,
        focusableElements: [],
        currentFocusIndex: 0,
        lastNavigationTime: 0,
        lastAxisValues: {
            x: 0,
            y: 0
        },
        buttonStates: {},
        animationFrameId: null
    };

    // duplicated from main code thing for reliability
    function isBigPictureMode() {
        if (typeof window.__LUATOOLS_IS_BIG_PICTURE__ !== 'undefined') {
            return window.__LUATOOLS_IS_BIG_PICTURE__;
        }
        const htmlClasses = document.documentElement.className;
        const userAgent = navigator.userAgent;
        let score = 0;
        if (htmlClasses.includes('BasicUI')) score += 3;
        if (htmlClasses.includes('DesktopUI')) score -= 3;
        if (userAgent.includes('Valve Steam Gamepad')) score += 2;
        if (userAgent.includes('Valve Steam Client')) score -= 2;
        if (htmlClasses.includes('touch')) score += 1;
        return score > 0;
    }

    // B button handler removed - users should use the modal buttons directly
    // This prevents conflicts with Steam's back navigation
    let onBackHandler = function () {
        console.log('[Gamepad] B button pressed - ignoring (use modal buttons instead)');
        // Do nothing - let users navigate with D-pad/stick and press A on Cancel/Back buttons
    };

    function onGamepadConnected(event) {
        console.log('[Gamepad] Gamepad conectado en Millennium:', event.gamepad.id);
        state.gamepadConnected = true;
        state.gamepadIndex = event.gamepad.index;
        if (!state.animationFrameId) {
            pollGamepad();
        }
        // Don't scan immediately - only scan when an overlay is opened
        // scanFocusableElements() will be called by the overlay's setTimeout
    }

    function onGamepadDisconnected(event) {
        console.log('[Gamepad] Gamepad disconnected:', event.gamepad.id);
        if (state.gamepadIndex === event.gamepad.index) {
            state.gamepadConnected = false;
            state.gamepadIndex = null;
            if (state.animationFrameId) {
                cancelAnimationFrame(state.animationFrameId);
                state.animationFrameId = null;
            }
        }
    }

    function scanFocusableElements() {
        if (!isBigPictureMode()) return;

        // Only scan if there's a LuaTools overlay active
        const activeOverlay = document.querySelector(OVERLAY_SELECTOR_STRING);

        if (!activeOverlay) {
            console.log('[Gamepad] No LuaTools overlay active, skipping scan');
            state.focusableElements = [];
            state.currentFocusIndex = 0;
            return;
        }

        // Only scan elements INSIDE the active overlay
        const selectors = [
            'button:not([disabled])',
            'a[href]:not([disabled])',
            'input:not([disabled])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex="0"]',
            '[tabindex]:not([tabindex="-1"])',
            '.focusable:not([disabled])'
        ].join(', ');

        // Use querySelectorAll on the overlay, not the whole document
        const elements = Array.from(activeOverlay.querySelectorAll(selectors));
        state.focusableElements = elements.filter(function (el) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.opacity !== '0';
        });

        console.log('[Gamepad] Scanned ' + state.focusableElements.length + ' focusable elements inside overlay');

        if (state.focusableElements.length > 0) {
            focusElement(0);
        }
    }

    function focusElement(index) {
        const prevElement = state.focusableElements[state.currentFocusIndex];
        if (prevElement) {
            prevElement.blur();
            prevElement.classList.remove('active-focus');
        }

        if (index < 0) index = 0;
        if (index >= state.focusableElements.length) index = state.focusableElements.length - 1;

        state.currentFocusIndex = index;

        const element = state.focusableElements[index];
        if (element) {
            element.focus();
            element.classList.add('active-focus');
            element.scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
                inline: 'nearest'
            });
            console.log('[Gamepad] Focused element ' + index + ':', element);
        }
    }

    function navigate(direction) {
        const now = Date.now();
        if (now - state.lastNavigationTime < CONFIG.debounceTime) {
            return;
        }
        state.lastNavigationTime = now;

        if (state.focusableElements.length === 0) {
            scanFocusableElements();
            return;
        }

        let newIndex = state.currentFocusIndex;

        switch (direction) {
            case 'up':
                newIndex--;
                break;
            case 'down':
                newIndex++;
                break;
            case 'left':
                newIndex = findElementInDirection('left');
                break;
            case 'right':
                newIndex = findElementInDirection('right');
                break;
        }

        if (newIndex < 0) newIndex = state.focusableElements.length - 1;
        if (newIndex >= state.focusableElements.length) newIndex = 0;

        focusElement(newIndex);
    }

    function findElementInDirection(direction) {
        const currentElement = state.focusableElements[state.currentFocusIndex];
        if (!currentElement) return state.currentFocusIndex;

        const currentRect = currentElement.getBoundingClientRect();
        let closestIndex = state.currentFocusIndex;
        let closestDistance = Infinity;

        state.focusableElements.forEach(function (el, index) {
            if (index === state.currentFocusIndex) return;

            const rect = el.getBoundingClientRect();
            let isInDirection = false;
            let distance = 0;

            if (direction === 'left') {
                isInDirection = rect.right <= currentRect.left;
                distance = currentRect.left - rect.right;
            } else if (direction === 'right') {
                isInDirection = rect.left >= currentRect.right;
                distance = rect.left - currentRect.right;
            }

            if (isInDirection && distance < closestDistance) {
                closestDistance = distance;
                closestIndex = index;
            }
        });

        return closestIndex;
    }

    function handleButtonPress(buttonIndex) {
        const element = state.focusableElements[state.currentFocusIndex];

        switch (buttonIndex) {
            case CONFIG.buttonMap.A:
                if (element) {
                    console.log('[Gamepad] A button: clicking element', element);
                    element.click();
                    setTimeout(scanFocusableElements, 100);
                }
                break;

            case CONFIG.buttonMap.B:
                // B button disabled - users should use modal buttons
                console.log('[Gamepad] B button pressed - ignoring');
                break;

            case CONFIG.buttonMap.DPAD_UP:
                navigate('up');
                break;

            case CONFIG.buttonMap.DPAD_DOWN:
                navigate('down');
                break;

            case CONFIG.buttonMap.DPAD_LEFT:
                navigate('left');
                break;

            case CONFIG.buttonMap.DPAD_RIGHT:
                navigate('right');
                break;
        }
    }

    function pollGamepad() {
        if (!state.gamepadConnected) {
            state.animationFrameId = null;
            return;
        }

        // Check if there's an active LuaTools overlay
        const hasActiveOverlay = document.querySelector(OVERLAY_SELECTOR_STRING);

        // If no overlay is active, skip input processing but keep polling
        if (!hasActiveOverlay) {
            state.animationFrameId = requestAnimationFrame(pollGamepad);
            return;
        }

        const gamepads = navigator.getGamepads();
        const gamepad = gamepads[state.gamepadIndex];

        if (!gamepad) {
            state.animationFrameId = requestAnimationFrame(pollGamepad);
            return;
        }

        // Buttons
        gamepad.buttons.forEach(function (button, index) {
            const wasPressed = state.buttonStates[index] || false;
            const isPressed = button.pressed;

            if (isPressed && !wasPressed) {
                handleButtonPress(index);
            }

            state.buttonStates[index] = isPressed;
        });

        // Left stick
        const axisX = gamepad.axes[CONFIG.axesMap.LEFT_STICK_X] || 0;
        const axisY = gamepad.axes[CONFIG.axesMap.LEFT_STICK_Y] || 0;

        const x = Math.abs(axisX) > CONFIG.deadzone ? axisX : 0;
        const y = Math.abs(axisY) > CONFIG.deadzone ? axisY : 0;

        const now = Date.now();
        const threshold = CONFIG.stickThreshold; // Use higher threshold (0.7)
        if (now - state.lastNavigationTime >= CONFIG.debounceTime) {
            if (y < -threshold && state.lastAxisValues.y >= -threshold) {
                navigate('up');
            } else if (y > threshold && state.lastAxisValues.y <= threshold) {
                navigate('down');
            } else if (x < -threshold && state.lastAxisValues.x >= -threshold) {
                navigate('left');
            } else if (x > threshold && state.lastAxisValues.x <= threshold) {
                navigate('right');
            }
        }

        state.lastAxisValues.x = x;
        state.lastAxisValues.y = y;

        state.animationFrameId = requestAnimationFrame(pollGamepad);
    }

    // Disabled: MutationObserver was causing unwanted auto-scanning
    // Only manual scanElements() calls from overlay setTimeout will trigger scans
    /*
    const observer = new MutationObserver(function(mutations) {
        clearTimeout(observer.rescanTimeout);
        observer.rescanTimeout = setTimeout(function() {
            if (state.gamepadConnected) {
                scanFocusableElements();
            }
        }, 300);
    });
    */

    // Block Steam's gamepad navigation when overlay is active
    function blockSteamNavigation(event) {
        const hasActiveOverlay = document.querySelector(OVERLAY_SELECTOR_STRING);

        if (hasActiveOverlay && state.gamepadConnected) {
            // Block arrow keys, Enter, Escape, Backspace and other navigation keys
            // Note: Steam may translate gamepad B button to Escape or Backspace
            const navKeys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'Escape', 'Backspace', ' ', 'Tab'];
            if (navKeys.includes(event.key)) {
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();
                console.log('[Gamepad] Blocked Steam navigation key:', event.key);
                return false;
            }
        }
    }

    // Block clicks on Steam UI when overlay is active
    function blockSteamClicks(event) {
        const hasActiveOverlay = document.querySelector(OVERLAY_SELECTOR_STRING);

        if (hasActiveOverlay && state.gamepadConnected) {
            // Only allow clicks inside the overlay
            const clickedInsideOverlay = event.target.closest(OVERLAY_SELECTOR_STRING);

            if (!clickedInsideOverlay) {
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();
                console.log('[Gamepad] Blocked click outside overlay');
                return false;
            }
        }
    }

    // Block browser history navigation when overlay is active
    function blockHistoryNavigation(event) {
        const hasActiveOverlay = document.querySelector(OVERLAY_SELECTOR_STRING);
        if (hasActiveOverlay && state.gamepadConnected) {
            console.log('[Gamepad] Blocked history navigation (popstate)');
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            // Push the current state back to prevent navigation
            window.history.pushState(null, '', window.location.href);
            return false;
        }
    }

    function init() {
        if (!isBigPictureMode()) {
            console.log('[Gamepad] Not in Big Picture Mode, skipping initialization');
            return;
        }

        console.log('[Gamepad] Initializing Gamepad Navigation System...');

        window.addEventListener('gamepadconnected', onGamepadConnected);
        window.addEventListener('gamepaddisconnected', onGamepadDisconnected);

        // Block Steam's keyboard navigation when overlay is active
        document.addEventListener('keydown', blockSteamNavigation, true);
        document.addEventListener('keyup', blockSteamNavigation, true);

        // Block clicks outside overlay when gamepad is active
        document.addEventListener('click', blockSteamClicks, true);
        document.addEventListener('mousedown', blockSteamClicks, true);

        // Block browser history navigation (back button)
        window.addEventListener('popstate', blockHistoryNavigation, true);

        const gamepads = navigator.getGamepads();
        for (let i = 0; i < gamepads.length; i++) {
            if (gamepads[i]) {
                onGamepadConnected({
                    gamepad: gamepads[i]
                });
                break;
            }
        }

        // Disabled: MutationObserver auto-scanning
        /*
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        */

        // Don't scan on init - only scan when overlays are opened
        // scanFocusableElements();

        console.log('[Gamepad] Initialization complete');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.GamepadNav = {
        scanElements: scanFocusableElements,
        setBackHandler: function (fn) {
            if (typeof fn === 'function') {
                onBackHandler = fn;
            }
        },
        focusElement: focusElement,
        getCurrentIndex: function () {
            return state.currentFocusIndex;
        },
        getElements: function () {
            return state.focusableElements;
        },
        isConnected: function () {
            return state.gamepadConnected;
        }
    };
})();

// ============================================
// LUATOOLS MAIN CODE
// ============================================
(function () {
    'use strict';

    // Big Picture Mode Detector - Multi-method system for maximum reliability
    function isBigPictureMode() {
        const htmlClasses = document.documentElement.className;
        const userAgent = navigator.userAgent;

        // METHOD 1: HTML Classes
        // Big Picture: 'BasicUI' + 'touch'
        // Normal Mode: 'DesktopUI' (without 'touch')
        const hasBigPictureClass = htmlClasses.includes('BasicUI');
        const hasDesktopClass = htmlClasses.includes('DesktopUI');
        const hasTouchClass = htmlClasses.includes('touch');

        // METHOD 2: User Agent
        // Big Picture: 'Valve Steam Gamepad'
        // Normal Mode: 'Valve Steam Client'
        const isGamepadUA = userAgent.includes('Valve Steam Gamepad');
        const isClientUA = userAgent.includes('Valve Steam Client');

        // Scoring system: each indicator adds points
        let bigPictureScore = 0;

        // BasicUI/DesktopUI class (weight: 3 points - highly reliable)
        if (hasBigPictureClass) bigPictureScore += 3;
        if (hasDesktopClass) bigPictureScore -= 3;

        // User Agent (weight: 2 points - reliable)
        if (isGamepadUA) bigPictureScore += 2;
        if (isClientUA) bigPictureScore -= 2;

        // Touch class (weight: 1 point - additional indicator)
        if (hasTouchClass) bigPictureScore += 1;

        // Positive score = Big Picture, negative/zero = Normal
        const isBigPicture = bigPictureScore > 0;

        return isBigPicture;
    }

    // Detect and save mode at startup
    window.__LUATOOLS_IS_BIG_PICTURE__ = isBigPictureMode();

    // Forward logs to Millennium backend so they appear in the dev console
    function backendLog(message) {
        try {
            if (typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
                Millennium.callServerMethod('luatools', 'Logger.log', {
                    message: String(message)
                });
            }
        } catch (err) {
            if (typeof console !== 'undefined' && console.warn) {
                console.warn('[LuaTools] backendLog failed', err);
            }
        }
    }

    backendLog('LuaTools script loaded');
    backendLog('Mode Detection: ' + (window.__LUATOOLS_IS_BIG_PICTURE__ ? 'BIG PICTURE MODE' : 'NORMAL MODE'));
    // anti-spam state
    const logState = {
        missingOnce: false,
        existsOnce: false
    };
    // click/run debounce state
    const runState = {
        inProgress: false,
        appid: null
    };

    // Games Database - backend handles caching
    function fetchGamesDatabase() {
        if (typeof Millennium === 'undefined' || typeof Millennium.callServerMethod !== 'function') {
            return Promise.resolve({});
        }
        return Millennium.callServerMethod('luatools', 'GetGamesDatabase', {
            contentScriptQuery: ''
        })
            .then(function (res) {
                var payload = (res && (res.result || res.value)) || res;
                if (typeof payload === 'string') {
                    try {
                        payload = JSON.parse(payload);
                    } catch (e) { }
                }
                return payload || {};
            })
            .catch(function (err) {
                console.warn('[LuaTools] Failed to fetch games database', err);
                return {};
            });
    }

    // Fixes - backend handles caching
    // Client-side fixes cache: avoids redundant backend calls during rate-limit backoff
    const _fixesCache = {};
    const _FIXES_CACHE_TTL = 5 * 60 * 1000;        // 5 min normal results
    const _FIXES_RATELIMIT_TTL = 8 * 60 * 1000;    // 8 min rate-limited results

    function fetchFixes(appid) {
        const key = String(appid);
        const now = Date.now();
        const cached = _fixesCache[key];
        if (cached && (now - cached.ts) < (cached.rateLimited ? _FIXES_RATELIMIT_TTL : _FIXES_CACHE_TTL)) {
            return Promise.resolve(cached.data);
        }

        if (typeof Millennium === 'undefined' || typeof Millennium.callServerMethod !== 'function') {
            return Promise.resolve(null);
        }
        return Millennium.callServerMethod('luatools', 'CheckForFixes', {
            appid: appid,
            contentScriptQuery: ''
        })
            .then(function (res) {
                const payload = typeof res === 'string' ? JSON.parse(res) : res;
                if (payload) {
                    _fixesCache[key] = { data: payload, ts: now, rateLimited: !!payload.rateLimited };
                }
                return payload;
            })
            .catch(function () {
                return null;
            });
    }
    function fetchSteamGameName(appid) {
        if (!appid) return Promise.resolve(null);
        if (steamGameNameCache[appid]) return Promise.resolve(steamGameNameCache[appid]);

        return fetch('https://store.steampowered.com/api/appdetails?appids=' + appid + '&filters=basic')
            .then(function (res) {
                return res.json();
            })
            .then(function (data) {
                if (data && data[appid] && data[appid].success && data[appid].data && data[appid].data.name) {
                    const name = data[appid].data.name;
                    steamGameNameCache[appid] = name;
                    return name;
                }
                return null;
            })
            .catch(function (err) {
                backendLog('LuaTools: fetchSteamGameName error for ' + appid + ': ' + err);
                return null;
            });
    }


    const TRANSLATION_PLACEHOLDER = 'translation missing';

    function applyTranslationBundle(bundle) {
        if (!bundle || typeof bundle !== 'object') return;
        const stored = window.__LuaToolsI18n || {};
        if (bundle.language) {
            stored.language = String(bundle.language);
        } else if (!stored.language) {
            stored.language = 'en';
        }
        if (bundle.strings && typeof bundle.strings === 'object') {
            stored.strings = bundle.strings;
        } else if (!stored.strings) {
            stored.strings = {};
        }
        if (Array.isArray(bundle.locales)) {
            stored.locales = bundle.locales;
        } else if (!Array.isArray(stored.locales)) {
            stored.locales = [];
        }
        stored.ready = true;
        stored.lastFetched = Date.now();
        window.__LuaToolsI18n = stored;
    }

    // Theme definitions (pulled from themes.json; inline only used as fallback)
    const DEFAULT_THEMES = {
        original: {
            name: 'Original',
            bgPrimary: '#1b2838',
            bgSecondary: '#2a475e',
            bgTertiary: 'rgba(7, 7, 7, 0.86)',
            bgHover: 'rgba(7, 7, 7, 0.86)',
            bgContainer: 'rgba(11,20,30,0.6)',
            bgContainerGradient: 'rgba(11, 20, 30, 0.85), #0b141e',
            accent: '#66c0f4',
            accentLight: '#a4d7f5',
            accentDark: '#4a9ece',
            border: 'rgba(102,192,244,0.3)',
            borderHover: 'rgba(102,192,244,0.8)',
            text: '#fff',
            textSecondary: '#c7d5e0',
            gradient: 'linear-gradient(135deg, #66c0f4 0%, #a4d7f5 100%)',
            gradientLight: 'linear-gradient(135deg, #a4d7f5 0%, #7dd4ff 100%)',
            shadow: 'rgba(102,192,244,0.4)',
            shadowHover: 'rgba(102,192,244,0.6)',
        }
    };

    // Runtime THEMES map - start with fallback, then hydrate from themes.json/backend.
    let THEMES = DEFAULT_THEMES;
    let themesLoaded = false;

    function normalizeThemesPayload(input) {
        try {
            let payload = input;
            if (typeof payload === 'string') payload = JSON.parse(payload);
            if (payload && typeof payload === 'object') {
                if (Array.isArray(payload.themes)) return payload.themes;
                if (Array.isArray(payload.result)) return payload.result;
                if (payload.result && Array.isArray(payload.result.themes)) return payload.result.themes;
                if (Array.isArray(payload.value)) return payload.value;
            }
            if (Array.isArray(payload)) return payload;
        } catch (_) {
            /* ignore */
        }
        return [];
    }

    function _applyBackendThemes(themesArray) {
        try {
            const themes = normalizeThemesPayload(themesArray);
            if (!Array.isArray(themes) || themes.length === 0) return;
            const map = {};
            themes.forEach(function (t) {
                if (!t || (!t.value && !t.key)) return;
                const key = t.value || t.key;
                map[key] = Object.assign({}, t, {
                    value: key,
                    name: t.name || key
                });
            });
            if (Object.keys(map).length === 0) return;
            // Merge into existing THEMES if themes have been loaded, otherwise start from DEFAULT_THEMES
            THEMES = Object.assign({}, (themesLoaded ? THEMES : DEFAULT_THEMES), map);
            themesLoaded = true;
            try {
                ensureLuaToolsStyles();
            } catch (_) { }
        } catch (e) {
            console.warn('Failed to apply backend themes', e);
        }
    }

    function loadThemesFromFile() {
        try {
            return fetch('themes/themes.json', {
                cache: 'no-store'
            }).then(function (res) {
                if (!res || !res.ok) return null;
                return res.json();
            }).then(function (json) {
                if (!json) return null;
                _applyBackendThemes(json);
                return json;
            }).catch(function () {
                return null;
            });
        } catch (_) {
            return Promise.resolve(null);
        }
    }

    function loadThemesFromBackend() {
        if (typeof Millennium === 'undefined' || typeof Millennium.callServerMethod !== 'function') {
            return Promise.resolve(null);
        }
        return Millennium.callServerMethod('luatools', 'GetThemes', {
            contentScriptQuery: ''
        }).then(function (res) {
            try {
                const payload = typeof res === 'string' ? JSON.parse(res) : res;
                if (payload && payload.success && payload.themes) {
                    _applyBackendThemes(payload.themes);
                    return payload.themes;
                }
            } catch (_) { }
            return null;
        }).catch(function () {
            return null;
        });
    }

    function loadThemes() {
        return Promise.all([
            loadThemesFromFile(),
            loadThemesFromBackend()
        ]).catch(function () {
            /* ignore */
        });
    }

    // Trigger load (non-blocking). Keeps DEFAULT_THEMES as a safe fallback.
    const themeLoadPromise = loadThemes();

    function getCurrentThemeKey() {
        try {
            const settings = window.__LuaToolsSettings || {};
            const themeKey = (settings.values || {}).general || {};
            return themeKey.theme || 'original';
        } catch (e) {
            return 'original';
        }
    }

    function getCurrentTheme() {
        try {
            const themeName = getCurrentThemeKey();
            const theme = THEMES[themeName] || THEMES.original;
            if (!THEMES[themeName]) {
                try {
                    backendLog('LuaTools: Theme ' + themeName + ' not found in THEMES, using original. Available: ' + Object.keys(THEMES).join(', '));
                } catch (_) { }
            }
            return theme;
        } catch (e) {
            return THEMES.original;
        }
    }

    function hexToRgb(hex) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return result ? [
            parseInt(result[1], 16),
            parseInt(result[2], 16),
            parseInt(result[3], 16)
        ] : [102, 192, 244];
    }

    var _themeColorsCache = null;
    var _themeColorsCacheThemeId = null;
    function getThemeColors() {
        var currentId = (window.__LUATOOLS_CURRENT_THEME__ || {}).name || '_default';
        if (_themeColorsCache && _themeColorsCacheThemeId === currentId) return _themeColorsCache;
        const theme = getCurrentTheme();
        const rgb = hexToRgb(theme.accent);
        _themeColorsCache = {
            modalBg: `linear-gradient(135deg, ${theme.bgPrimary} 0%, ${theme.bgSecondary} 100%)`,
            border: theme.accent,
            borderRgba: theme.border,
            text: theme.text,
            textSecondary: theme.textSecondary,
            accent: theme.accent,
            accentLight: theme.accentLight,
            gradient: theme.gradient,
            gradientLight: theme.gradientLight,
            shadow: theme.shadow,
            shadowHover: theme.shadowHover,
            shadowRgba: theme.shadow.replace('0.4', '0.3'),
            bgContainer: theme.bgContainer,
            bgTertiary: theme.bgTertiary,
            bgHover: theme.bgHover,
            rgbString: rgb.join(',')
        };
        _themeColorsCacheThemeId = currentId;
        return _themeColorsCache;
    }
    function invalidateThemeCache() { _themeColorsCache = null; _themeColorsCacheThemeId = null; }

    function generateThemeStyles(theme) {
        return `
            /* Force overlay backdrops to follow the active theme (overrides inline styles) */
            .luatools-settings-overlay,
            .luatools-overlay,
            .luatools-fixes-results-overlay,
            .luatools-loading-fixes-overlay,
            .luatools-unfix-overlay,
            .luatools-settings-manager-overlay,
            .luatools-loadedapps-overlay {
                background: rgba(${theme.rgbString}, 0.12) !important;
                backdrop-filter: blur(8px) !important;
            }

            /* Prefer overlay-scoped select rules to override theme CSS files */
            .luatools-settings-overlay select,
            .luatools-settings-manager-overlay select,
            .luatools-overlay select,
            .luatools-fixes-results-overlay select,
            .luatools-loadedapps-overlay select {
                background-color: ${theme.bgTertiary} !important;
                color: ${theme.text} !important;
                border: 1px solid ${theme.border} !important;
                border-radius: 3px !important;
                padding: 6px 8px !important;
                font-size: 14px !important;
            }
            .luatools-settings-overlay select option,
            .luatools-settings-manager-overlay select option,
            .luatools-overlay select option,
            .luatools-fixes-results-overlay select option,
            .luatools-loadedapps-overlay select option {
                background-color: ${theme.bgPrimary} !important;
                color: ${theme.text} !important;
            }
            .luatools-settings-overlay select option:checked,
            .luatools-settings-manager-overlay select option:checked,
            .luatools-overlay select option:checked,
            .luatools-fixes-results-overlay select option:checked,
            .luatools-loadedapps-overlay select option:checked {
                background: ${theme.accent} !important;
                color: ${theme.text} !important;
            }
            .luatools-settings-overlay select:hover,
            .luatools-settings-manager-overlay select:hover,
            .luatools-overlay select:hover,
            .luatools-fixes-results-overlay select:hover,
            .luatools-loadedapps-overlay select:hover {
                border-color: ${theme.borderHover} !important;
            }
            .luatools-settings-overlay select:focus,
            .luatools-settings-manager-overlay select:focus,
            .luatools-overlay select:focus,
            .luatools-fixes-results-overlay select:focus,
            .luatools-loadedapps-overlay select:focus {
                outline: none !important;
                border-color: ${theme.accent} !important;
                box-shadow: 0 0 0 2px ${theme.shadow} !important;
            }
            .luatools-btn {
                padding: 12px 24px;
                background: ${theme.bgTertiary};
                border: 2px solid ${theme.border.replace('0.3', '0.5')};
                border-radius: 12px;
                color: ${theme.text};
                font-size: 15px;
                font-weight: 600;
                text-decoration: none;
                transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
                cursor: pointer;
                box-shadow: 0 2px 8px ${theme.shadow};
                letter-spacing: 0.3px;
            }
            .luatools-btn:hover:not([data-disabled="1"]) {
                background: ${theme.bgHover};
                transform: translateY(-2px);
                box-shadow: 0 6px 20px ${theme.shadowHover};
                border-color: ${theme.borderHover};
            }
            .luatools-btn.primary {
                background: ${theme.gradient};
                border-color: ${theme.borderHover.replace('0.8', '0.8')};
                color: ${theme.text};
                font-weight: 700;
                box-shadow: 0 4px 15px ${theme.shadow}, inset 0 1px 0 rgba(255,255,255,0.3);
                text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
            }
            .luatools-btn.primary:hover:not([data-disabled="1"]) {
                background: ${theme.gradientLight};
                transform: translateY(-3px) scale(1.03);
                box-shadow: 0 8px 25px ${theme.shadowHover}, inset 0 1px 0 rgba(255,255,255,0.4);
            }
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            @keyframes slideUp {
                from {
                    opacity: 0;
                    transform: scale(0.9);
                }
                to {
                    opacity: 1;
                    transform: scale(1);
                }
            }
            @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.7; }
            }
        `;
    }

    function ensureThemeStylesheet(themeKey) {
        const id = 'luatools-theme-css';
        const href = 'themes/' + themeKey + '.css';
        const link = document.getElementById(id);
        if (link) {
            const currentTheme = link.getAttribute('data-theme');
            if (currentTheme === themeKey) return;
            link.href = href;
            link.setAttribute('data-theme', themeKey);
            return;
        }
        try {
            const el = document.createElement('link');
            el.id = id;
            el.rel = 'stylesheet';
            el.href = href;
            el.setAttribute('data-theme', themeKey);
            document.head.appendChild(el);
        } catch (err) {
            backendLog('LuaTools: Theme CSS injection failed: ' + err);
        }
    }

    function ensureLuaToolsStyles() {
        const styleEl = document.getElementById('luatools-styles');
        const themeKey = getCurrentThemeKey();
        const theme = getCurrentTheme();
        const styles = generateThemeStyles(theme);

        try {
            ensureThemeStylesheet(themeKey);
        } catch (_) { }

        if (styleEl) {
            styleEl.textContent = styles;
        } else {
            try {
                const style = document.createElement('style');
                style.id = 'luatools-styles';
                style.textContent = styles;
                document.head.appendChild(style);
            } catch (err) {
                backendLog('LuaTools: Styles injection failed: ' + err);
            }
        }
    }

    function ensureFontAwesome() {
        if (document.getElementById('luatools-fontawesome')) return;
        try {
            const link = document.createElement('link');
            link.id = 'luatools-fontawesome';
            link.rel = 'stylesheet';
            link.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css';
            link.integrity = 'sha512-DTOQO9RWCH3ppGqcWaEA1BIZOC6xxalwEsw9c2QQeAIftl+Vegovlnee1c9QX4TctnWMn13TZye+giMm8e2LwA==';
            link.crossOrigin = 'anonymous';
            link.referrerPolicy = 'no-referrer';
            document.head.appendChild(link);
        } catch (err) {
            backendLog('LuaTools: Font Awesome injection failed: ' + err);
        }
    }

    function showSettingsPopup() {
        if (document.querySelector('.luatools-settings-overlay') || settingsMenuPending) return;
        settingsMenuPending = true;
        ensureTranslationsLoaded(false).catch(function () {
            return null;
        }).finally(function () {
            settingsMenuPending = false;
            if (document.querySelector('.luatools-settings-overlay')) return;

            try {
                const d = document.querySelector('.luatools-overlay');
                if (d) d.remove();
            } catch (_) { }
            ensureLuaToolsStyles();
            ensureFontAwesome();

            const overlay = document.createElement('div');
            overlay.className = 'luatools-settings-overlay';
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';
            try { LuaToolsMods.fireHook('onSettingsOpen', { overlay: overlay }); } catch (_) { }

            const modal = document.createElement('div');
            const colors = getThemeColors();
            modal.style.cssText = `position:relative;background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:8px;width:420px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${colors.shadowRgba};animation:slideUp 0.1s ease-out;`;

            const header = document.createElement('div');
            header.style.cssText = `display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid ${colors.borderRgba};`;

            const title = document.createElement('div');
            title.style.cssText = `font-size:15px;color:${colors.text};font-weight:700;text-shadow:0 2px 8px ${colors.shadow};background:${colors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
            title.textContent = t('menu.title', 'LuaTools · Menu');

            const iconButtons = document.createElement('div');
            iconButtons.style.cssText = 'display:flex;gap:6px;';

            function createIconButton(id, iconClass, titleKey, titleFallback) {
                const btn = document.createElement('a');
                btn.id = id;
                btn.href = '#';
                const btnColors = getThemeColors();
                btn.style.cssText = `display:flex;align-items:center;justify-content:center;width:28px;height:28px;background:rgba(${btnColors.rgbString},0.1);border:1px solid ${btnColors.borderRgba};border-radius:8px;color:${btnColors.accent};font-size:15px;text-decoration:none;transition:all 0.3s ease;cursor:pointer;`;
                btn.innerHTML = '<i class="fa-solid ' + iconClass + '"></i>';
                btn.title = t(titleKey, titleFallback);
                btn.onmouseover = function () {
                    this.style.background = `rgba(${btnColors.rgbString},0.25)`;
                    this.style.transform = 'translateY(-2px) scale(1.05)';
                    this.style.boxShadow = `0 8px 16px ${btnColors.shadowRgba}`;
                    this.style.borderColor = btnColors.accent;
                };
                btn.onmouseout = function () {
                    this.style.background = `rgba(${btnColors.rgbString},0.1)`;
                    this.style.transform = 'translateY(0) scale(1)';
                    this.style.boxShadow = 'none';
                    this.style.borderColor = btnColors.borderRgba;
                };
                iconButtons.appendChild(btn);
                return btn;
            }

            const body = document.createElement('div');
            body.style.cssText = 'font-size:12px;line-height:1.4;margin-bottom:6px;';

            // Add mouse mode tip for Big Picture
            if (window.__LUATOOLS_IS_BIG_PICTURE__) {
                const tip = document.createElement('div');
                tip.style.cssText = 'background:rgba(102,192,244,0.15);border-left:3px solid #66c0f4;padding:8px 10px;border-radius:5px;font-size:11px;color:#c7d5e0;margin-bottom:16px;line-height:1.5;';
                tip.innerHTML = '<i class="fa-solid fa-info-circle" style="margin-right:8px;color:#66c0f4;"></i>' + t('bigpicture.mouseTip', 'To use mouse mode in Steam: Guide Button + Right Joystick, click with RB');
                body.appendChild(tip);
            }

            const container = document.createElement('div');
            container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:4px;align-items:stretch;';

            function createSectionLabel(key, fallback, marginTop) {
                const label = document.createElement('div');
                const topValue = typeof marginTop === 'number' ? marginTop : 12;
                const labelColors = getThemeColors();
                label.style.cssText = `font-size:10px;color:${labelColors.accent};margin-top:${topValue}px;margin-bottom:2px;font-weight:600;text-transform:uppercase;letter-spacing:1.2px;text-align:center;`;
                label.textContent = t(key, fallback);
                container.appendChild(label);
                return label;
            }

            function createMenuButton(id, key, fallback, iconClass, isPrimary) {
                const btn = document.createElement('a');
                btn.id = id;
                btn.href = '#';
                const btnColors = getThemeColors();
                btn.style.cssText = `display:flex;align-items:center;justify-content:center;gap:5px;padding:6px 12px;background:linear-gradient(135deg, rgba(${btnColors.rgbString},0.15) 0%, rgba(${btnColors.rgbString},0.05) 100%);border:1px solid ${btnColors.borderRgba};border-radius:8px;color:${btnColors.text};font-size:12px;font-weight:500;text-decoration:none;transition:all 0.3s ease;cursor:pointer;position:relative;overflow:hidden;text-align:center;`;
                const iconHtml = iconClass ? '<i class="fa-solid ' + iconClass + '" style="font-size:16px;"></i>' : '';
                const textSpan = '<span style="text-align:center;">' + t(key, fallback) + '</span>';
                btn.innerHTML = iconHtml + textSpan;
                btn.onmouseover = function () {
                    const c = getThemeColors();
                    this.style.background = `linear-gradient(135deg, rgba(${c.rgbString},0.3) 0%, rgba(${c.rgbString},0.15) 100%)`;
                    this.style.transform = 'translateY(-2px)';
                    this.style.boxShadow = `0 8px 20px ${c.shadow.replace('0.4', '0.25')}`;
                    this.style.borderColor = c.accent;
                };
                btn.onmouseout = function () {
                    const c = getThemeColors();
                    this.style.background = `linear-gradient(135deg, rgba(${c.rgbString},0.15) 0%, rgba(${c.rgbString},0.05) 100%)`;
                    this.style.transform = 'translateY(0)';
                    this.style.boxShadow = 'none';
                    this.style.borderColor = c.borderRgba;
                };
                container.appendChild(btn);
                return btn;
            }

            const discordBtn = createIconButton('lt-settings-discord', 'fa-brands fa-discord', 'menu.discord', 'Discord');
            const settingsManagerBtn = createIconButton('lt-settings-open-manager', 'fa-gear', 'menu.settings', 'Settings');
            const closeBtn = createIconButton('lt-settings-close', 'fa-xmark', 'settings.close', 'Close');

            createSectionLabel('menu.manageGameLabel', 'Manage Game');

            const removeBtn = createMenuButton('lt-settings-remove-lua', 'menu.removeLuaTools', 'Remove via LuaTools', 'fa-trash-can');
            removeBtn.style.display = 'none';

            const fixesMenuBtn = createMenuButton('lt-settings-fixes-menu', 'menu.fixesMenu', 'Fixes Menu', 'fa-wrench');

            createSectionLabel('menu.advancedLabel', 'Advanced');
            const checkBtn = createMenuButton('lt-settings-check', 'menu.checkForUpdates', 'Check For Updates', 'fa-cloud-arrow-down');
            const fetchApisBtn = createMenuButton('lt-settings-fetch-apis', 'menu.fetchFreeApis', 'Fetch Free APIs', 'fa-server');

            createSectionLabel('menu.steamToolsLabel', 'SteamTools');
            const dashboardBtn = createMenuButton('lt-st-dashboard', 'menu.dashboard', '📊 Quick Dashboard', 'fa-gauge-high');
            const healthScanBtn = createMenuButton('lt-st-health-scan', 'menu.healthScan', '🩺 Health Scan All Scripts', 'fa-stethoscope');
            const repairAllBtn = createMenuButton('lt-st-repair-all', 'menu.repairAll', '🔧 Repair Depot Cache', 'fa-screwdriver-wrench');
            const gameToolsBtn = createMenuButton('lt-st-game-tools', 'menu.gameTools', '🎮 Game Tools (per-app)', 'fa-gamepad');
            const cacheInfoBtn = createMenuButton('lt-st-cache-info', 'menu.cacheManager', '🧹 Cache Manager', 'fa-broom');
            const folderStatsBtn = createMenuButton('lt-st-folder-stats', 'menu.folderStats', '📁 Folder Stats', 'fa-chart-pie');
            const conflictsBtn = createMenuButton('lt-st-conflicts', 'menu.depotConflicts', '⚠️ Depot Conflict Check', 'fa-triangle-exclamation');
            const libScanBtn = createMenuButton('lt-st-lib-scan', 'menu.libraryScan', '💿 Library Scanner', 'fa-hard-drive');
            const backupBtn = createMenuButton('lt-st-backup', 'menu.backupRestore', '💾 Backup & Restore', 'fa-box-archive');
            const customApisBtn = createMenuButton('lt-st-custom-apis', 'menu.customApis', '🔌 Custom API Sources', 'fa-plug');
            const smartRestartBtn = createMenuButton('lt-st-smart-restart', 'menu.smartRestart', '🔄 Smart Restart Steam', 'fa-rotate');

            body.appendChild(container);

            header.appendChild(title);
            header.appendChild(iconButtons);
            modal.appendChild(header);
            modal.appendChild(body);
            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // Re-scan elements for gamepad navigation
            setTimeout(function () {
                if (window.GamepadNav) {
                    window.GamepadNav.scanElements();
                }
            }, 150);

            // ── SteamTools: Quick Dashboard button ───────────────────
            if (dashboardBtn) {
                dashboardBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsDashboard();
                });
            }

            // ── SteamTools: Health Scan button ────────────────────────
            if (healthScanBtn) {
                healthScanBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsHealthScan();
                });
            if (repairAllBtn) {
                repairAllBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    var existingOvs = document.querySelectorAll('.luatools-overlay, .luatools-settings-overlay');
                    existingOvs.forEach(function(o) { o.remove(); });
                    showRepairDepotCachePanel();
                });
            }
            }

            // ── SteamTools: Cache Manager button ──────────────────────
            if (cacheInfoBtn) {
                cacheInfoBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsCacheManager();
                });
            }

            // ── SteamTools: Backup button ─────────────────────────────
            if (backupBtn) {
                backupBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsBackup();
                });
            }

            // ── SteamTools: Smart Restart button ──────────────────────
            if (smartRestartBtn) {
                smartRestartBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showLuaToolsConfirm('Smart Restart', 'Kill Steam and restart with -clearbeta? Achievement/playtime data will be preserved.', function () {
                        try {
                            Millennium.callServerMethod('luatools', 'SmartRestartSteam', { clearBeta: true, contentScriptQuery: '' })
                                .then(function (res) {
                                    try {
                                        var p = typeof res === 'string' ? JSON.parse(res) : res;
                                        ShowLuaToolsAlert('Smart Restart', p.message || (p.success ? 'Steam restarted.' : 'Failed.'));
                                    } catch (_) { }
                                });
                        } catch (_) { }
                    }, function () { showSettingsPopup(); });
                });
            }

            // ── SteamTools: Game Tools button ─────────────────────────
            if (gameToolsBtn) {
                gameToolsBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    var match = window.location.href.match(/\/app\/(\d+)/) ;
                    var appid = match ? parseInt(match[1], 10) : (window.__LuaToolsCurrentAppId || NaN);
                    if (isNaN(appid)) {
                        try { overlay.remove(); } catch (_) { }
                        ShowLuaToolsAlert('Game Tools', 'Navigate to a game page first to use per-app tools.');
                        return;
                    }
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsGamePanel(appid);
                });
            }

            // ── SteamTools: Folder Stats button ───────────────────────
            if (folderStatsBtn) {
                folderStatsBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsFolderStats();
                });
            }

            // ── SteamTools: Depot Conflicts button ────────────────────
            if (conflictsBtn) {
                conflictsBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsConflicts();
                });
            }

            // ── SteamTools: Library Scanner button ────────────────────
            if (libScanBtn) {
                libScanBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showSteamToolsLibraryScanner();
                });
            }

            // ── SteamTools: Custom APIs button ────────────────────────
            if (customApisBtn) {
                customApisBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try { overlay.remove(); } catch (_) { }
                    showCustomApisManager();
                });
            }

            if (checkBtn) {
                checkBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        overlay.remove();
                    } catch (_) { }
                    try {
                        Millennium.callServerMethod('luatools', 'CheckForUpdatesNow', {
                            contentScriptQuery: ''
                        }).then(function (res) {
                            try {
                                const payload = typeof res === 'string' ? JSON.parse(res) : res;
                                const msg = (payload && payload.message) ? String(payload.message) : lt('No updates available.');
                                ShowLuaToolsAlert('LuaTools', msg);
                            } catch (_) { }
                        });
                    } catch (_) { }
                });
            }

            if (discordBtn) {
                discordBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        overlay.remove();
                    } catch (_) { }
                    const url = 'https://discord.gg/luatools';
                    try {
                        Millennium.callServerMethod('luatools', 'OpenExternalUrl', {
                            url,
                            contentScriptQuery: ''
                        });
                    } catch (_) { }
                });
            }

            if (fetchApisBtn) {
                fetchApisBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        overlay.remove();
                    } catch (_) { }
                    try {
                        Millennium.callServerMethod('luatools', 'FetchFreeApisNow', {
                            contentScriptQuery: ''
                        }).then(function (res) {
                            try {
                                const payload = typeof res === 'string' ? JSON.parse(res) : res;
                                const ok = payload && payload.success;
                                const count = payload && payload.count;
                                const successText = lt('Loaded free APIs: {count}').replace('{count}', (count != null ? count : '?'));
                                const failText = (payload && payload.error) ? String(payload.error) : lt('Failed to load free APIs.');
                                const text = ok ? successText : failText;
                                ShowLuaToolsAlert('LuaTools', text);
                            } catch (_) { }
                        });
                    } catch (_) { }
                });
            }

            if (closeBtn) {
                closeBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    overlay.remove();
                });
            }

            if (settingsManagerBtn) { // This is the icon button now
                settingsManagerBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        overlay.remove();
                    } catch (_) { }
                    showSettingsManagerPopup(false, showSettingsPopup);
                });
            }

            if (fixesMenuBtn) {
                fixesMenuBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        const match = window.location.href.match(/https:\/\/store\.steampowered\.com\/app\/(\d+)/) || window.location.href.match(/https:\/\/steamcommunity\.com\/app\/(\d+)/);
                        const appid = match ? parseInt(match[1], 10) : (window.__LuaToolsCurrentAppId || NaN);
                        if (isNaN(appid)) {
                            try {
                                overlay.remove();
                            } catch (_) { }
                            const errText = t('menu.error.noAppId', 'Could not determine game AppID');
                            ShowLuaToolsAlert('LuaTools', errText);
                            return;
                        }

                        Millennium.callServerMethod('luatools', 'GetGameInstallPath', {
                            appid,
                            contentScriptQuery: ''
                        }).then(function (pathRes) {
                            try {
                                let isGameInstalled = false;
                                const pathPayload = typeof pathRes === 'string' ? JSON.parse(pathRes) : pathRes;
                                if (pathPayload && pathPayload.success && pathPayload.installPath) {
                                    isGameInstalled = true;
                                    window.__LuaToolsGameInstallPath = pathPayload.installPath;
                                }
                                window.__LuaToolsGameIsInstalled = isGameInstalled;
                                try {
                                    overlay.remove();
                                } catch (_) { }
                                showFixesLoadingPopupAndCheck(appid);
                            } catch (err) {
                                backendLog('LuaTools: GetGameInstallPath error: ' + err);
                                try {
                                    overlay.remove();
                                } catch (_) { }
                            }
                        }).catch(function () {
                            try {
                                overlay.remove();
                            } catch (_) { }
                            const errorText = t('menu.error.getPath', 'Error getting game path');
                            ShowLuaToolsAlert('LuaTools', errorText);
                        });
                    } catch (err) {
                        backendLog('LuaTools: Fixes Menu button error: ' + err);
                    }
                });
            }

            try {
                const match = window.location.href.match(/https:\/\/store\.steampowered\.com\/app\/(\d+)/) || window.location.href.match(/https:\/\/steamcommunity\.com\/app\/(\d+)/);
                const appid = match ? parseInt(match[1], 10) : (window.__LuaToolsCurrentAppId || NaN);
                if (!isNaN(appid) && typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
                    Millennium.callServerMethod('luatools', 'HasLuaToolsForApp', {
                        appid,
                        contentScriptQuery: ''
                    }).then(function (res) {
                        try {
                            const payload = typeof res === 'string' ? JSON.parse(res) : res;
                            const exists = !!(payload && payload.success && payload.exists === true);
                            if (exists) {
                                const doDelete = function () {
                                    try {
                                        Millennium.callServerMethod('luatools', 'DeleteLuaToolsForApp', {
                                            appid,
                                            contentScriptQuery: ''
                                        }).then(function () {
                                            try {
                                                window.__LuaToolsButtonInserted = false;
                                                window.__LuaToolsPresenceCheckInFlight = false;
                                                window.__LuaToolsPresenceCheckAppId = undefined;
                                                addLuaToolsButton();
                                                const successText = t('menu.remove.success', 'LuaTools removed for this app.');
                                                ShowLuaToolsAlert('LuaTools', successText);
                                            } catch (err) {
                                                backendLog('LuaTools: post-delete cleanup failed: ' + err);
                                            }
                                        }).catch(function (err) {
                                            const failureText = t('menu.remove.failure', 'Failed to remove LuaTools.');
                                            const errMsg = (err && err.message) ? err.message : failureText;
                                            ShowLuaToolsAlert('LuaTools', errMsg);
                                        });
                                    } catch (err) {
                                        backendLog('LuaTools: doDelete failed: ' + err);
                                    }
                                };

                                removeBtn.style.display = 'flex';
                                removeBtn.onclick = function (e) {
                                    e.preventDefault();
                                    try {
                                        overlay.remove();
                                    } catch (_) { }
                                    const confirmMessage = t('menu.remove.confirm', 'Remove via LuaTools for this game?');
                                    showLuaToolsConfirm('LuaTools', confirmMessage, function () {
                                        doDelete();
                                    }, function () {
                                        try {
                                            showSettingsPopup();
                                        } catch (_) { }
                                    });
                                };
                            } else {
                                removeBtn.style.display = 'none';
                            }
                        } catch (_) { }
                    });
                }
            } catch (_) { }
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // STEAMTOOLS OVERLAYS
    // ══════════════════════════════════════════════════════════════════

    function _stOverlayShell(titleText, buildBodyFn) {
        ensureLuaToolsStyles();
        ensureFontAwesome();
        var ov = document.createElement('div');
        ov.className = 'luatools-overlay';
        ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';
        var colors = getThemeColors();
        var modal = document.createElement('div');
        modal.style.cssText = 'position:relative;background:' + colors.modalBg + ';color:' + colors.text + ';border:2px solid ' + colors.border + ';border-radius:8px;width:460px;max-width:95vw;max-height:80vh;overflow-y:auto;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8);animation:slideUp 0.1s ease-out;';
        var hdr = document.createElement('div');
        hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid ' + colors.borderRgba + ';';
        var ttl = document.createElement('div');
        ttl.style.cssText = 'font-size:13px;font-weight:700;color:' + colors.accent + ';';
        ttl.textContent = titleText;
        var closeBtn = document.createElement('a');
        closeBtn.href = '#';
        closeBtn.style.cssText = 'color:' + colors.accent + ';font-size:16px;cursor:pointer;text-decoration:none;';
        closeBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        closeBtn.onclick = function (e) { e.preventDefault(); ov.remove(); };
        hdr.appendChild(ttl);
        hdr.appendChild(closeBtn);
        modal.appendChild(hdr);
        var body = document.createElement('div');
        body.style.cssText = 'font-size:14px;line-height:1.35;';
        modal.appendChild(body);
        ov.appendChild(modal);
        document.body.appendChild(ov);
        buildBodyFn(body, ov, colors);
        setTimeout(function () { if (window.GamepadNav) window.GamepadNav.scanElements(); }, 150);
    }

    function _stStatusBadge(status) {
        var c = status === 'healthy' ? '#4caf50' : status === 'warning' ? '#ff9800' : '#f44336';
        return '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + c + ';margin-right:6px;"></span>';
    }


    function showRepairDepotCachePanel() {
        _stOverlayShell('🔧 Repair Depot Cache', function (body, ov, colors) {
            // Config panel
            var cfg = document.createElement('div');
            cfg.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;';

            function cfgRow(label, id, checked) {
                var d = document.createElement('label');
                d.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;padding:6px 8px;background:rgba(255,255,255,0.03);border-radius:5px;';
                d.innerHTML = '<input type="checkbox" id="lt-repair-' + id + '" ' + (checked ? 'checked' : '') + ' style="accent-color:#66c0f4;width:14px;height:14px;"> ' + label;
                return d;
            }

            cfg.appendChild(cfgRow('Fix .lua syntax', 'fixlua', false));
            cfg.appendChild(cfgRow('Remove orphaned', 'orphans', true));
            cfg.appendChild(cfgRow('Dry run (preview)', 'dryrun', true));

            var agePicker = document.createElement('div');
            agePicker.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:12px;color:#aaa;padding:6px 8px;background:rgba(255,255,255,0.03);border-radius:5px;';
            agePicker.innerHTML = 'Orphan age: <input type="number" id="lt-repair-age" value="30" min="1" max="365" style="width:50px;background:#1a1a1a;border:1px solid #333;border-radius:3px;color:#ccc;padding:2px 4px;font-size:12px;"> days';
            cfg.appendChild(agePicker);

            body.appendChild(cfg);

            // Scope selector
            var scopeDiv = document.createElement('div');
            scopeDiv.style.cssText = 'display:flex;gap:6px;margin-bottom:10px;';
            var scopeAll = document.createElement('button');
            scopeAll.textContent = '🌐 All scripts';
            scopeAll.style.cssText = 'flex:1;padding:6px;background:rgba(102,192,244,0.2);border:1px solid rgba(102,192,244,0.5);border-radius:5px;color:#66c0f4;font-size:12px;cursor:pointer;font-weight:600;';
            scopeDiv.appendChild(scopeAll);
            body.appendChild(scopeDiv);

            // Progress / output area
            var out = document.createElement('div');
            out.style.cssText = 'font-size:12px;line-height:1.8;min-height:120px;padding:10px;background:rgba(0,0,0,0.2);border-radius:6px;border:1px solid ' + colors.borderRgba + ';overflow-y:auto;max-height:320px;';
            out.innerHTML = '<span style="color:#888;">Configure options above, then click a scope button to begin.</span>';
            body.appendChild(out);

            function getOptions() {
                return {
                    fix_lua: document.getElementById('lt-repair-fixlua') ? document.getElementById('lt-repair-fixlua').checked : false,
                    remove_orphans: document.getElementById('lt-repair-orphans') ? document.getElementById('lt-repair-orphans').checked : true,
                    dry_run: document.getElementById('lt-repair-dryrun') ? document.getElementById('lt-repair-dryrun').checked : true,
                    orphan_age_days: parseInt((document.getElementById('lt-repair-age') || {value:30}).value) || 30,
                };
            }

            function renderPhase(name, icon, data) {
                if (!data) return '';
                var html = '<div style="margin-top:8px;"><span style="color:#66c0f4;font-weight:600;">' + icon + ' ' + name + '</span><br>';
                Object.entries(data).forEach(function(kv) {
                    var key = kv[0], val = kv[1];
                    if (typeof val === 'boolean' || (Array.isArray(val) && val.length === 0)) return;
                    if (Array.isArray(val)) val = val.join(', ');
                    var color = (typeof val === 'number' && val > 0) ? '#66c0f4' : '#aaa';
                    html += '  <span style="color:#666;">' + key.replace(/_/g,' ') + ':</span> <span style="color:' + color + ';">' + val + '</span><br>';
                });
                return html + '</div>';
            }

            function runFor(appid) {
                var opts = getOptions();
                var dryRun = opts.dry_run;
                out.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> ' + (dryRun ? 'Scanning (dry run)…' : 'Repairing…');
                Millennium.callServerMethod('luatools', 'RepairDepotCache', {
                    appid: appid || 0,
                    fix_lua: opts.fix_lua,
                    remove_orphans: opts.remove_orphans,
                    dry_run: opts.dry_run,
                    orphan_age_days: opts.orphan_age_days,
                    contentScriptQuery: ''
                }).then(function(res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p || !p.success) {
                        out.innerHTML = '<span style="color:#f44336;">Error: ' + (p && p.error ? p.error : 'Unknown') + '</span>';
                        return;
                    }
                    var t = p.totals || {};
                    var header = dryRun
                        ? '<div style="color:#ffc800;font-weight:700;margin-bottom:8px;">🔍 Dry-run complete — no changes made</div>'
                        : '<div style="color:#4caf50;font-weight:700;margin-bottom:8px;">✅ Repair complete</div>';
                    var summary = '<div style="padding:8px;background:rgba(102,192,244,0.05);border-radius:5px;margin-bottom:6px;">'
                        + 'Manifests scanned: <b>' + (t.manifests_scanned||0) + '</b> &nbsp; '
                        + 'Downloaded: <b style="color:#66c0f4;">' + (t.manifests_downloaded||0) + '</b> &nbsp; '
                        + 'Removed: <b style="color:#ff9800;">' + (t.manifests_removed||0) + '</b> &nbsp; '
                        + 'Junk: <b style="color:#f44336;">' + (t.junk_files_removed||0) + '</b> &nbsp; '
                        + 'Lua lines: <b>' + (t.lua_lines_fixed||0) + '</b>'
                        + '</div>';
                    var phases = '';
                    phases += renderPhase('Scan', '🔍', p.phases.scan);
                    phases += renderPhase('Download', '⬇', p.phases.download);
                    phases += renderPhase('Cleanup', '🗑', p.phases.cleanup);
                    if (p.phases.lua_fix && p.phases.lua_fix.enabled) {
                        phases += renderPhase('Lua fix', '🔧', {
                            files_fixed: p.phases.lua_fix.files_fixed,
                            lines_commented_out: p.phases.lua_fix.lines_commented_out,
                        });
                    }
                    out.innerHTML = header + summary + phases;
                    if (dryRun && (t.manifests_downloaded + t.manifests_removed + t.junk_files_removed) === 0) {
                        out.innerHTML += '<div style="color:#4caf50;margin-top:8px;">✅ Nothing to fix — cache looks healthy!</div>';
                    }
                }).catch(function(err) {
                    out.innerHTML = '<span style="color:#f44336;">Error: ' + err + '</span>';
                });
            }

            scopeAll.onclick = function() { runFor(0); };
        });
    }

    function showSteamToolsHealthScan() {
        _stOverlayShell('🩺 Health Scan', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin" style="font-size:16px;"></i><div style="margin-top:8px;">Scanning all scripts…</div></div>';
            Millennium.callServerMethod('luatools', 'BatchHealthScan', { contentScriptQuery: '' })
                .then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p.success) { body.innerHTML = '<div style="color:#f44336;">Error: ' + (p.error || 'Unknown') + '</div>'; return; }
                    var t = p.totals || {};
                    var summary = '<div style="display:flex;gap:10px;margin-bottom:10px;justify-content:center;">'
                        + '<div style="text-align:center;"><div style="font-size:15px;font-weight:700;color:#4caf50;">' + (t.healthy || 0) + '</div><div style="font-size:11px;opacity:0.7;">Healthy</div></div>'
                        + '<div style="text-align:center;"><div style="font-size:15px;font-weight:700;color:#ff9800;">' + (t.warnings || 0) + '</div><div style="font-size:11px;opacity:0.7;">Warnings</div></div>'
                        + '<div style="text-align:center;"><div style="font-size:15px;font-weight:700;color:#f44336;">' + (t.errors || 0) + '</div><div style="font-size:11px;opacity:0.7;">Errors</div></div>'
                        + '<div style="text-align:center;"><div style="font-size:15px;font-weight:700;color:' + colors.accent + ';">' + (t.total || 0) + '</div><div style="font-size:11px;opacity:0.7;">Total</div></div>'
                        + '</div>';
                    var rows = '';
                    (p.results || []).forEach(function (r) {
                        var issues = (r.issues || []).join(', ') || 'OK';
                        var name = r.gameName || ('AppID ' + r.appid);
                        rows += '<tr><td style="padding:4px 8px;">' + _stStatusBadge(r.status) + '</td>'
                            + '<td style="padding:4px 8px;font-weight:500;">' + r.appid + '</td>'
                            + '<td style="padding:4px 8px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + name + '">' + name + '</td>'
                            + '<td style="padding:4px 8px;font-size:12px;opacity:0.8;">' + issues + '</td></tr>';
                    });
                    body.innerHTML = summary + '<div style="max-height:45vh;overflow-y:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">'
                        + '<thead><tr style="border-bottom:1px solid ' + colors.borderRgba + ';"><th></th><th style="text-align:left;padding:4px 8px;">ID</th><th style="text-align:left;padding:4px 8px;">Game</th><th style="text-align:left;padding:4px 8px;">Issues</th></tr></thead>'
                        + '<tbody>' + rows + '</tbody></table></div>';
                })
                .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function showSteamToolsCacheManager() {
        _stOverlayShell('🧹 Cache Manager', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin" style="font-size:16px;"></i><div style="margin-top:8px;">Calculating cache sizes…</div></div>';
            Millennium.callServerMethod('luatools', 'GetCacheInfo', { contentScriptQuery: '' })
                .then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p.success) { body.innerHTML = '<div style="color:#f44336;">Error: ' + (p.error || 'Unknown') + '</div>'; return; }
                    var cats = p.categories || {};
                    var totalMB = p.totalMB || 0;
                    var html = '<div style="margin-bottom:10px;text-align:center;font-size:15px;font-weight:700;color:' + colors.accent + ';">Total: ' + totalMB + ' MB</div>';
                    html += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px;">';
                    var keys = Object.keys(cats);
                    keys.forEach(function (k) {
                        var c = cats[k];
                        html += '<label style="display:flex;align-items:center;gap:10px;padding:6px 10px;background:rgba(255,255,255,0.04);border-radius:6px;cursor:pointer;">'
                            + '<input type="checkbox" value="' + k + '" checked style="width:18px;height:18px;accent-color:' + colors.accent + ';">'
                            + '<div style="flex:1;"><div style="font-weight:500;">' + c.label + '</div><div style="font-size:11px;opacity:0.6;">' + c.description + '</div></div>'
                            + '<div style="font-weight:600;min-width:70px;text-align:right;">' + (c.sizeMB || 0) + ' MB</div>'
                            + '</label>';
                    });
                    html += '</div>';
                    html += '<div style="text-align:center;"><a href="#" id="lt-st-clean-btn" style="display:inline-block;padding:12px 32px;background:linear-gradient(135deg,rgba(244,67,54,0.2),rgba(244,67,54,0.05));border:1px solid rgba(244,67,54,0.4);border-radius:10px;color:#f44336;font-weight:600;text-decoration:none;cursor:pointer;transition:all 0.3s;">🧹 Clean Selected</a></div>';
                    html += '<div style="font-size:11px;opacity:0.5;margin-top:8px;text-align:center;">Achievements & playtime data are preserved automatically.</div>';
                    body.innerHTML = html;
                    var cleanBtn = body.querySelector('#lt-st-clean-btn');
                    if (cleanBtn) {
                        cleanBtn.onclick = function (e) {
                            e.preventDefault();
                            var checked = [];
                            body.querySelectorAll('input[type=checkbox]:checked').forEach(function (cb) { checked.push(cb.value); });
                            if (!checked.length) { ShowLuaToolsAlert('Cache', 'Select at least one category.'); return; }
                            cleanBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Cleaning…';
                            cleanBtn.style.pointerEvents = 'none';
                            Millennium.callServerMethod('luatools', 'CleanSteamCache', { categories: checked.join(','), contentScriptQuery: '' })
                                .then(function (r2) {
                                    try { ov.remove(); } catch (_) { }
                                    var p2 = typeof r2 === 'string' ? JSON.parse(r2) : r2;
                                    var preserved = p2.preserved ? '\nPreserved: ' + Object.values(p2.preserved).flat().join(', ') : '';
                                    ShowLuaToolsAlert('Cache Cleaned', 'Freed ' + (p2.freedMB || 0) + ' MB' + preserved);
                                })
                                .catch(function () { try { ov.remove(); } catch (_) { } ShowLuaToolsAlert('Cache', 'Cleaning failed.'); });
                        };
                    }
                })
                .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function showSteamToolsBackup() {
        _stOverlayShell('💾 Backup & Restore', function (body, ov, colors) {
            function refreshList() {
                body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</div>';
                Millennium.callServerMethod('luatools', 'ListBackups', { contentScriptQuery: '' })
                    .then(function (res) {
                        var p = typeof res === 'string' ? JSON.parse(res) : res;
                        var html = '<div style="display:flex;gap:8px;margin-bottom:10px;justify-content:center;">'
                            + '<a href="#" id="lt-st-create-backup" style="padding:10px 24px;background:linear-gradient(135deg,rgba(76,175,80,0.2),rgba(76,175,80,0.05));border:1px solid rgba(76,175,80,0.4);border-radius:10px;color:#4caf50;font-weight:600;text-decoration:none;cursor:pointer;">📦 Create Backup</a>'
                            + '</div>';
                        var bks = (p.backups || []);
                        if (bks.length === 0) {
                            html += '<div style="text-align:center;opacity:0.5;padding:10px;">No backups yet.</div>';
                        } else {
                            html += '<div style="max-height:35vh;overflow-y:auto;">';
                            bks.forEach(function (b) {
                                html += '<div style="display:flex;align-items:center;padding:10px 12px;background:rgba(255,255,255,0.04);border-radius:8px;margin-bottom:6px;">'
                                    + '<div style="flex:1;"><div style="font-weight:500;font-size:13px;">' + b.filename + '</div><div style="font-size:11px;opacity:0.6;">' + b.created + ' · ' + b.sizeMB + ' MB</div></div>'
                                    + '<a href="#" class="lt-st-restore-bk" data-fn="' + b.filename + '" style="color:#66c0f4;margin-right:12px;font-size:13px;text-decoration:none;" title="Restore"><i class="fa-solid fa-arrow-rotate-left"></i></a>'
                                    + '<a href="#" class="lt-st-delete-bk" data-fn="' + b.filename + '" style="color:#f44336;font-size:13px;text-decoration:none;" title="Delete"><i class="fa-solid fa-trash"></i></a>'
                                    + '</div>';
                            });
                            html += '</div>';
                        }
                        body.innerHTML = html;
                        var createBtn = body.querySelector('#lt-st-create-backup');
                        if (createBtn) {
                            createBtn.onclick = function (e) {
                                e.preventDefault();
                                createBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating…';
                                createBtn.style.pointerEvents = 'none';
                                Millennium.callServerMethod('luatools', 'CreateBackup', { label: '', contentScriptQuery: '' })
                                    .then(function (r2) {
                                        var p2 = typeof r2 === 'string' ? JSON.parse(r2) : r2;
                                        if (p2.success) { refreshList(); } else { ShowLuaToolsAlert('Backup', p2.error || 'Failed'); refreshList(); }
                                    })
                                    .catch(function () { ShowLuaToolsAlert('Backup', 'Failed to create backup.'); refreshList(); });
                            };
                        }
                        body.querySelectorAll('.lt-st-restore-bk').forEach(function (el) {
                            el.onclick = function (e) {
                                e.preventDefault();
                                var fn = el.getAttribute('data-fn');
                                showLuaToolsConfirm('Restore', 'Restore backup ' + fn + '?', function () {
                                    Millennium.callServerMethod('luatools', 'RestoreBackup', { filename: fn, contentScriptQuery: '' })
                                        .then(function (r3) { var p3 = typeof r3 === 'string' ? JSON.parse(r3) : r3; ShowLuaToolsAlert('Restore', p3.success ? 'Restored ' + (p3.restoredFiles || 0) + ' files.' : (p3.error || 'Failed')); })
                                        .catch(function () { ShowLuaToolsAlert('Restore', 'Failed.'); });
                                }, function () { });
                            };
                        });
                        body.querySelectorAll('.lt-st-delete-bk').forEach(function (el) {
                            el.onclick = function (e) {
                                e.preventDefault();
                                var fn = el.getAttribute('data-fn');
                                Millennium.callServerMethod('luatools', 'DeleteBackup', { filename: fn, contentScriptQuery: '' })
                                    .then(function () { refreshList(); })
                                    .catch(function () { refreshList(); });
                            };
                        });
                    })
                    .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
            }
            refreshList();
        });
    }

    function showSteamToolsGamePanel(appid) {
        _stOverlayShell('🎮 Game Tools — AppID ' + appid, function (body, ov, colors) {
            function makeBtn(label, icon, onClick) {
                var a = document.createElement('a');
                a.href = '#'; a.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(255,255,255,0.04);border:1px solid ' + colors.borderRgba + ';border-radius:8px;color:${colors||c}.text;font-size:13px;text-decoration:none;cursor:pointer;transition:all 0.2s;';
                a.innerHTML = '<i class="fa-solid ' + icon + '" style="width:20px;text-align:center;color:' + colors.accent + ';"></i><span>' + label + '</span>';
                a.onmouseover = function () { this.style.background = 'rgba(255,255,255,0.08)'; this.style.borderColor = colors.accent; };
                a.onmouseout = function () { this.style.background = 'rgba(255,255,255,0.04)'; this.style.borderColor = colors.borderRgba; };
                a.onclick = function (e) { e.preventDefault(); onClick(a); };
                body.appendChild(a);
                return a;
            }
            function resultArea() {
                var d = body.querySelector('#lt-gt-result');
                if (!d) { d = document.createElement('div'); d.id = 'lt-gt-result'; d.style.cssText = 'margin-top:8px;padding:10px;background:rgba(0,0,0,0.3);border-radius:8px;font-size:13px;line-height:1.5;max-height:40vh;overflow-y:auto;white-space:pre-wrap;'; body.appendChild(d); }
                return d;
            }
            function callAndShow(method, params, formatFn) {
                var r = resultArea(); r.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Working…';
                Millennium.callServerMethod('luatools', method, params)
                    .then(function (res) { var p = typeof res === 'string' ? JSON.parse(res) : res; r.innerHTML = formatFn(p); })
                    .catch(function (err) { r.innerHTML = '<span style="color:#f44336;">Error: ' + err + '</span>'; });
            }

            makeBtn('Diagnose & Export Report', 'fa-file-medical', function () {
                callAndShow('ExportDiagnosticReport', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var escaped = (p.text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    setTimeout(function () {
                        var el = document.getElementById('lt-gt-report-text');
                        if (el) el.onclick = function () {
                            navigator.clipboard.writeText(p.text || '').catch(function(){});
                            el.style.opacity = '0.5';
                            setTimeout(function () { if (el) el.style.opacity = '1'; }, 500);
                        };
                    }, 50);
                    return '<div style="margin-bottom:8px;font-weight:600;color:' + colors.accent + ';">Diagnostic Report (click to copy)</div>'
                        + '<div id="lt-gt-report-text" style="cursor:pointer;font-family:monospace;font-size:12px;" title="Click to copy">' + escaped + '</div>';
                });
            });

            makeBtn('Audit Content (Depots/DLC/Workshop)', 'fa-search', function () {
                callAndShow('AuditLuaContent', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var ws = p.workshop || {};
                    var dlc = p.dlc || {};
                    return '<b>Workshop:</b> ' + (ws.label || ws.status || '?')
                        + '\n<b>Depots:</b> ' + (p.depotCount || 0) + ' referenced'
                        + '\n<b>DLC included:</b> ' + (dlc.included || []).length + '/' + (dlc.total || 0)
                        + ((dlc.missing || []).length ? '\n<b style="color:#f44336;">DLC missing:</b> ' + (dlc.missing || []).join(', ') : '');
                });
            });

            makeBtn('Validate Lua Syntax', 'fa-spell-check', function () {
                callAndShow('ValidateLuaSyntax', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var res = (p.results || [])[0] || {};
                    if (res.valid) return '<span style="color:#4caf50;">✅ Syntax is valid (' + (res.lineCount || 0) + ' lines)</span>';
                    var lines = (res.badLines || []).map(function (b) { return 'Line ' + b.line + ': ' + b.reason; }).join('\n');
                    return '<span style="color:#f44336;">❌ ' + (res.badLines || []).length + ' error(s):</span>\n' + lines;
                });
            });

            makeBtn('Repair Depot Cache', 'fa-wrench', function () {
                var r = resultArea();
                r.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running repair scan…';

                // Phase display helper
                function phaseIcon(ok) { return ok ? '✅' : '⚠️'; }
                function fmt(n) { return (n === 0 ? '<span style="color:#888;">0</span>' : '<span style="color:#66c0f4;font-weight:700;">' + n + '</span>'); }

                Millennium.callServerMethod('luatools', 'RepairDepotCache', {
                    appid: appid, fix_lua: false, remove_orphans: true,
                    orphan_age_days: 30, dry_run: true, contentScriptQuery: ''
                }).then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p || !p.success) {
                        r.innerHTML = '<span style="color:#f44336;">' + (p && p.error ? p.error : 'Failed') + '</span>';
                        return;
                    }
                    var sc = p.phases.scan || {}, dl = p.phases.download || {}, cl = p.phases.cleanup || {};

                    // Show dry-run summary with action buttons
                    var html = '<div style="margin-bottom:8px;padding:8px;background:rgba(255,200,0,0.06);border:1px solid rgba(255,200,0,0.25);border-radius:6px;font-size:11px;color:#ffc800;">';
                    html += '<i class="fa-solid fa-eye" style="margin-right:5px;"></i><strong>Dry-run preview — no changes made yet</strong></div>';

                    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px;">';
                    html += '<div style="padding:8px;background:rgba(255,255,255,0.03);border-radius:5px;">';
                    html += '<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Scan</div>';
                    html += '<div style="font-size:12px;">Total: ' + fmt(sc.total_manifests || 0) + '</div>';
                    html += '<div style="font-size:12px;">Corrupt: ' + fmt(sc.corrupt || 0) + '</div>';
                    html += '<div style="font-size:12px;">Zero-byte: ' + fmt(sc.zero_byte || 0) + '</div>';
                    html += '<div style="font-size:12px;">Orphaned: ' + fmt(sc.orphaned_old_enough || 0) + '</div>';
                    html += '</div>';
                    html += '<div style="padding:8px;background:rgba(255,255,255,0.03);border-radius:5px;">';
                    html += '<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Would do</div>';
                    html += '<div style="font-size:12px;">Download: ' + fmt(dl.needed || 0) + '</div>';
                    html += '<div style="font-size:12px;">Remove corrupt: ' + fmt(sc.corrupt || 0) + '</div>';
                    html += '<div style="font-size:12px;">Remove zero: ' + fmt(sc.zero_byte || 0) + '</div>';
                    html += '<div style="font-size:12px;">Remove orphans: ' + fmt(sc.orphaned_old_enough || 0) + '</div>';
                    html += '</div></div>';

                    var needsWork = (sc.corrupt || 0) + (sc.zero_byte || 0) + (dl.needed || 0) + (sc.orphaned_old_enough || 0);
                    if (needsWork === 0) {
                        html += '<div style="color:#4caf50;font-size:12px;"><i class="fa-solid fa-check-circle" style="margin-right:5px;"></i>Depot cache looks healthy -- nothing to repair!</div>';
                        r.innerHTML = html;
                        return;
                    }

                    // Action buttons row
                    html += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">';
                    html += '<button id="lt-repair-run" style="flex:1;padding:7px;background:rgba(102,192,244,0.15);border:1px solid rgba(102,192,244,0.4);border-radius:5px;color:#66c0f4;font-size:12px;font-weight:600;cursor:pointer;">⚡ Run Repair</button>';
                    html += '<button id="lt-repair-fixlua" style="flex:1;padding:7px;background:rgba(255,150,0,0.12);border:1px solid rgba(255,150,0,0.3);border-radius:5px;color:#ff9800;font-size:12px;cursor:pointer;">🔧 Repair + Fix .lua</button>';
                    html += '</div>';
                    r.innerHTML = html;

                    function runRepair(fixLua) {
                        r.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Repairing…';
                        Millennium.callServerMethod('luatools', 'RepairDepotCache', {
                            appid: appid, fix_lua: fixLua, remove_orphans: true,
                            orphan_age_days: 30, dry_run: false, contentScriptQuery: ''
                        }).then(function (res2) {
                            var p2 = typeof res2 === 'string' ? JSON.parse(res2) : res2;
                            if (!p2 || !p2.success) {
                                r.innerHTML = '<span style="color:#f44336;">' + (p2 && p2.error ? p2.error : 'Failed') + '</span>';
                                return;
                            }
                            var t = p2.totals || {}, dl2 = p2.phases.download || {}, cl2 = p2.phases.cleanup || {}, lf = p2.phases.lua_fix || {};
                            var out = '<div style="font-size:13px;font-weight:700;color:#4caf50;margin-bottom:8px;"><i class="fa-solid fa-check-circle" style="margin-right:6px;"></i>Repair complete</div>';
                            out += '<div style="font-size:12px;line-height:2;">';
                            out += 'Downloaded: ' + fmt(t.manifests_downloaded || 0) + ' manifest(s)<br>';
                            out += 'Removed (corrupt): ' + fmt(cl2.removed_corrupt || 0) + '<br>';
                            out += 'Removed (zero-byte): ' + fmt(cl2.removed_zero_byte || 0) + '<br>';
                            out += 'Removed (orphaned): ' + fmt(cl2.removed_orphaned || 0) + '<br>';
                            out += 'Stplug junk removed: ' + fmt(cl2.removed_stplug_junk || 0);
                            if (lf.enabled) out += '<br>Lua lines fixed: ' + fmt(lf.lines_commented_out || 0);
                            if ((dl2.failed || 0) > 0) out += '<br><span style="color:#ff9800;">Download failures: ' + dl2.failed + '</span>';
                            if ((t.errors || 0) > 0) out += '<br><span style="color:#f44336;">Errors: ' + t.errors + '</span>';
                            out += '</div>';
                            r.innerHTML = out;
                        }).catch(function(err) {
                            r.innerHTML = '<span style="color:#f44336;">Error: ' + err + '</span>';
                        });
                    }

                    setTimeout(function() {
                        var btn = r.querySelector('#lt-repair-run');
                        var btnLua = r.querySelector('#lt-repair-fixlua');
                        if (btn) btn.onclick = function() { runRepair(false); };
                        if (btnLua) btnLua.onclick = function() {
                            if (window.confirm('This will comment-out broken lines in .lua files. Proceed?')) {
                                runRepair(true);
                            }
                        };
                    }, 50);
                }).catch(function(err) {
                    r.innerHTML = '<span style="color:#f44336;">Error: ' + err + '</span>';
                });
            });

            makeBtn('Update Manifests', 'fa-download', function () {
                callAndShow('UpdateManifests', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var s = p.summary || {};
                    return '<b>Downloaded:</b> ' + (s.downloaded || 0) + '  <b>Skipped:</b> ' + (s.skipped || 0) + '  <b>Failed:</b> ' + (s.failed || 0)
                        + '\n<b>Total depots:</b> ' + (s.total || 0);
                });
            });

            makeBtn('Clean Lua (Strip Branding)', 'fa-broom', function () {
                callAndShow('CleanLuaContent', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    return p.removedLines === 0 ? '✅ Already clean' : '🧹 Removed ' + p.removedLines + ' branding line(s)';
                });
            });

            makeBtn('Toggle Enable/Disable', 'fa-toggle-on', function (btn) {
                Millennium.callServerMethod('luatools', 'HasLuaToolsForApp', { appid: appid, contentScriptQuery: '' })
                    .then(function (res) {
                        var p = typeof res === 'string' ? JSON.parse(res) : res;
                        if (!p.exists) { resultArea().innerHTML = '<span style="color:#ff9800;">No lua file for this appid.</span>'; return; }
                        // Check if disabled
                        Millennium.callServerMethod('luatools', 'ToggleLuaScript', { appid: appid, enable: false, contentScriptQuery: '' })
                            .then(function (r2) {
                                var p2 = typeof r2 === 'string' ? JSON.parse(r2) : r2;
                                if (p2.state === 'disabled') {
                                    resultArea().innerHTML = '<span style="color:#ff9800;">🔴 Disabled. Click again to re-enable.</span>';
                                    btn.querySelector('span').textContent = 'Toggle Enable/Disable (currently: OFF)';
                                    btn.onclick = function (e) { e.preventDefault();
                                        Millennium.callServerMethod('luatools', 'ToggleLuaScript', { appid: appid, enable: true, contentScriptQuery: '' })
                                            .then(function () { resultArea().innerHTML = '<span style="color:#4caf50;">🟢 Re-enabled.</span>'; btn.querySelector('span').textContent = 'Toggle Enable/Disable'; });
                                    };
                                } else if (p2.state === 'already_disabled') {
                                    Millennium.callServerMethod('luatools', 'ToggleLuaScript', { appid: appid, enable: true, contentScriptQuery: '' })
                                        .then(function () { resultArea().innerHTML = '<span style="color:#4caf50;">🟢 Re-enabled.</span>'; });
                                }
                            });
                    });
            });

            makeBtn('Extract Keys & Manifests', 'fa-key', function () {
                callAndShow('ExtractLuaKeys', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var s = p.summary || {};
                    return '<b>Depot keys:</b> ' + (s.totalDepots || 0)
                        + '\n<b>Manifest IDs:</b> ' + (s.totalManifests || 0)
                        + '\n<b>Tokens:</b> ' + (s.totalTokens || 0)
                        + '\n<b>Referenced AppIDs:</b> ' + (s.totalReferenced || 0);
                });
            });

            makeBtn('Check Available Fixes', 'fa-wrench', function () {
                callAndShow('CheckForFixes', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var gf = p.genericFix || {};
                    var of2 = p.onlineFix || {};
                    var html = '<b>Game:</b> ' + (p.gameName || 'Unknown') + '\n\n';
                    html += gf.available
                        ? '<span style="color:#4caf50;">✅ Generic Fix available</span>'
                        : '<span style="opacity:0.5;">Generic Fix: not available</span>';
                    html += '\n';
                    html += of2.available
                        ? '<span style="color:#4caf50;">✅ Online Fix available</span>'
                        : '<span style="opacity:0.5;">Online Fix: not available</span>';
                    if (!gf.available && !of2.available) {
                        html += '\n\n<span style="opacity:0.6;">No fixes available for this game. Try the Fixes Menu from the main LuaTools menu.</span>';
                    }
                    return html;
                });
            });

            makeBtn('Security Scan', 'fa-shield-halved', function () {
                callAndShow('DiagnoseApp', { appid: appid, contentScriptQuery: '' }, function (p) {
                    if (!p.success) return '<span style="color:#f44336;">' + (p.error || 'Failed') + '</span>';
                    var lines = [];

                    // Goldberg emulator detection
                    var gb = p.goldberg || {};
                    if (gb.detected) {
                        lines.push('<span style="color:#ff9800;">⚠️ Goldberg emulator detected:</span>');
                        (gb.files || []).slice(0, 5).forEach(function (f) { lines.push('  • ' + f); });
                        if ((gb.files || []).length > 5) lines.push('  … and ' + ((gb.files || []).length - 5) + ' more');
                    } else {
                        lines.push('<span style="color:#4caf50;">✅ No Goldberg files detected</span>');
                    }

                    lines.push('');

                    // Conflicting files (other cracks/emulators)
                    var cf = p.conflictingFiles || [];
                    if (cf.length > 0) {
                        lines.push('<span style="color:#f44336;">❌ Conflicting files found (' + cf.length + '):</span>');
                        cf.slice(0, 6).forEach(function (f) { lines.push('  • ' + f); });
                        if (cf.length > 6) lines.push('  … and ' + (cf.length - 6) + ' more');
                        lines.push('<span style="color:#ff9800;font-size:11px;">These files conflict with SteamTools activation — remove them.</span>');
                    } else {
                        lines.push('<span style="color:#4caf50;">✅ No conflicting crack files found</span>');
                    }

                    lines.push('');

                    // Auto-update status
                    if (p.updatesDisabled) {
                        lines.push('<span style="color:#4caf50;">✅ Auto-updates disabled (recommended for cracked games)</span>');
                    } else {
                        lines.push('<span style="color:#ff9800;">⚠️ Auto-updates enabled — Steam may overwrite files</span>');
                    }

                    return lines.join('\n');
                });
            });

            makeBtn('Achievements & Schema', 'fa-trophy', function () {
                var r = resultArea();
                r.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching achievement info…';

                Millennium.callServerMethod('luatools', 'GetAchievementInfo', {
                    appid: appid, contentScriptQuery: ''
                }).then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p || !p.success) {
                        r.innerHTML = '<span style="color:#f44336;">' + (p && p.error ? p.error : 'Failed') + '</span>';
                        return;
                    }

                    var html = '';

                    // Achievement count badge
                    if (p.apiAvailable) {
                        var countColor = p.count > 0 ? '#66c0f4' : '#888';
                        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">';
                        html += '<i class="fa-solid fa-trophy" style="color:#ffd700;font-size:18px;"></i>';
                        html += '<span style="font-size:16px;font-weight:700;color:' + countColor + ';">' + p.count + ' achievements</span>';
                        if (p.truncated) html += '<span style="color:#888;font-size:11px;">(+' + p.truncated + ' more)</span>';
                        html += '</div>';
                    } else {
                        html += '<div style="color:#888;margin-bottom:8px;font-size:12px;">';
                        html += '<i class="fa-solid fa-info-circle" style="margin-right:5px;"></i>';
                        html += (p.apiNote || 'Achievement info unavailable') + '</div>';
                    }

                    // Schema file status per account
                    if (p.accounts && p.accounts.length > 0) {
                        html += '<div style="font-weight:600;font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Schema Files (appcache/stats)</div>';
                        p.accounts.forEach(function (acc) {
                            var schemaIcon = acc.schemaExists
                                ? '<i class="fa-solid fa-check" style="color:#4caf50;"></i>'
                                : '<i class="fa-solid fa-xmark" style="color:#888;"></i>';
                            var statsIcon = acc.userStatsExists
                                ? '<i class="fa-solid fa-check" style="color:#4caf50;"></i>'
                                : '<i class="fa-solid fa-xmark" style="color:#888;"></i>';
                            var recentBadge = acc.mostRecent ? ' <span style="background:#1b6fa8;border-radius:3px;padding:1px 5px;font-size:10px;">active</span>' : '';
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(255,255,255,0.03);border-radius:5px;margin-bottom:3px;">';
                            html += '<span style="font-size:12px;">' + (acc.personaName || acc.username || 'Unknown') + recentBadge + '</span>';
                            html += '<span style="display:flex;gap:12px;font-size:11px;color:#aaa;">';
                            html += '<span>' + schemaIcon + ' Schema</span>';
                            html += '<span>' + statsIcon + ' Stats</span>';
                            html += '</span>';
                            html += '</div>';
                        });

                        // Seed button if any account is missing stats file
                        var needsSeed = p.accounts.some(function (a) { return !a.userStatsExists; });
                        if (needsSeed) {
                            html += '<div style="margin-top:8px;padding:8px;background:rgba(255,200,0,0.06);border:1px solid rgba(255,200,0,0.2);border-radius:5px;font-size:11px;">';
                            html += '<i class="fa-solid fa-seedling" style="color:#ffc800;margin-right:5px;"></i>';
                            html += '<strong style="color:#ffc800;">Empty stats files missing.</strong> ';
                            html += 'Steam needs these to track achievements. ';
                            html += '<a href="#" id="lt-seed-btn" style="color:#66c0f4;text-decoration:none;">Seed now</a>';
                            html += '</div>';
                        }

                        // Schema note
                        var schemasMissing = p.accounts.some(function (a) { return !a.schemaExists; });
                        if (schemasMissing) {
                            html += '<div style="margin-top:6px;font-size:11px;color:#aaa;">';
                            html += '<i class="fa-solid fa-circle-info" style="margin-right:5px;"></i>';
                            html += 'Schema binary (.bin) will be downloaded by Steam automatically on first game launch.';
                            html += '</div>';
                        }
                    } else {
                        html += '<div style="color:#888;font-size:11px;margin-top:6px;">' + (p.accountNote || 'No accounts found in loginusers.vdf') + '</div>';
                    }

                    // Achievement list preview
                    if (p.achievements && p.achievements.length > 0) {
                        html += '<div style="margin-top:10px;">';
                        html += '<div style="font-weight:600;font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Preview</div>';
                        var listEl = '<div style="max-height:120px;overflow-y:auto;display:flex;flex-direction:column;gap:3px;">';
                        p.achievements.slice(0, 15).forEach(function (a) {
                            var hiddenTag = a.hidden ? ' <span style="color:#888;font-size:10px;">[hidden]</span>' : '';
                            listEl += '<div style="font-size:11px;padding:3px 6px;background:rgba(255,255,255,0.03);border-radius:3px;">';
                            listEl += '<span style="color:#ccc;">' + (a.displayName || a.name) + '</span>' + hiddenTag;
                            if (a.description) listEl += '<div style="color:#888;font-size:10px;">' + a.description.substring(0, 60) + (a.description.length > 60 ? '…' : '') + '</div>';
                            listEl += '</div>';
                        });
                        if (p.achievements.length === 15 && (p.count > 15 || p.truncated)) {
                            listEl += '<div style="font-size:10px;color:#666;padding:3px 6px;">… and ' + (p.count - 15) + ' more</div>';
                        }
                        listEl += '</div>';
                        html += listEl + '</div>';
                    }

                    r.innerHTML = html;

                    // Wire up seed button
                    var seedBtn = r.querySelector('#lt-seed-btn');
                    if (seedBtn) {
                        seedBtn.onclick = function (e) {
                            e.preventDefault();
                            seedBtn.textContent = 'Seeding…';
                            Millennium.callServerMethod('luatools', 'SeedAchievementFiles', {
                                appid: appid, accountId32: 0, contentScriptQuery: ''
                            }).then(function (res2) {
                                var p2 = typeof res2 === 'string' ? JSON.parse(res2) : res2;
                                if (p2 && p2.success) {
                                    var seededCount = (p2.seeded || []).length;
                                    seedBtn.textContent = '✅ Seeded ' + seededCount + ' file(s)';
                                    seedBtn.style.color = '#4caf50';
                                    // Refresh display
                                    setTimeout(function () {
                                        seedBtn.closest('a') && seedBtn.closest('a').click && seedBtn.closest('a').click();
                                    }, 1000);
                                } else {
                                    seedBtn.textContent = '❌ ' + (p2 && p2.error ? p2.error : 'Failed');
                                    seedBtn.style.color = '#f44336';
                                }
                            }).catch(function () {
                                seedBtn.textContent = '❌ Error';
                                seedBtn.style.color = '#f44336';
                            });
                        };
                    }
                }).catch(function (err) {
                    r.innerHTML = '<span style="color:#f44336;">Error: ' + err + '</span>';
                });
            });

            // ── Quick Actions (from Kite quick-actions concept) ──────────
            var qaSep = document.createElement('div');
            qaSep.style.cssText = 'margin:8px 0 4px;font-size:10px;color:' + colors.accent + ';text-transform:uppercase;letter-spacing:1px;text-align:center;font-weight:600;';
            qaSep.textContent = 'Quick Actions';
            body.appendChild(qaSep);

            var qaRow = document.createElement('div');
            qaRow.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;';

            var qaButtons = [
                { label: '📋 Copy AppID', fn: function () { navigator.clipboard.writeText(String(appid)).then(function () { showLuaToolsToast('AppID ' + appid + ' copied', 2000, 'success'); }); } },
                { label: '🔍 SteamDB', fn: function () { try { Millennium.callServerMethod('luatools', 'OpenExternalUrl', { url: 'https://steamdb.info/app/' + appid + '/', contentScriptQuery: '' }); } catch (_) { } } },
                { label: '📖 PCGamingWiki', fn: function () { try { Millennium.callServerMethod('luatools', 'OpenExternalUrl', { url: 'https://www.pcgamingwiki.com/api/appid.php?appid=' + appid, contentScriptQuery: '' }); } catch (_) { } } },
                { label: '🐧 ProtonDB', fn: function () { try { Millennium.callServerMethod('luatools', 'OpenExternalUrl', { url: 'https://www.protondb.com/app/' + appid, contentScriptQuery: '' }); } catch (_) { } } },
                { label: '📂 Open Folder', fn: function () { Millennium.callServerMethod('luatools', 'GetGameInstallPath', { appid: appid, contentScriptQuery: '' }).then(function (r) { var p = typeof r === 'string' ? JSON.parse(r) : r; if (p.path) Millennium.callServerMethod('luatools', 'OpenGameFolder', { path: p.path, contentScriptQuery: '' }); else showLuaToolsToast('Install path not found', 2000, 'error'); }); } },
            ];

            qaButtons.forEach(function (qa) {
                var btn = document.createElement('button');
                btn.textContent = qa.label;
                btn.style.cssText = 'flex:1;min-width:90px;padding:5px 8px;background:rgba(255,255,255,0.04);border:1px solid ' + colors.borderRgba + ';border-radius:5px;color:#ccc;font-size:11px;cursor:pointer;transition:all 0.2s;';
                btn.onmouseover = function () { this.style.background = 'rgba(' + colors.rgbString + ',0.12)'; this.style.borderColor = colors.accent; this.style.color = '#fff'; };
                btn.onmouseout = function () { this.style.background = 'rgba(255,255,255,0.04)'; this.style.borderColor = colors.borderRgba; this.style.color = '#ccc'; };
                btn.onclick = qa.fn;
                qaRow.appendChild(btn);
            });
            body.appendChild(qaRow);

            // Fire mod hook
            try { LuaToolsMods.fireHook('onGameDetected', { appid: appid, overlay: ov }); } catch (_) { }
        });
    }

    function showSteamToolsFolderStats() {
        _stOverlayShell('📊 Steam Folder Stats', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin" style="font-size:16px;"></i><div style="margin-top:8px;">Calculating folder sizes…</div></div>';
            Millennium.callServerMethod('luatools', 'GetSteamFolderStats', { contentScriptQuery: '' })
                .then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p.success) { body.innerHTML = '<div style="color:#f44336;">Error: ' + (p.error || 'Unknown') + '</div>'; return; }
                    var folders = p.folders || {};
                    var html = '<div style="margin-bottom:10px;text-align:center;">'
                        + '<div style="font-size:16px;font-weight:700;color:' + colors.accent + ';">' + (p.totalGB || 0) + ' GB</div>'
                        + '<div style="font-size:12px;opacity:0.6;">Total Steam footprint</div>'
                        + '<div style="font-size:11px;opacity:0.4;margin-top:4px;">' + (p.steamPath || '') + '</div>'
                        + '</div>';
                    html += '<div style="display:flex;flex-direction:column;gap:6px;">';
                    var maxMB = 1;
                    Object.keys(folders).forEach(function (k) { if ((folders[k].sizeMB || 0) > maxMB) maxMB = folders[k].sizeMB; });
                    Object.keys(folders).sort(function (a, b) { return (folders[b].sizeMB || 0) - (folders[a].sizeMB || 0); }).forEach(function (k) {
                        var f = folders[k];
                        var pct = maxMB > 0 ? Math.round(((f.sizeMB || 0) / maxMB) * 100) : 0;
                        var sizeLabel = (f.sizeGB || 0) >= 1 ? (f.sizeGB + ' GB') : ((f.sizeMB || 0) + ' MB');
                        var existsTag = f.exists === false ? ' <span style="color:#f44336;font-size:10px;">(missing)</span>' : '';
                        html += '<div style="padding:6px 10px;background:rgba(255,255,255,0.04);border-radius:6px;">'
                            + '<div style="display:flex;justify-content:space-between;margin-bottom:4px;"><span style="font-weight:500;font-size:13px;">' + k + existsTag + '</span><span style="font-weight:600;font-size:13px;">' + sizeLabel + '</span></div>'
                            + '<div style="height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden;"><div style="height:100%;width:' + pct + '%;background:' + colors.accent + ';border-radius:3px;transition:width 0.3s;"></div></div>'
                            + '</div>';
                    });
                    html += '</div>';
                    body.innerHTML = html;
                })
                .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function showSteamToolsDashboard() {
        _stOverlayShell('📊 Quick Dashboard', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin" style="font-size:16px;"></i><div style="margin-top:8px;">Gathering stats…</div></div>';
            Promise.all([
                Millennium.callServerMethod('luatools', 'GetQuickDashboard', { contentScriptQuery: '' }),
                Millennium.callServerMethod('luatools', 'GetSteamProcessInfo', { contentScriptQuery: '' })
            ]).then(function (results) {
                var d = typeof results[0] === 'string' ? JSON.parse(results[0]) : results[0];
                var pi = typeof results[1] === 'string' ? JSON.parse(results[1]) : results[1];
                function card(icon, label, value, color) {
                    return '<div style="text-align:center;padding:10px 6px;background:rgba(255,255,255,0.04);border-radius:8px;min-width:80px;">'
                        + '<i class="fa-solid ' + icon + '" style="font-size:14px;color:' + (color || colors.accent) + ';margin-bottom:4px;display:block;"></i>'
                        + '<div style="font-size:14px;font-weight:700;color:' + colors.text + ';">' + value + '</div>'
                        + '<div style="font-size:10px;opacity:0.6;margin-top:2px;">' + label + '</div></div>';
                }
                var steamColor = (pi.running ? '#4caf50' : '#f44336');
                var html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;">'
                    + card('fa-file-code', 'Scripts', d.luaFiles || 0)
                    + card('fa-eye-slash', 'Disabled', d.disabledFiles || 0, '#ff9800')
                    + card('fa-file-lines', 'Manifests', d.manifestFiles || 0)
                    + card('fa-hard-drive', 'Manifest Size', (d.manifestSizeMB || 0) + ' MB')
                    + card('fa-broom', 'Cleanable', (d.cacheSizeMB || 0) + ' MB', '#ff9800')
                    + card('fa-box-archive', 'Backups', d.backupCount || 0)
                    + '</div>';
                html += '<div style="display:flex;align-items:center;justify-content:center;gap:6px;padding:6px;background:rgba(255,255,255,0.04);border-radius:8px;">'
                    + '<div style="width:10px;height:10px;border-radius:50%;background:' + steamColor + ';"></div>'
                    + '<span style="font-weight:500;font-size:12px;">Steam: ' + (pi.running ? 'Running' : 'Not Running') + '</span>';
                if (pi.running && pi.totalMemoryMB) {
                    html += '<span style="opacity:0.5;font-size:11px;">(' + pi.processes.length + ' proc, ' + pi.totalMemoryMB + ' MB)</span>';
                }
                html += '</div>';
                body.innerHTML = html;
            }).catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function showSteamToolsConflicts() {
        _stOverlayShell('⚠️ Depot Conflict Check', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin" style="font-size:16px;"></i><div style="margin-top:8px;">Scanning for conflicts…</div></div>';
            Millennium.callServerMethod('luatools', 'DetectDepotConflicts', { contentScriptQuery: '' })
                .then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p.success) { body.innerHTML = '<div style="color:#f44336;">Error: ' + (p.error || 'Unknown') + '</div>'; return; }
                    var html = '<div style="text-align:center;margin-bottom:16px;">'
                        + '<div style="font-size:14px;opacity:0.7;">Scanned ' + (p.filesScanned || 0) + ' files</div>';
                    if (p.conflictsFound === 0) {
                        html += '<div style="font-size:16px;font-weight:700;color:#4caf50;margin-top:8px;">✅ No conflicts found</div>';
                    } else {
                        html += '<div style="font-size:16px;font-weight:700;color:#f44336;margin-top:8px;">⚠️ ' + p.conflictsFound + ' conflict(s) found</div>';
                    }
                    html += '</div>';
                    if (p.conflicts && p.conflicts.length > 0) {
                        html += '<div style="max-height:40vh;overflow-y:auto;">';
                        p.conflicts.forEach(function (c) {
                            html += '<div style="padding:10px 12px;background:rgba(244,67,54,0.08);border:1px solid rgba(244,67,54,0.3);border-radius:8px;margin-bottom:6px;">'
                                + '<div style="font-weight:600;">Depot ' + c.depotId + '</div>'
                                + '<div style="font-size:12px;opacity:0.7;">Referenced by AppIDs: ' + (c.referencedBy || []).join(', ') + '</div>'
                                + '</div>';
                        });
                        html += '</div>';
                    }
                    body.innerHTML = html;
                })
                .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function showCustomApisManager() {
        _stOverlayShell('🔌 Custom API Sources', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</div>';
            Millennium.callServerMethod('luatools', 'GetCustomApis', { contentScriptQuery: '' })
                .then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    var apis = (p.apis || []);
                    function render() {
                        var html = '<div style="font-size:12px;opacity:0.6;margin-bottom:12px;">Add custom manifest API endpoints. URL must contain &lt;appid&gt; placeholder.</div>';
                        html += '<div id="lt-ca-list" style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px;">';
                        apis.forEach(function (a, i) {
                            var borderColor = a.enabled ? 'rgba(76,175,80,0.5)' : colors.borderRgba;
                            html += '<div class="lt-ca-item" data-idx="' + i + '" style="padding:12px;background:rgba(255,255,255,0.04);border:1px solid ' + borderColor + ';border-radius:8px;">'
                                + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                                + '<input type="text" class="lt-ca-name" value="' + (a.name || '').replace(/"/g, '&quot;') + '" placeholder="Name" style="background:transparent;border:none;color:' + colors.text + ';font-weight:600;font-size:14px;width:60%;outline:none;">'
                                + '<div style="display:flex;gap:8px;align-items:center;">'
                                + '<label style="font-size:11px;cursor:pointer;color:' + (a.enabled ? '#4caf50' : '#999') + ';"><input type="checkbox" class="lt-ca-enabled" ' + (a.enabled ? 'checked' : '') + ' style="accent-color:' + colors.accent + ';"> ON</label>'
                                + '<a href="#" class="lt-ca-del" style="color:#f44336;font-size:14px;text-decoration:none;" title="Remove"><i class="fa-solid fa-trash"></i></a>'
                                + '</div></div>'
                                + '<input type="text" class="lt-ca-url" value="' + (a.url || '').replace(/"/g, '&quot;') + '" placeholder="https://api.example.com/manifest/<appid>" style="width:100%;padding:6px 8px;background:rgba(0,0,0,0.3);border:1px solid ' + colors.borderRgba + ';color:' + colors.text + ';border-radius:4px;font-size:12px;font-family:monospace;box-sizing:border-box;margin-bottom:6px;">'
                                + '<input type="text" class="lt-ca-key" value="' + (a.api_key || '').replace(/"/g, '&quot;') + '" placeholder="API Key (optional)" style="width:100%;padding:6px 8px;background:rgba(0,0,0,0.3);border:1px solid ' + colors.borderRgba + ';color:' + colors.text + ';border-radius:4px;font-size:12px;box-sizing:border-box;">'
                                + '</div>';
                        });
                        html += '</div>';
                        html += '<div style="display:flex;gap:10px;justify-content:center;">'
                            + '<a href="#" id="lt-ca-add" style="padding:10px 20px;background:rgba(76,175,80,0.15);border:1px solid rgba(76,175,80,0.4);border-radius:8px;color:#4caf50;font-weight:500;text-decoration:none;cursor:pointer;">+ Add API</a>'
                            + '<a href="#" id="lt-ca-save" style="padding:10px 20px;background:rgba(102,192,244,0.15);border:1px solid rgba(102,192,244,0.4);border-radius:8px;color:#66c0f4;font-weight:600;text-decoration:none;cursor:pointer;">Save</a>'
                            + '</div>';
                        body.innerHTML = html;

                        // Bind delete buttons
                        body.querySelectorAll('.lt-ca-del').forEach(function (el) {
                            el.onclick = function (e) {
                                e.preventDefault();
                                var item = el.closest('.lt-ca-item');
                                var idx = parseInt(item.getAttribute('data-idx'));
                                apis.splice(idx, 1);
                                render();
                            };
                        });
                        // Bind add button
                        var addBtn = body.querySelector('#lt-ca-add');
                        if (addBtn) addBtn.onclick = function (e) {
                            e.preventDefault();
                            apis.push({ name: '', url: '', api_key: '', enabled: true });
                            render();
                        };
                        // Bind save button
                        var saveBtn = body.querySelector('#lt-ca-save');
                        if (saveBtn) saveBtn.onclick = function (e) {
                            e.preventDefault();
                            // Collect from DOM
                            var items = body.querySelectorAll('.lt-ca-item');
                            var collected = [];
                            items.forEach(function (item) {
                                collected.push({
                                    name: (item.querySelector('.lt-ca-name') || {}).value || '',
                                    url: (item.querySelector('.lt-ca-url') || {}).value || '',
                                    api_key: (item.querySelector('.lt-ca-key') || {}).value || '',
                                    enabled: !!(item.querySelector('.lt-ca-enabled') || {}).checked,
                                });
                            });
                            saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                            saveBtn.style.pointerEvents = 'none';
                            Millennium.callServerMethod('luatools', 'SaveCustomApis', { apis_json: JSON.stringify(collected), contentScriptQuery: '' })
                                .then(function (r2) {
                                    var p2 = typeof r2 === 'string' ? JSON.parse(r2) : r2;
                                    if (p2.success) {
                                        try { ov.remove(); } catch (_) { }
                                        ShowLuaToolsAlert('Custom APIs', 'Saved ' + (p2.count || 0) + ' API source(s).');
                                    } else {
                                        ShowLuaToolsAlert('Custom APIs', p2.error || 'Failed to save.');
                                        saveBtn.innerHTML = 'Save';
                                        saveBtn.style.pointerEvents = 'auto';
                                    }
                                })
                                .catch(function () { saveBtn.innerHTML = 'Save'; saveBtn.style.pointerEvents = 'auto'; });
                        };
                    }
                    render();
                })
                .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function showSteamToolsLibraryScanner() {
        _stOverlayShell('💿 Steam Library Scanner', function (body, ov, colors) {
            body.innerHTML = '<div style="text-align:center;padding:10px;color:' + colors.accent + '"><i class="fa-solid fa-spinner fa-spin" style="font-size:16px;"></i><div style="margin-top:8px;">Scanning all drives for Steam libraries…</div></div>';
            Millennium.callServerMethod('luatools', 'ScanSteamLibraries', { contentScriptQuery: '' })
                .then(function (res) {
                    var p = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!p.success) { body.innerHTML = '<div style="color:#f44336;">Error: ' + (p.error || 'Unknown') + '</div>'; return; }
                    var libs = p.libraries || [];
                    var html = '<div style="text-align:center;margin-bottom:16px;">'
                        + '<div style="font-size:15px;font-weight:700;color:' + colors.accent + ';">' + libs.length + '</div>'
                        + '<div style="font-size:12px;opacity:0.6;">Steam Libraries Found</div></div>';
                    html += '<div style="display:flex;flex-direction:column;gap:8px;max-height:50vh;overflow-y:auto;">';
                    libs.forEach(function (lib) {
                        var badge = lib.isPrimary ? '<span style="background:' + colors.accent + ';color:#000;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:8px;">PRIMARY</span>' : '';
                        html += '<div style="padding:12px;background:rgba(255,255,255,0.04);border:1px solid ' + colors.borderRgba + ';border-radius:10px;">'
                            + '<div style="display:flex;justify-content:space-between;align-items:center;">'
                            + '<div style="font-weight:600;font-size:13px;">' + lib.path + badge + '</div>'
                            + '<div style="font-weight:700;color:' + colors.accent + ';">' + (lib.sizeGB || 0) + ' GB</div></div>'
                            + '<div style="font-size:12px;opacity:0.6;margin-top:4px;">' + (lib.gameCount || 0) + ' games installed'
                            + (lib.exists === false ? ' <span style="color:#f44336;">(path missing)</span>' : '') + '</div>';
                        if (lib.games && lib.games.length > 0) {
                            html += '<div style="margin-top:8px;font-size:11px;opacity:0.5;max-height:80px;overflow-y:auto;">';
                            lib.games.forEach(function (g) {
                                html += '<div>' + g.appid + ' — ' + (g.name || '?').replace(/</g, '&lt;') + '</div>';
                            });
                            if (lib.gameCount > lib.games.length) {
                                html += '<div style="color:' + colors.accent + ';">… and ' + (lib.gameCount - lib.games.length) + ' more</div>';
                            }
                            html += '</div>';
                        }
                        html += '</div>';
                    });
                    html += '</div>';
                    body.innerHTML = html;
                })
                .catch(function (err) { body.innerHTML = '<div style="color:#f44336;">Failed: ' + err + '</div>'; });
        });
    }

    function ensureTranslationsLoaded(forceRefresh, preferredLanguage) {
        try {
            if (!forceRefresh && window.__LuaToolsI18n && window.__LuaToolsI18n.ready) {
                return Promise.resolve(window.__LuaToolsI18n);
            }
            if (typeof Millennium === 'undefined' || typeof Millennium.callServerMethod !== 'function') {
                window.__LuaToolsI18n = window.__LuaToolsI18n || {
                    language: 'en',
                    locales: [],
                    strings: {},
                    ready: false
                };
                return Promise.resolve(window.__LuaToolsI18n);
            }
            const settingsVals = ((window.__LuaToolsSettings || {}).values || {}).general || {};
            const useSteamLang = typeof settingsVals.useSteamLanguage === 'boolean' ? settingsVals.useSteamLanguage : true;
            let targetLanguage = (typeof preferredLanguage === 'string' && preferredLanguage) ? preferredLanguage : '';
            if (!targetLanguage) {
                let steamLang = document.documentElement.lang || 'en';
                if (steamLang.toLowerCase() === 'pt-br') steamLang = 'pt-BR';
                if (steamLang.toLowerCase() === 'zh-cn') steamLang = 'zh-CN';
                if (steamLang.toLowerCase() === 'zh-tw') steamLang = 'zh-TW';
                if (steamLang.toLowerCase() === 'es-419') steamLang = 'es';
                targetLanguage = useSteamLang ? steamLang : ((window.__LuaToolsI18n && window.__LuaToolsI18n.language) || 'en');
            }
            return Millennium.callServerMethod('luatools', 'GetTranslations', {
                language: targetLanguage,
                contentScriptQuery: ''
            }).then(function (res) {
                const payload = typeof res === 'string' ? JSON.parse(res) : res;
                if (!payload || payload.success !== true || !payload.strings) {
                    throw new Error('Invalid translation payload');
                }
                applyTranslationBundle(payload);
                // Update button text after translations are loaded
                updateButtonTranslations();
                return window.__LuaToolsI18n;
            }).catch(function (err) {
                backendLog('LuaTools: translation load failed: ' + err);
                window.__LuaToolsI18n = window.__LuaToolsI18n || {
                    language: 'en',
                    locales: [],
                    strings: {},
                    ready: false
                };
                return window.__LuaToolsI18n;
            });
        } catch (err) {
            backendLog('LuaTools: ensureTranslationsLoaded error: ' + err);
            window.__LuaToolsI18n = window.__LuaToolsI18n || {
                language: 'en',
                locales: [],
                strings: {},
                ready: false
            };
            return Promise.resolve(window.__LuaToolsI18n);
        }
    }

    function translateText(key, fallback) {
        if (!key) {
            return typeof fallback !== 'undefined' ? fallback : '';
        }
        try {
            const store = window.__LuaToolsI18n;
            if (store && store.strings && Object.prototype.hasOwnProperty.call(store.strings, key)) {
                const value = store.strings[key];
                if (typeof value === 'string') {
                    const trimmed = value.trim();
                    if (trimmed && trimmed.toLowerCase() !== TRANSLATION_PLACEHOLDER) {
                        return value;
                    }
                }
            }
        } catch (_) { }
        return typeof fallback !== 'undefined' ? fallback : key;
    }

    function t(key, fallback) {
        return translateText(key, fallback);
    }

    function lt(text) {
        return t(text, text);
    }

    // Translations are loaded by fetchSettingsConfig() in onFrontendReady — no separate preload needed.

    let settingsMenuPending = false;

    // Helper: show a Steam-style popup with a 10s loading bar (custom UI)
    function showTestPopup() {

        // Avoid duplicates
        if (document.querySelector('.luatools-overlay')) return;
        // Close settings popup if open so modals don't overlap
        try {
            const s = document.querySelector('.luatools-settings-overlay');
            if (s) s.remove();
        } catch (_) { }

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const colors = getThemeColors();
        modal.style.cssText = `background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:8px;width:440px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${colors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const title = document.createElement('div');
        const titleColors = getThemeColors();
        title.style.cssText = `font-size:14px;color:${titleColors.text};margin-bottom:12px;font-weight:700;text-shadow:0 2px 8px ${titleColors.shadow};background:${titleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        title.className = 'luatools-title';
        title.textContent = t('common.appName', 'LuaTools');

        // API list container
        const apiListContainer = document.createElement('div');
        apiListContainer.className = 'luatools-api-list';
        apiListContainer.style.cssText = 'margin-bottom:10px;max-height:280px;overflow-y:auto;';

        // Placeholder while loading APIs
        const loadingItem = document.createElement('div');
        loadingItem.style.cssText = `text-align:center;padding:10px;color:${colors.textSecondary};font-size:13px;`;
        loadingItem.textContent = lt('Loading APIs...');
        apiListContainer.appendChild(loadingItem);

        // Load APIs dynamically from backend
        if (typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
            Millennium.callServerMethod('luatools', 'GetApiList', {
                contentScriptQuery: ''
            }).then(function (res) {
                try {
                    const payload = typeof res === 'string' ? JSON.parse(res) : res;
                    if (payload && payload.success && payload.apis && Array.isArray(payload.apis)) {
                        // Clear loading message
                        apiListContainer.innerHTML = '';

                        // Create API items
                        payload.apis.forEach((api, index) => {
                            const apiItem = document.createElement('div');
                            apiItem.className = `luatools-api-item luatools-api-${index}`;
                            apiItem.setAttribute('data-api-name', api.name);
                            apiItem.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:5px 10px;margin-bottom:3px;background:rgba(${colors.rgbString},0.07);border:1px solid ${colors.borderRgba};border-radius:5px;transition:all 0.15s;`;

                            const apiName = document.createElement('div');
                            apiName.className = 'luatools-api-name';
                            apiName.style.cssText = `font-size:12px;color:${colors.textSecondary};font-weight:500;`;
                            apiName.textContent = api.name;

                            const apiStatus = document.createElement('div');
                            apiStatus.className = 'luatools-api-status';
                            apiStatus.style.cssText = `font-size:11px;color:${colors.textSecondary};display:flex;align-items:center;gap:4px;`;
                            apiStatus.innerHTML = '<span style="opacity:.6">' + lt('…') + '</span>';

                            apiItem.appendChild(apiName);
                            apiItem.appendChild(apiStatus);
                            apiListContainer.appendChild(apiItem);
                        });
                    }
                } catch (err) {
                    backendLog('Failed to parse API list: ' + err);
                }
            }).catch(function (err) {
                backendLog('Failed to load API list: ' + err);
            });
        }

        const body = document.createElement('div');
        body.style.cssText = `font-size:12px;line-height:1.3;margin-bottom:8px;color:${colors.textSecondary};`;
        body.className = 'luatools-status';
        body.textContent = lt('Checking availability…');

        const progressWrap = document.createElement('div');
        progressWrap.style.cssText = `background:rgba(0,0,0,0.3);height:16px;border-radius:3px;overflow:hidden;position:relative;display:none;border:1px solid ${colors.border};margin-top:8px;`;
        progressWrap.className = 'luatools-progress-wrap';
        const progressBar = document.createElement('div');
        progressBar.style.cssText = `height:100%;width:0%;background:${colors.gradient};transition:width 0.3s ease;box-shadow:0 0 10px ${colors.shadow};`;
        progressBar.className = 'luatools-progress-bar';
        progressWrap.appendChild(progressBar);

        const progressInfo = document.createElement('div');
        progressInfo.style.cssText = `display:none;margin-top:4px;font-size:11px;color:${colors.textSecondary};flex-direction:column;gap:2px;`;
        progressInfo.className = 'luatools-progress-info';

        const progressRow1 = document.createElement('div');
        progressRow1.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';

        const percent = document.createElement('span');
        percent.className = 'luatools-percent';
        percent.textContent = '0%';

        const downloadSize = document.createElement('span');
        downloadSize.className = 'luatools-download-size';
        downloadSize.style.cssText = 'margin-left:8px;';
        downloadSize.textContent = '';

        const progressRow2 = document.createElement('div');
        progressRow2.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';

        const speedEl = document.createElement('span');
        speedEl.className = 'luatools-speed';
        speedEl.style.cssText = `color:${colors.accent};font-weight:600;`;
        speedEl.textContent = '';

        const etaEl = document.createElement('span');
        etaEl.className = 'luatools-eta';
        etaEl.style.cssText = `color:${colors.textSecondary};`;
        etaEl.textContent = '';

        progressRow1.appendChild(percent);
        progressRow1.appendChild(downloadSize);
        progressRow2.appendChild(speedEl);
        progressRow2.appendChild(etaEl);
        progressInfo.appendChild(progressRow1);
        progressInfo.appendChild(progressRow2);

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'margin-top:8px;display:flex;gap:6px;justify-content:flex-end;';
        const cancelBtn = document.createElement('a');
        cancelBtn.className = 'luatools-btn luatools-cancel-btn';
        cancelBtn.innerHTML = `<span>${lt('Cancel')}</span>`;
        cancelBtn.href = '#';
        cancelBtn.style.display = 'none';
        cancelBtn.onclick = function (e) {
            e.preventDefault();
            cancelOperation();
        };
        const hideBtn = document.createElement('a');
        hideBtn.className = 'luatools-btn luatools-hide-btn';
        hideBtn.innerHTML = `<span>${lt('Hide')}</span>`;
        hideBtn.href = '#';
        hideBtn.onclick = function (e) {
            e.preventDefault();
            cleanup();
        };
        btnRow.appendChild(cancelBtn);
        btnRow.appendChild(hideBtn);

        modal.appendChild(title);
        modal.appendChild(apiListContainer);
        modal.appendChild(body);
        modal.appendChild(progressWrap);
        modal.appendChild(progressInfo);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);

        function cleanup() {
            overlay.remove();
        }

        function cancelOperation() {
            // Call backend to cancel the operation
            try {
                const match = window.location.href.match(/https:\/\/store\.steampowered\.com\/app\/(\d+)/) || window.location.href.match(/https:\/\/steamcommunity\.com\/app\/(\d+)/);
                const appid = match ? parseInt(match[1], 10) : (window.__LuaToolsCurrentAppId || NaN);
                if (!isNaN(appid) && typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
                    Millennium.callServerMethod('luatools', 'CancelAddViaLuaTools', {
                        appid,
                        contentScriptQuery: ''
                    });
                }
            } catch (_) { }
            // Update UI to show cancelled
            const status = overlay.querySelector('.luatools-status');
            if (status) status.textContent = lt('Cancelled');
            const cancelBtn = overlay.querySelector('.luatools-cancel-btn');
            if (cancelBtn) cancelBtn.style.display = 'none';
            const hideBtn = overlay.querySelector('.luatools-hide-btn');
            if (hideBtn) hideBtn.innerHTML = `<span>${lt('Close')}</span>`;
            // Hide progress UI
            const wrap = overlay.querySelector('.luatools-progress-wrap');
            const progressInfo = overlay.querySelector('.luatools-progress-info');
            if (wrap) wrap.style.display = 'none';
            if (progressInfo) progressInfo.style.display = 'none';
            // Reset run state
            runState.inProgress = false;
            runState.appid = null;
        }
    }

    // Fixes Results popup
    function showFixesResultsPopup(data, isGameInstalled) {
        if (document.querySelector('.luatools-fixes-results-overlay')) return;
        // Close other popups
        try {
            const d = document.querySelector('.luatools-overlay');
            if (d) d.remove();
        } catch (_) { }
        try {
            const s = document.querySelector('.luatools-settings-overlay');
            if (s) s.remove();
        } catch (_) { }
        try {
            const f = document.querySelector('.luatools-fixes-results-overlay');
            if (f) f.remove();
        } catch (_) { }
        try {
            const l = document.querySelector('.luatools-loading-fixes-overlay');
            if (l) l.remove();
        } catch (_) { }

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-fixes-results-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const colors = getThemeColors();
        modal.style.cssText = `position:relative;background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:8px;width:520px;max-width:95vw;max-height:80vh;display:flex;flex-direction:column;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${colors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const header = document.createElement('div');
        header.style.cssText = `flex:0 0 auto;display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid ${colors.borderRgba};`;

        const title = document.createElement('div');
        title.style.cssText = `font-size:15px;color:${colors.text};font-weight:700;text-shadow:0 2px 8px ${colors.shadow};background:${colors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        title.textContent = lt('LuaTools · Fixes Menu');

        const iconButtons = document.createElement('div');
        iconButtons.style.cssText = 'display:flex;gap:6px;';

        function createIconButton(id, iconClass, titleKey, titleFallback) {
            const btn = document.createElement('a');
            btn.id = id;
            btn.href = '#';
            const btnColors = getThemeColors();
            btn.style.cssText = `display:flex;align-items:center;justify-content:center;width:28px;height:28px;background:rgba(${btnColors.rgbString},0.1);border:1px solid ${btnColors.borderRgba};border-radius:8px;color:${btnColors.accent};font-size:15px;text-decoration:none;transition:all 0.3s ease;cursor:pointer;`;
            btn.innerHTML = '<i class="fa-solid ' + iconClass + '"></i>';
            btn.title = t(titleKey, titleFallback);
            btn.onmouseover = function () {
                this.style.background = `rgba(${btnColors.rgbString},0.25)`;
                this.style.transform = 'translateY(-2px) scale(1.05)';
                this.style.boxShadow = `0 8px 16px ${btnColors.shadowRgba}`;
                this.style.borderColor = btnColors.accent;
            };
            btn.onmouseout = function () {
                this.style.background = `rgba(${btnColors.rgbString},0.1)`;
                this.style.transform = 'translateY(0) scale(1)';
                this.style.boxShadow = 'none';
                this.style.borderColor = btnColors.borderRgba;
            };
            iconButtons.appendChild(btn);
            return btn;
        }

        const discordBtn = createIconButton('lt-fixes-discord', 'fa-brands fa-discord', 'menu.discord', 'Discord');
        const settingsBtn = createIconButton('lt-fixes-settings', 'fa-gear', 'menu.settings', 'Settings');
        const closeIconBtn = createIconButton('lt-fixes-close', 'fa-xmark', 'settings.close', 'Close');

        const body = document.createElement('div');
        const bodyColors = getThemeColors();
        body.style.cssText = `flex:1 1 auto;overflow-y:auto;padding:12px;border:1px solid ${bodyColors.border};border-radius:12px;background:${bodyColors.bgContainer};`

        try {
            const bannerImg = document.querySelector('.game_header_image_full');
            if (bannerImg && bannerImg.src) {
                body.style.background = `linear-gradient(to bottom, rgba(15, 15, 15, 0.85), #0f0f0f 70%), url('${bannerImg.src}') no-repeat top center`;
                body.style.backgroundSize = 'cover';
            }
        } catch (_) { }

        // Add mouse mode tip for Big Picture
        if (window.__LUATOOLS_IS_BIG_PICTURE__) {
            const tip = document.createElement('div');
            tip.style.cssText = 'background:rgba(102,192,244,0.15);border-left:3px solid #66c0f4;padding:8px 10px;border-radius:5px;font-size:11px;color:#c7d5e0;margin-bottom:16px;line-height:1.5;';
            tip.innerHTML = '<i class="fa-solid fa-info-circle" style="margin-right:8px;color:#66c0f4;"></i>' + t('bigpicture.mouseTip', 'To use mouse mode in Steam: Guide Button + Right Joystick, click with RB');
            body.appendChild(tip);
        }

        const gameHeader = document.createElement('div');
        gameHeader.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:10px;';

        const gameIcon = document.createElement('img');
        gameIcon.style.cssText = 'width:32px;height:32px;border-radius:4px;object-fit:cover;display:none;';
        try {
            const iconImg = document.querySelector('.apphub_AppIcon img');
            if (iconImg && iconImg.src) {
                gameIcon.src = iconImg.src;
                gameIcon.style.display = 'block';
            }
        } catch (_) { }

        const gameName = document.createElement('div');
        gameName.style.cssText = 'font-size:13px;color:#fff;font-weight:600;text-align:center;';
        gameName.textContent = data.gameName || lt('Unknown Game');

        if (!data.gameName || data.gameName === 'Unknown Game' || data.gameName === lt('Unknown Game') || data.gameName.startsWith('Unknown Game')) {
            fetchSteamGameName(data.appid).then(function (name) {
                if (name) {
                    data.gameName = name;
                    gameName.textContent = name;
                }
            });
        }


        const contentContainer = document.createElement('div');
        contentContainer.style.position = 'relative';
        contentContainer.style.zIndex = '1';

        const columnsContainer = document.createElement('div');
        columnsContainer.style.cssText = 'display:flex;gap:10px;';

        const leftColumn = document.createElement('div');
        leftColumn.style.cssText = 'flex:1;display:flex;flex-direction:column;gap:8px;';

        const rightColumn = document.createElement('div');
        rightColumn.style.cssText = 'flex:1;display:flex;flex-direction:column;gap:8px;';

        function createFixButton(label, text, icon, isSuccess, onClick) {
            const section = document.createElement('div');
            section.style.cssText = 'width:100%;text-align:center;';

            const sectionLabel = document.createElement('div');
            const labelColors = getThemeColors();
            sectionLabel.style.cssText = `font-size:12px;color:${labelColors.accent};margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:1px;`;
            sectionLabel.textContent = label;

            const btn = document.createElement('a');
            btn.href = '#';
            const btnColors = getThemeColors();
            btn.style.cssText = `display:flex;align-items:center;justify-content:center;gap:10px;width:100%;box-sizing:border-box;padding:10px 16px;background:linear-gradient(135deg, rgba(${btnColors.rgbString},0.15) 0%, rgba(${btnColors.rgbString},0.05) 100%);border:1px solid ${btnColors.border};border-radius:8px;color:${btnColors.text};font-size:12px;font-weight:500;text-decoration:none;transition:all 0.3s ease;cursor:pointer;`;
            btn.innerHTML = '<i class="fa-solid ' + icon + '" style="font-size:16px;"></i><span>' + text + '</span>';

            // If the active theme is light, make certain fix action texts/icons white for readability.
            try {
                const currentThemeKey = (((window.__LuaToolsSettings || {}).values || {}).general || {}).theme || 'original';
                // Use localized labels so this works in other languages
                const applyLabel = lt('Apply');
                const onlineUnsteamLabel = lt('Online Fix (Unsteam)');
                const noOnlineLabel = lt('No online-fix');
                const unfixLabel = lt('Un-Fix (verify game)');
                const noGenericLabel = lt('No generic fix');
                const whiteTexts = new Set([applyLabel, onlineUnsteamLabel, noOnlineLabel, unfixLabel, noGenericLabel]);
                if (currentThemeKey === 'light' && whiteTexts.has(String(text))) {
                    const spanEl = btn.querySelector('span');
                    const iconEl = btn.querySelector('i');
                    if (spanEl) spanEl.style.color = '#ffffff';
                    if (iconEl) iconEl.style.color = '#ffffff';
                }
            } catch (_) { }

            if (isSuccess) {
                btn.style.background = 'linear-gradient(135deg, rgba(92,156,62,0.4) 0%, rgba(92,156,62,0.2) 100%)';
                btn.style.borderColor = 'rgba(92,156,62,0.6)';
                btn.onmouseover = function () {
                    this.style.background = 'linear-gradient(135deg, rgba(92,156,62,0.6) 0%, rgba(92,156,62,0.3) 100%)';
                    this.style.transform = 'translateY(-2px)';
                    this.style.boxShadow = '0 8px 20px rgba(92,156,62,0.3)';
                    this.style.borderColor = '#79c754';
                };
                btn.onmouseout = function () {
                    this.style.background = 'linear-gradient(135deg, rgba(92,156,62,0.4) 0%, rgba(92,156,62,0.2) 100%)';
                    this.style.transform = 'translateY(0)';
                    this.style.boxShadow = 'none';
                    this.style.borderColor = 'rgba(92,156,62,0.6)';
                };
            } else if (isSuccess === false) {
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
            } else {
                const mutableColors = getThemeColors();
                btn.onmouseover = function () {
                    const c = getThemeColors();
                    this.style.background = `linear-gradient(135deg, rgba(${c.rgbString},0.3) 0%, rgba(${c.rgbString},0.15) 100%)`;
                    this.style.transform = 'translateY(-2px)';
                    this.style.boxShadow = `0 8px 20px rgba(${c.rgbString},0.25)`;
                    this.style.borderColor = c.accent;
                };
                btn.onmouseout = function () {
                    const c = getThemeColors();
                    this.style.background = `linear-gradient(135deg, rgba(${c.rgbString},0.15) 0%, rgba(${c.rgbString},0.05) 100%)`;
                    this.style.transform = 'translateY(0)';
                    this.style.boxShadow = 'none';
                    this.style.borderColor = c.border;
                };
            }

            btn.onclick = onClick;

            section.appendChild(sectionLabel);
            section.appendChild(btn);
            return section;
        }

        // left thing in fixes modal
        const genericStatus = data.genericFix.status;
        const genericSection = createFixButton(
            lt('Generic Fix'),
            genericStatus === 200 ? lt('Apply') : lt('No generic fix'),
            genericStatus === 200 ? 'fa-check' : 'fa-circle-xmark',
            genericStatus === 200 ? true : false,
            function (e) {
                e.preventDefault();
                if (genericStatus === 200 && isGameInstalled) {
                    const genericUrl = 'https://files.luatools.work/GameBypasses/' + data.appid + '.zip';
                    applyFix(data.appid, genericUrl, lt('Generic Fix'), data.gameName, overlay);
                }
            }
        );
        leftColumn.appendChild(genericSection);

        if (!isGameInstalled) {
            genericSection.querySelector('a').style.opacity = '0.5';
            genericSection.querySelector('a').style.cursor = 'not-allowed';
        }

        const onlineStatus = data.onlineFix.status;
        const onlineSection = createFixButton(
            lt('Online Fix'),
            onlineStatus === 200 ? lt('Apply') : lt('No online-fix'),
            onlineStatus === 200 ? 'fa-check' : 'fa-circle-xmark',
            onlineStatus === 200 ? true : false,
            function (e) {
                e.preventDefault();
                if (onlineStatus === 200 && isGameInstalled) {
                    const onlineUrl = data.onlineFix.url || ('https://files.luatools.work/OnlineFix1/' + data.appid + '.zip');
                    applyFix(data.appid, onlineUrl, lt('Online Fix'), data.gameName, overlay);
                }
            }
        );
        leftColumn.appendChild(onlineSection);

        if (!isGameInstalled) {
            onlineSection.querySelector('a').style.opacity = '0.5';
            onlineSection.querySelector('a').style.cursor = 'not-allowed';
        }

        // right
        const aioSection = createFixButton(
            lt('All-In-One Fixes'),
            lt('Online Fix (Unsteam)'),
            'fa-globe',
            null, // default blue button
            function (e) {
                e.preventDefault();
                if (isGameInstalled) {
                    const downloadUrl = 'https://github.com/madoiscool/lt_api_links/releases/download/unsteam/Win64.zip';
                    applyFix(data.appid, downloadUrl, lt('Online Fix (Unsteam)'), data.gameName, overlay);
                }
            }
        );
        rightColumn.appendChild(aioSection);
        if (!isGameInstalled) {
            aioSection.querySelector('a').style.opacity = '0.5';
            aioSection.querySelector('a').style.cursor = 'not-allowed';
        }

        const unfixSection = createFixButton(
            lt('Manage Game'),
            lt('Un-Fix (verify game)'),
            'fa-trash',
            null, // ^^
            function (e) {
                e.preventDefault();
                if (isGameInstalled) {
                    try {
                        overlay.remove();
                    } catch (_) { }
                    showLuaToolsConfirm('LuaTools', lt('Are you sure you want to un-fix? This will remove fix files and verify game files.'),
                        function () {
                            startUnfix(data.appid);
                        },
                        function () {
                            showFixesResultsPopup(data, isGameInstalled);
                        }
                    );
                }
            }
        );
        rightColumn.appendChild(unfixSection);
        if (!isGameInstalled) {
            unfixSection.querySelector('a').style.opacity = '0.5';
            unfixSection.querySelector('a').style.cursor = 'not-allowed';
        }

        // Credit message
        const creditMsg = document.createElement('div');
        const creditColors = getThemeColors();
        creditMsg.style.cssText = `margin-top:8px;text-align:center;font-size:13px;color:${creditColors.textSecondary};`;
        const creditTemplate = lt('Only possible thanks to {name} 💜');
        creditMsg.innerHTML = creditTemplate.replace('{name}', `<a href="#" id="lt-shayenvi-link" style="color:${creditColors.accent};text-decoration:none;font-weight:600;">ShayneVi</a>`);

        // Wire up ShayneVi link
        setTimeout(function () {
            const shayenviLink = overlay.querySelector('#lt-shayenvi-link');
            if (shayenviLink) {
                shayenviLink.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        Millennium.callServerMethod('luatools', 'OpenExternalUrl', {
                            url: 'https://github.com/ShayneVi/',
                            contentScriptQuery: ''
                        });
                    } catch (_) { }
                });
            }
        }, 0);

        // body moment
        gameHeader.appendChild(gameIcon);
        gameHeader.appendChild(gameName);
        contentContainer.appendChild(gameHeader);

        if (!isGameInstalled) {
            const notInstalledWarning = document.createElement('div');
            notInstalledWarning.style.cssText = 'margin-bottom: 16px; padding: 12px; background: rgba(255, 193, 7, 0.1); border: 1px solid rgba(255, 193, 7, 0.3); border-radius: 6px; color: #ffc107; font-size: 13px; text-align: center;';
            notInstalledWarning.innerHTML = '<i class="fa-solid fa-circle-info" style="margin-right: 8px;"></i>' + t('menu.error.notInstalled', 'Game is not installed');
            contentContainer.appendChild(notInstalledWarning);
        }

        columnsContainer.appendChild(leftColumn);
        columnsContainer.appendChild(rightColumn);
        contentContainer.appendChild(columnsContainer);
        contentContainer.appendChild(creditMsg);
        body.appendChild(contentContainer);

        // header moment
        header.appendChild(title);
        header.appendChild(iconButtons);

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'flex:0 0 auto;margin-top:8px;display:flex;gap:8px;justify-content:space-between;align-items:center;';

        const rightButtons = document.createElement('div');
        rightButtons.style.cssText = 'display:flex;gap:8px;';
        const gameFolderBtn = document.createElement('a');
        gameFolderBtn.className = 'luatools-btn';
        gameFolderBtn.innerHTML = `<span><i class="fa-solid fa-folder" style="margin-right: 8px;"></i>${lt('Game folder')}</span>`;
        gameFolderBtn.href = '#';
        gameFolderBtn.onclick = function (e) {
            e.preventDefault();
            if (window.__LuaToolsGameInstallPath) {
                try {
                    Millennium.callServerMethod('luatools', 'OpenGameFolder', {
                        path: window.__LuaToolsGameInstallPath,
                        contentScriptQuery: ''
                    });
                } catch (err) {
                    backendLog('LuaTools: Failed to open game folder: ' + err);
                }
            }
        };
        rightButtons.appendChild(gameFolderBtn);

        const backBtn = document.createElement('a');
        backBtn.className = 'luatools-btn';
        backBtn.innerHTML = '<span><i class="fa-solid fa-arrow-left"></i></span>';
        backBtn.href = '#';
        backBtn.onclick = function (e) {
            e.preventDefault();
            try {
                overlay.remove();
            } catch (_) { }
            showSettingsPopup();
        };
        btnRow.appendChild(backBtn);
        btnRow.appendChild(rightButtons);

        // final modal
        modal.appendChild(header);
        modal.appendChild(body);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);

        closeIconBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
        };
        discordBtn.onclick = function (e) {
            e.preventDefault();
            try {
                overlay.remove();
            } catch (_) { }
            const url = 'https://discord.gg/luatools';
            try {
                Millennium.callServerMethod('luatools', 'OpenExternalUrl', {
                    url,
                    contentScriptQuery: ''
                });
            } catch (_) { }
        };
        settingsBtn.onclick = function (e) {
            e.preventDefault();
            try {
                overlay.remove();
            } catch (_) { }
            showSettingsManagerPopup(false, function () {
                showFixesResultsPopup(data, isGameInstalled);
            });
        };

        function startUnfix(appid) {
            try {
                Millennium.callServerMethod('luatools', 'UnFixGame', {
                    appid: appid,
                    installPath: window.__LuaToolsGameInstallPath,
                    contentScriptQuery: ''
                }).then(function (res) {
                    const payload = typeof res === 'string' ? JSON.parse(res) : res;
                    if (payload && payload.success) {
                        showUnfixProgress(appid);
                    } else {
                        const errorKey = (payload && payload.error) ? String(payload.error) : '';
                        const errorMsg = (errorKey && (errorKey.startsWith('menu.error.') || errorKey.startsWith('common.'))) ? t(errorKey) : (errorKey || lt('Failed to start un-fix'));
                        ShowLuaToolsAlert('LuaTools', errorMsg);
                    }
                }).catch(function () {
                    const msg = lt('Error starting un-fix');
                    ShowLuaToolsAlert('LuaTools', msg);
                });
            } catch (err) {
                backendLog('LuaTools: Un-Fix start error: ' + err);
            }
        }
    }

    function showFixesLoadingPopupAndCheck(appid) {
        if (document.querySelector('.luatools-loading-fixes-overlay')) return;
        try {
            const d = document.querySelector('.luatools-overlay');
            if (d) d.remove();
        } catch (_) { }
        try {
            const s = document.querySelector('.luatools-settings-overlay');
            if (s) s.remove();
        } catch (_) { }
        try {
            const f = document.querySelector('.luatools-fixes-overlay');
            if (f) f.remove();
        } catch (_) { }

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-loading-fixes-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const colors = getThemeColors();
        modal.style.cssText = `background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:8px;width:400px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${colors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const title = document.createElement('div');
        const titleColorsLoading = getThemeColors();
        title.style.cssText = `font-size:13px;color:${titleColorsLoading.text};margin-bottom:10px;font-weight:700;text-shadow:0 2px 8px ${titleColorsLoading.shadow};background:${titleColorsLoading.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        title.textContent = lt('Loading fixes...');

        const body = document.createElement('div');
        const bodyColorsLoading = getThemeColors();
        body.style.cssText = `font-size:14px;line-height:1.35;margin-bottom:16px;color:${bodyColorsLoading.textSecondary};`;
        body.textContent = lt('Checking availability…');

        const progressWrap = document.createElement('div');
        const progressColorsLoading = getThemeColors();
        progressWrap.style.cssText = `background:rgba(0,0,0,0.3);height:12px;border-radius:4px;overflow:hidden;position:relative;border:1px solid ${progressColorsLoading.border};`;
        const progressBar = document.createElement('div');
        progressBar.style.cssText = `height:100%;width:0%;background:${progressColorsLoading.gradient};transition:width 0.2s linear;box-shadow:0 0 10px ${progressColorsLoading.shadow};`;
        progressWrap.appendChild(progressBar);

        modal.appendChild(title);
        modal.appendChild(body);
        modal.appendChild(progressWrap);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);

        let progress = 0;
        const progressInterval = setInterval(function () {
            if (progress < 95) {
                progress += Math.random() * 5;
                progressBar.style.width = Math.min(progress, 95) + '%';
            }
        }, 200);

        fetchFixes(appid).then(function (payload) {
            if (payload && payload.success) {
                const isGameInstalled = window.__LuaToolsGameIsInstalled === true;
                showFixesResultsPopup(payload, isGameInstalled);
            } else {
                const errText = (payload && payload.error) ? String(payload.error) : lt('Failed to check for fixes.');
                ShowLuaToolsAlert('LuaTools', errText);
            }
        }).catch(function () {
            const msg = lt('Error checking for fixes');
            ShowLuaToolsAlert('LuaTools', msg);
        }).finally(function () {
            clearInterval(progressInterval);
            progressBar.style.width = '100%';
            setTimeout(function () {
                try {
                    const l = document.querySelector('.luatools-loading-fixes-overlay');
                    if (l) l.remove();
                } catch (_) { }
            }, 300);
        });
    }

    // Apply Fix function
    function applyFix(appid, downloadUrl, fixType, gameName, resultsOverlay) {
        try {
            // Close results overlay
            if (resultsOverlay) {
                resultsOverlay.remove();
            }

            // Check if we have the game install path
            if (!window.__LuaToolsGameInstallPath) {
                const msg = lt('Game install path not found');
                ShowLuaToolsAlert('LuaTools', msg);
                return;
            }

            backendLog('LuaTools: Applying fix ' + fixType + ' for appid ' + appid);

            // Start the download and extraction process
            Millennium.callServerMethod('luatools', 'ApplyGameFix', {
                appid: appid,
                downloadUrl: downloadUrl,
                installPath: window.__LuaToolsGameInstallPath,
                fixType: fixType,
                gameName: gameName || '',
                contentScriptQuery: ''
            }).then(function (res) {
                try {
                    const payload = typeof res === 'string' ? JSON.parse(res) : res;
                    if (payload && payload.success) {
                        // Show download progress popup similar to Add via LuaTools
                        showFixDownloadProgress(appid, fixType);
                    } else {
                        const errorKey = (payload && payload.error) ? String(payload.error) : '';
                        const errorMsg = (errorKey && (errorKey.startsWith('menu.error.') || errorKey.startsWith('common.'))) ? t(errorKey) : (errorKey || lt('Failed to start fix download'));
                        ShowLuaToolsAlert('LuaTools', errorMsg);
                    }
                } catch (err) {
                    backendLog('LuaTools: ApplyGameFix response error: ' + err);
                    const msg = lt('Error applying fix');
                    ShowLuaToolsAlert('LuaTools', msg);
                }
            }).catch(function (err) {
                backendLog('LuaTools: ApplyGameFix error: ' + err);
                const msg = lt('Error applying fix');
                ShowLuaToolsAlert('LuaTools', msg);
            });
        } catch (err) {
            backendLog('LuaTools: applyFix error: ' + err);
        }
    }

    // Show fix download progress popup
    function showFixDownloadProgress(appid, fixType) {
        // Reuse the download popup UI from Add via LuaTools
        if (document.querySelector('.luatools-overlay')) return;

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const colors = getThemeColors();
        modal.style.cssText = `background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:8px;width:400px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${colors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const title = document.createElement('div');
        const applyFixTitleColors = getThemeColors();
        title.style.cssText = `font-size:13px;color:${applyFixTitleColors.text};margin-bottom:10px;font-weight:700;text-shadow:0 2px 8px ${applyFixTitleColors.shadow};background:${applyFixTitleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        title.textContent = lt('Applying {fix}').replace('{fix}', fixType);

        const body = document.createElement('div');
        const applyFixBodyColors = getThemeColors();
        body.style.cssText = `font-size:15px;line-height:1.35;margin-bottom:10px;color:${applyFixBodyColors.textSecondary};`;
        body.innerHTML = '<div id="lt-fix-progress-msg">' + lt('Downloading...') + '</div>';

        const btnRow = document.createElement('div');
        btnRow.className = 'lt-fix-btn-row';
        btnRow.style.cssText = 'margin-top:8px;display:flex;gap:6px;justify-content:center;';

        const hideBtn = document.createElement('a');
        hideBtn.href = '#';
        hideBtn.className = 'luatools-btn';
        hideBtn.style.flex = '1';
        hideBtn.innerHTML = `<span>${lt('Hide')}</span>`;
        hideBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
        };
        btnRow.appendChild(hideBtn);

        const cancelBtn = document.createElement('a');
        cancelBtn.href = '#';
        cancelBtn.className = 'luatools-btn primary';
        cancelBtn.style.flex = '1';
        cancelBtn.innerHTML = `<span>${lt('Cancel')}</span>`;
        cancelBtn.onclick = function (e) {
            e.preventDefault();
            if (cancelBtn.dataset.pending === '1') return;
            cancelBtn.dataset.pending = '1';
            const span = cancelBtn.querySelector('span');
            if (span) span.textContent = lt('Cancelling...');
            const msgEl = document.getElementById('lt-fix-progress-msg');
            if (msgEl) msgEl.textContent = lt('Cancelling...');
            Millennium.callServerMethod('luatools', 'CancelApplyFix', {
                appid: appid,
                contentScriptQuery: ''
            }).then(function (res) {
                try {
                    const payload = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!payload || payload.success !== true) {
                        throw new Error((payload && payload.error) || lt('Cancellation failed'));
                    }
                } catch (err) {
                    cancelBtn.dataset.pending = '0';
                    if (span) span.textContent = lt('Cancel');
                    const msgEl2 = document.getElementById('lt-fix-progress-msg');
                    if (msgEl2 && msgEl2.dataset.last) msgEl2.textContent = msgEl2.dataset.last;
                    backendLog('LuaTools: CancelApplyFix response error: ' + err);
                    const msg = lt('Failed to cancel fix download');
                    ShowLuaToolsAlert('LuaTools', msg);
                }
            }).catch(function (err) {
                cancelBtn.dataset.pending = '0';
                const span2 = cancelBtn.querySelector('span');
                if (span2) span2.textContent = lt('Cancel');
                const msgEl2 = document.getElementById('lt-fix-progress-msg');
                if (msgEl2 && msgEl2.dataset.last) msgEl2.textContent = msgEl2.dataset.last;
                backendLog('LuaTools: CancelApplyFix error: ' + err);
                const msg = lt('Failed to cancel fix download');
                ShowLuaToolsAlert('LuaTools', msg);
            });
        };
        btnRow.appendChild(cancelBtn);

        modal.appendChild(title);
        modal.appendChild(body);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);

        // Start polling for progress
        pollFixProgress(appid, fixType);
    }

    function replaceFixButtonsWithClose(overlayEl) {
        if (!overlayEl) return;
        const btnRow = overlayEl.querySelector('.lt-fix-btn-row');
        if (!btnRow) return;
        btnRow.innerHTML = '';
        btnRow.style.cssText = 'margin-top:8px;display:flex;justify-content:flex-end;';
        const closeBtn = document.createElement('a');
        closeBtn.href = '#';
        closeBtn.className = 'luatools-btn primary';
        closeBtn.style.minWidth = '140px';
        closeBtn.innerHTML = `<span>${lt('Close')}</span>`;
        closeBtn.onclick = function (e) {
            e.preventDefault();
            overlayEl.remove();
        };
        btnRow.appendChild(closeBtn);
    }

    // Poll fix download and extraction progress
    function pollFixProgress(appid, fixType) {
        const poll = function () {
            try {
                const overlayEl = document.querySelector('.luatools-overlay');
                if (!overlayEl) return; // Stop if overlay was closed

                Millennium.callServerMethod('luatools', 'GetApplyFixStatus', {
                    appid: appid,
                    contentScriptQuery: ''
                }).then(function (res) {
                    try {
                        const payload = typeof res === 'string' ? JSON.parse(res) : res;
                        if (payload && payload.success && payload.state) {
                            const state = payload.state;
                            const msgEl = document.getElementById('lt-fix-progress-msg');

                            if (state.status === 'downloading') {
                                const pct = state.totalBytes > 0 ? Math.floor((state.bytesRead / state.totalBytes) * 100) : 0;
                                if (msgEl) {
                                    msgEl.textContent = lt('Downloading: {percent}%').replace('{percent}', pct);
                                    msgEl.dataset.last = msgEl.textContent;
                                }
                                setTimeout(poll, 500);
                            } else if (state.status === 'extracting') {
                                if (msgEl) {
                                    msgEl.textContent = lt('Extracting to game folder...');
                                    msgEl.dataset.last = msgEl.textContent;
                                }
                                setTimeout(poll, 500);
                            } else if (state.status === 'cancelled') {
                                if (msgEl) msgEl.textContent = lt('Cancelled: {reason}').replace('{reason}', state.error || lt('Cancelled by user'));
                                replaceFixButtonsWithClose(overlayEl);
                                return;
                            } else if (state.status === 'done') {
                                if (msgEl) msgEl.textContent = lt('{fix} applied successfully!').replace('{fix}', fixType);
                                replaceFixButtonsWithClose(overlayEl);
                                return; // Stop polling
                            } else if (state.status === 'failed') {
                                if (msgEl) msgEl.textContent = lt('Failed: {error}').replace('{error}', state.error || lt('Unknown error'));
                                replaceFixButtonsWithClose(overlayEl);
                                return; // Stop polling
                            } else {
                                // Continue polling for unknown states
                                setTimeout(poll, 500);
                            }
                        }
                    } catch (err) {
                        backendLog('LuaTools: GetApplyFixStatus error: ' + err);
                    }
                });
            } catch (err) {
                backendLog('LuaTools: pollFixProgress error: ' + err);
            }
        };
        setTimeout(poll, 500);
    }

    // Show un-fix progress popup
    function showUnfixProgress(appid) {
        // Remove any existing popup
        try {
            const old = document.querySelector('.luatools-unfix-overlay');
            if (old) old.remove();
        } catch (_) { }

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-unfix-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const colors = getThemeColors();
        modal.style.cssText = `background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:8px;width:400px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${colors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const title = document.createElement('div');
        const unfixTitleColors = getThemeColors();
        title.style.cssText = `font-size:13px;color:${unfixTitleColors.text};margin-bottom:10px;font-weight:700;text-shadow:0 2px 8px ${unfixTitleColors.shadow};background:${unfixTitleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        title.textContent = lt('Un-Fixing game');

        const body = document.createElement('div');
        body.style.cssText = 'font-size:15px;line-height:1.35;margin-bottom:10px;color:#c7d5e0;';
        body.innerHTML = '<div id="lt-unfix-progress-msg">' + lt('Removing fix files...') + '</div>';

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'margin-top:8px;display:flex;justify-content:center;';
        const hideBtn = document.createElement('a');
        hideBtn.href = '#';
        hideBtn.className = 'luatools-btn';
        hideBtn.style.minWidth = '140px';
        hideBtn.innerHTML = `<span>${lt('Hide')}</span>`;
        hideBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
        };
        btnRow.appendChild(hideBtn);

        modal.appendChild(title);
        modal.appendChild(body);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);

        // Start polling for progress
        pollUnfixProgress(appid);
    }

    // Poll un-fix progress
    function pollUnfixProgress(appid) {
        const poll = function () {
            try {
                const overlayEl = document.querySelector('.luatools-unfix-overlay');
                if (!overlayEl) return; // Stop if overlay was closed

                Millennium.callServerMethod('luatools', 'GetUnfixStatus', {
                    appid: appid,
                    contentScriptQuery: ''
                }).then(function (res) {
                    try {
                        const payload = typeof res === 'string' ? JSON.parse(res) : res;
                        if (payload && payload.success && payload.state) {
                            const state = payload.state;
                            const msgEl = document.getElementById('lt-unfix-progress-msg');

                            if (state.status === 'removing') {
                                if (msgEl) msgEl.textContent = state.progress || lt('Removing fix files...');
                                // Continue polling
                                setTimeout(poll, 500);
                            } else if (state.status === 'done') {
                                const filesRemoved = state.filesRemoved || 0;
                                if (msgEl) msgEl.textContent = lt('Removed {count} files. Running Steam verification...').replace('{count}', filesRemoved);
                                // Change Hide button to Close button
                                try {
                                    const btnRow = overlayEl.querySelector('div[style*="justify-content:flex-end"]');
                                    if (btnRow) {
                                        btnRow.innerHTML = '';
                                        const closeBtn = document.createElement('a');
                                        closeBtn.href = '#';
                                        closeBtn.className = 'luatools-btn primary';
                                        closeBtn.style.minWidth = '140px';
                                        closeBtn.innerHTML = `<span>${lt('Close')}</span>`;
                                        closeBtn.onclick = function (e) {
                                            e.preventDefault();
                                            overlayEl.remove();
                                        };
                                        btnRow.appendChild(closeBtn);
                                    }
                                } catch (_) { }

                                // Trigger Steam verification after a short delay
                                setTimeout(function () {
                                    try {
                                        const verifyUrl = 'steam://validate/' + appid;
                                        window.location.href = verifyUrl;
                                        backendLog('LuaTools: Running verify for appid ' + appid);
                                    } catch (_) { }
                                }, 1000);

                                return; // Stop polling
                            } else if (state.status === 'failed') {
                                if (msgEl) msgEl.textContent = lt('Failed: {error}').replace('{error}', state.error || lt('Unknown error'));
                                // Change Hide button to Close button
                                try {
                                    const btnRow = overlayEl.querySelector('div[style*="justify-content:flex-end"]');
                                    if (btnRow) {
                                        btnRow.innerHTML = '';
                                        const closeBtn = document.createElement('a');
                                        closeBtn.href = '#';
                                        closeBtn.className = 'luatools-btn primary';
                                        closeBtn.style.minWidth = '140px';
                                        closeBtn.innerHTML = `<span>${lt('Close')}</span>`;
                                        closeBtn.onclick = function (e) {
                                            e.preventDefault();
                                            overlayEl.remove();
                                        };
                                        btnRow.appendChild(closeBtn);
                                    }
                                } catch (_) { }
                                return; // Stop polling
                            } else {
                                // Continue polling for unknown states
                                setTimeout(poll, 500);
                            }
                        }
                    } catch (err) {
                        backendLog('LuaTools: GetUnfixStatus error: ' + err);
                    }
                });
            } catch (err) {
                backendLog('LuaTools: pollUnfixProgress error: ' + err);
            }
        };
        setTimeout(poll, 500);
    }

    function fetchSettingsConfig(forceRefresh) {
        try {
            if (!forceRefresh && window.__LuaToolsSettings && Array.isArray(window.__LuaToolsSettings.schema)) {
                return Promise.resolve(window.__LuaToolsSettings);
            }
        } catch (_) { }

        if (typeof Millennium === 'undefined' || typeof Millennium.callServerMethod !== 'function') {
            return Promise.reject(new Error(lt('LuaTools backend unavailable')));
        }

        return Millennium.callServerMethod('luatools', 'GetSettingsConfig', {
            contentScriptQuery: ''
        }).then(function (res) {
            const payload = typeof res === 'string' ? JSON.parse(res) : res;
            if (!payload || payload.success !== true) {
                const errorMsg = (payload && payload.error) ? String(payload.error) : t('settings.error', 'Failed to load settings.');
                throw new Error(errorMsg);
            }
            const config = {
                schemaVersion: payload.schemaVersion || 0,
                schema: Array.isArray(payload.schema) ? payload.schema : [],
                values: (payload && payload.values && typeof payload.values === 'object') ? payload.values : {},
                language: payload && payload.language ? String(payload.language) : 'en',
                locales: Array.isArray(payload && payload.locales) ? payload.locales : [],
                translations: (payload && payload.translations && typeof payload.translations === 'object') ? payload.translations : {},
                lastFetched: Date.now()
            };
            applyTranslationBundle({
                language: config.language,
                locales: config.locales,
                strings: config.translations
            });
            window.__LuaToolsSettings = config;
            return config;
        });
    }

    function initialiseSettingsDraft(config) {
        const values = JSON.parse(JSON.stringify((config && config.values) || {}));
        if (!config || !Array.isArray(config.schema)) {
            return values;
        }
        for (let i = 0; i < config.schema.length; i++) {
            const group = config.schema[i];
            if (!group || !group.key) continue;
            if (typeof values[group.key] !== 'object' || values[group.key] === null || Array.isArray(values[group.key])) {
                values[group.key] = {};
            }
            const options = Array.isArray(group.options) ? group.options : [];
            for (let j = 0; j < options.length; j++) {
                const option = options[j];
                if (!option || !option.key) continue;
                if (typeof values[group.key][option.key] === 'undefined') {
                    values[group.key][option.key] = option.default;
                }
            }
        }
        return values;
    }

    function showSettingsManagerPopup(forceRefresh, onBack) {
        if (document.querySelector('.luatools-settings-manager-overlay')) return;

        try {
            const mainOverlay = document.querySelector('.luatools-settings-overlay');
            if (mainOverlay) mainOverlay.remove();
        } catch (_) { }

        ensureLuaToolsStyles();
        ensureFontAwesome();

        const overlay = document.createElement('div');
        overlay.className = 'luatools-settings-manager-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:100000;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const settingsModalColors = getThemeColors();
        modal.style.cssText = `position:relative;background:${settingsModalColors.modalBg};color:${settingsModalColors.text};border:2px solid ${settingsModalColors.border};border-radius:8px;width:580px;max-width:95vw;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${settingsModalColors.shadowRgba};animation:slideUp 0.1s ease-out;overflow:hidden;`;

        const header = document.createElement('div');
        const settingsHeaderColors = getThemeColors();
        header.style.cssText = `display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding:14px 18px 10px;border-bottom:2px solid ${settingsHeaderColors.border.replace('0.3', '0.2')};`;

        const title = document.createElement('div');
        const settingsTitleColors = getThemeColors();
        title.style.cssText = `font-size:14px;color:${settingsTitleColors.text};font-weight:700;text-shadow:0 2px 8px ${settingsTitleColors.shadow};background:${settingsTitleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        title.textContent = t('settings.title', 'LuaTools · Settings');

        const iconButtons = document.createElement('div');
        iconButtons.style.cssText = 'display:flex;gap:6px;';

        const discordIconBtn = document.createElement('a');
        discordIconBtn.href = '#';
        const discordBtnColors = getThemeColors();
        discordIconBtn.style.cssText = `display:flex;align-items:center;justify-content:center;width:28px;height:28px;background:rgba(${discordBtnColors.rgbString},0.1);border:1px solid ${discordBtnColors.border};border-radius:10px;color:${discordBtnColors.accent};font-size:14px;text-decoration:none;transition:all 0.3s ease;cursor:pointer;`;
        discordIconBtn.innerHTML = '<i class="fa-brands fa-discord"></i>';
        discordIconBtn.title = t('menu.discord', 'Discord');
        discordIconBtn.onmouseover = function () {
            const c = getThemeColors();
            this.style.background = `rgba(${c.rgbString},0.25)`;
            this.style.transform = 'translateY(-2px) scale(1.05)';
            this.style.boxShadow = `0 8px 16px ${c.shadow}`;
            this.style.borderColor = c.accent;
        };
        discordIconBtn.onmouseout = function () {
            const c = getThemeColors();
            this.style.background = `rgba(${c.rgbString},0.1)`;
            this.style.transform = 'translateY(0) scale(1)';
            this.style.boxShadow = 'none';
            this.style.borderColor = c.border;
        };
        iconButtons.appendChild(discordIconBtn);

        const closeIconBtn = document.createElement('a');
        closeIconBtn.href = '#';
        const closeBtnColors = getThemeColors();
        closeIconBtn.style.cssText = `display:flex;align-items:center;justify-content:center;width:28px;height:28px;background:rgba(${closeBtnColors.rgbString},0.1);border:1px solid ${closeBtnColors.border};border-radius:10px;color:${closeBtnColors.accent};font-size:14px;text-decoration:none;transition:all 0.3s ease;cursor:pointer;`;
        closeIconBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        closeIconBtn.title = t('settings.close', 'Close');
        closeIconBtn.onmouseover = function () {
            const c = getThemeColors();
            this.style.background = `rgba(${c.rgbString},0.25)`;
            this.style.transform = 'translateY(-2px) scale(1.05)';
            this.style.boxShadow = `0 8px 16px ${c.shadow}`;
            this.style.borderColor = c.accent;
        };
        closeIconBtn.onmouseout = function () {
            const c = getThemeColors();
            this.style.background = `rgba(${c.rgbString},0.1)`;
            this.style.transform = 'translateY(0) scale(1)';
            this.style.boxShadow = 'none';
            this.style.borderColor = c.border;
        };
        iconButtons.appendChild(closeIconBtn);

        // Search bar container
        const searchContainer = document.createElement('div');
        const searchColors = getThemeColors();
        searchContainer.style.cssText = 'padding:0 24px 16px;';

        const searchWrap = document.createElement('div');
        searchWrap.style.cssText = `display:flex;align-items:center;gap:10px;padding:10px 14px;background:${searchColors.bgTertiary};border:1px solid ${searchColors.border};border-radius:10px;transition:all 0.2s ease;`;

        const searchIcon = document.createElement('i');
        searchIcon.className = 'fa-solid fa-magnifying-glass';
        searchIcon.style.cssText = `color:${searchColors.textSecondary};font-size:14px;`;

        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.id = 'luatools-settings-search';
        searchInput.placeholder = t('settings.search.placeholder', 'Search settings, games, fixes...');
        searchInput.style.cssText = `flex:1;background:transparent;border:none;outline:none;color:${searchColors.text};font-size:14px;`;
        searchInput.setAttribute('autocomplete', 'off');

        const searchClear = document.createElement('a');
        searchClear.href = '#';
        searchClear.style.cssText = `display:none;color:${searchColors.textSecondary};font-size:14px;text-decoration:none;padding:4px;`;
        searchClear.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        searchClear.title = t('settings.search.clear', 'Clear search');

        searchWrap.onfocus = function () {
            searchWrap.style.borderColor = searchColors.accent;
        };
        searchInput.onfocus = function () {
            const c = getThemeColors();
            searchWrap.style.borderColor = c.accent;
            searchWrap.style.boxShadow = `0 0 0 3px rgba(${c.rgbString},0.15)`;
        };
        searchInput.onblur = function () {
            const c = getThemeColors();
            searchWrap.style.borderColor = c.border;
            searchWrap.style.boxShadow = 'none';
        };

        searchWrap.appendChild(searchIcon);
        searchWrap.appendChild(searchInput);
        searchWrap.appendChild(searchClear);
        searchContainer.appendChild(searchWrap);

        const contentWrap = document.createElement('div');
        contentWrap.id = 'luatools-content-wrap';
        const contentColors = getThemeColors();
        contentWrap.style.cssText = `flex:1 1 auto;overflow-y:auto;overflow-x:hidden;padding:12px;margin:0 24px;border:1px solid ${contentColors.border};border-radius:12px;background:${contentColors.bgContainer};`;

        // Add mouse mode tip for Big Picture
        if (window.__LUATOOLS_IS_BIG_PICTURE__) {
            const tip = document.createElement('div');
            tip.style.cssText = 'background:rgba(102,192,244,0.15);border-left:3px solid #66c0f4;padding:8px 10px;border-radius:5px;font-size:11px;color:#c7d5e0;margin-bottom:16px;line-height:1.5;';
            tip.innerHTML = '<i class="fa-solid fa-info-circle" style="margin-right:8px;color:#66c0f4;"></i>' + t('bigpicture.mouseTip', 'To use mouse mode in Steam: Guide Button + Right Joystick, click with RB');
            contentWrap.appendChild(tip);
        }

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'padding:12px 16px 24px;display:flex;gap:6px;justify-content:space-between;align-items:center;';

        const backBtn = createSettingsButton('back', '<i class="fa-solid fa-arrow-left"></i>');
        const rightButtons = document.createElement('div');
        rightButtons.style.cssText = 'display:flex;gap:8px;';
        const refreshBtn = createSettingsButton('refresh', '<i class="fa-solid fa-arrow-rotate-right"></i>');
        const saveBtn = createSettingsButton('save', '<i class="fa-solid fa-floppy-disk"></i>', true);

        modal.appendChild(header);
        modal.appendChild(searchContainer);
        modal.appendChild(contentWrap);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);

        const state = {
            config: null,
            draft: {},
            searchQuery: '',
        };

        // Search functionality
        let searchDebounceTimer = null;
        searchInput.addEventListener('input', function () {
            const query = searchInput.value.trim().toLowerCase();
            searchClear.style.display = query ? 'block' : 'none';

            // Debounce the search
            if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(function () {
                state.searchQuery = query;
                applySearchFilter();
            }, 150);
        });

        searchClear.addEventListener('click', function (e) {
            e.preventDefault();
            searchInput.value = '';
            searchClear.style.display = 'none';
            state.searchQuery = '';
            applySearchFilter();
            searchInput.focus();
        });

        function applySearchFilter() {
            const query = state.searchQuery;

            // Filter settings options
            const optionEls = contentWrap.querySelectorAll('[data-setting-option]');
            optionEls.forEach(function (el) {
                const searchText = (el.dataset.searchText || '').toLowerCase();
                if (!query || searchText.includes(query)) {
                    el.style.display = '';
                } else {
                    el.style.display = 'none';
                }
            });

            // Filter settings groups (hide if all options hidden)
            const groupEls = contentWrap.querySelectorAll('[data-setting-group]');
            groupEls.forEach(function (groupEl) {
                const visibleOptions = groupEl.querySelectorAll('[data-setting-option]:not([style*="display: none"])');
                if (!query || visibleOptions.length > 0) {
                    groupEl.style.display = '';
                } else {
                    groupEl.style.display = 'none';
                }
            });

            // Filter installed fixes
            const fixItems = contentWrap.querySelectorAll('[data-fix-item]');
            let visibleFixes = 0;
            fixItems.forEach(function (el) {
                const searchText = (el.dataset.searchText || '').toLowerCase();
                if (!query || searchText.includes(query)) {
                    el.style.display = '';
                    visibleFixes++;
                } else {
                    el.style.display = 'none';
                }
            });

            // Show/hide fixes empty state
            const fixesSection = document.getElementById('luatools-installed-fixes-section');
            const fixesEmptySearch = fixesSection ? fixesSection.querySelector('.search-empty-state') : null;
            if (fixesSection && query && fixItems.length > 0 && visibleFixes === 0) {
                if (!fixesEmptySearch) {
                    const emptyEl = document.createElement('div');
                    emptyEl.className = 'search-empty-state';
                    const emptyColors = getThemeColors();
                    emptyEl.style.cssText = `padding:10px;background:${emptyColors.bgTertiary};border:1px solid ${emptyColors.border};border-radius:4px;color:${emptyColors.textSecondary};text-align:center;margin-top:10px;`;
                    emptyEl.textContent = t('settings.search.noResults', 'No matches found');
                    const listContainer = fixesSection.querySelector('#luatools-fixes-list');
                    if (listContainer) listContainer.appendChild(emptyEl);
                }
            } else if (fixesEmptySearch) {
                fixesEmptySearch.remove();
            }

            // Filter installed lua scripts
            const luaItems = contentWrap.querySelectorAll('[data-lua-item]');
            let visibleLua = 0;
            luaItems.forEach(function (el) {
                const searchText = (el.dataset.searchText || '').toLowerCase();
                if (!query || searchText.includes(query)) {
                    el.style.display = '';
                    visibleLua++;
                } else {
                    el.style.display = 'none';
                }
            });

            // Show/hide lua empty state
            const luaSection = document.getElementById('luatools-installed-lua-section');
            const luaEmptySearch = luaSection ? luaSection.querySelector('.search-empty-state') : null;
            if (luaSection && query && luaItems.length > 0 && visibleLua === 0) {
                if (!luaEmptySearch) {
                    const emptyEl = document.createElement('div');
                    emptyEl.className = 'search-empty-state';
                    const emptyColors = getThemeColors();
                    emptyEl.style.cssText = `padding:10px;background:${emptyColors.bgTertiary};border:1px solid ${emptyColors.border};border-radius:4px;color:${emptyColors.textSecondary};text-align:center;margin-top:10px;`;
                    emptyEl.textContent = t('settings.search.noResults', 'No matches found');
                    const listContainer = luaSection.querySelector('#luatools-lua-list');
                    if (listContainer) listContainer.appendChild(emptyEl);
                }
            } else if (luaEmptySearch) {
                luaEmptySearch.remove();
            }
        }

        let refreshDefaultLabel = '';
        let saveDefaultLabel = '';
        let closeDefaultLabel = '';
        let backDefaultLabel = '';

        function createSettingsButton(id, text, isPrimary) {
            const btn = document.createElement('a');
            btn.id = 'lt-settings-' + id;
            btn.href = '#';
            btn.innerHTML = '<span>' + text + '</span>';

            btn.className = 'luatools-btn';
            if (isPrimary) {
                btn.classList.add('primary');
            }

            btn.onmouseover = function () {
                if (this.dataset.disabled === '1') {
                    this.style.opacity = '0.6';
                    this.style.cursor = 'not-allowed';
                    return;
                }
            };

            btn.onmouseout = function () {
                if (this.dataset.disabled === '1') {
                    this.style.opacity = '0.5';
                    return;
                }
            };

            if (isPrimary) {
                btn.dataset.disabled = '1';
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
            }

            return btn;
        }

        header.appendChild(title);
        header.appendChild(iconButtons);

        function applyStaticTranslations() {
            title.textContent = t('settings.title', 'LuaTools · Settings');
            refreshBtn.title = t('settings.refresh', 'Refresh');
            saveBtn.title = t('settings.save', 'Save Settings');
            backBtn.title = t('Back', 'Back');
            discordIconBtn.title = t('menu.discord', 'Discord');
            closeIconBtn.title = t('settings.close', 'Close');
        }
        applyStaticTranslations();

        function setStatus(text, color) {
            let statusLine = contentWrap.querySelector('.luatools-settings-status');
            if (!statusLine) {
                statusLine = document.createElement('div');
                statusLine.className = 'luatools-settings-status';
                statusLine.style.cssText = 'font-size:13px;margin-top:10px;transform:translateY(15px);color:#c7d5e0;min-height:18px;text-align:center;'; // may god have mercy upon your soul for witnessing this translateY
                contentWrap.insertBefore(statusLine, contentWrap.firstChild);
            }
            statusLine.textContent = text || '';
            statusLine.style.color = color || '#c7d5e0';
        }

        function ensureDraftGroup(groupKey) {
            if (!state.draft[groupKey] || typeof state.draft[groupKey] !== 'object') {
                state.draft[groupKey] = {};
            }
            return state.draft[groupKey];
        }

        function collectChanges() {
            if (!state.config || !Array.isArray(state.config.schema)) {
                return {};
            }
            const changes = {};
            for (let i = 0; i < state.config.schema.length; i++) {
                const group = state.config.schema[i];
                if (!group || !group.key) continue;
                const options = Array.isArray(group.options) ? group.options : [];
                const draftGroup = state.draft[group.key] || {};
                const originalGroup = (state.config.values && state.config.values[group.key]) || {};
                const groupChanges = {};
                for (let j = 0; j < options.length; j++) {
                    const option = options[j];
                    if (!option || !option.key) continue;
                    const newValue = draftGroup.hasOwnProperty(option.key) ? draftGroup[option.key] : option.default;
                    const oldValue = originalGroup.hasOwnProperty(option.key) ? originalGroup[option.key] : option.default;
                    if (newValue !== oldValue) {
                        groupChanges[option.key] = newValue;
                    }
                }
                if (Object.keys(groupChanges).length > 0) {
                    changes[group.key] = groupChanges;
                }
            }
            return changes;
        }

        function updateSaveState() {
            const hasChanges = Object.keys(collectChanges()).length > 0;
            const isBusy = saveBtn.dataset.busy === '1';
            if (hasChanges && !isBusy) {
                saveBtn.dataset.disabled = '0';
                saveBtn.style.opacity = '';
                saveBtn.style.cursor = 'pointer';
            } else {
                saveBtn.dataset.disabled = '1';
                saveBtn.style.opacity = '0.6';
                saveBtn.style.cursor = 'not-allowed';
            }
        }

        function optionLabelKey(groupKey, optionKey) {
            if (groupKey === 'general') {
                if (optionKey === 'language') return 'settings.language.label';
                if (optionKey === 'useSteamLanguage') return 'settings.useSteamLanguage.label';
                if (optionKey === 'donateKeys') return 'settings.donateKeys.label';
                if (optionKey === 'theme') return 'settings.theme.label';
            }
            return null;
        }

        function optionDescriptionKey(groupKey, optionKey) {
            if (groupKey === 'general') {
                if (optionKey === 'language') return 'settings.language.description';
                if (optionKey === 'useSteamLanguage') return 'settings.useSteamLanguage.description';
                if (optionKey === 'donateKeys') return 'settings.donateKeys.description';
                if (optionKey === 'theme') return 'settings.theme.description';
            }
            return null;
        }

        function renderSettings() {
            contentWrap.innerHTML = '';
            if (!state.config || !Array.isArray(state.config.schema) || state.config.schema.length === 0) {
                const emptyState = document.createElement('div');
                const emptyColors = getThemeColors();
                emptyState.style.cssText = `padding:10px;background:${emptyColors.bgTertiary};border:1px solid ${emptyColors.border};border-radius:4px;color:${emptyColors.textSecondary};`;
                emptyState.textContent = t('settings.empty', 'No settings available yet.');
                contentWrap.appendChild(emptyState);
                updateSaveState();
                return;
            }

            for (let i = 0; i < state.config.schema.length; i++) {
                const group = state.config.schema[i];
                if (!group || !group.key) continue;

                const groupEl = document.createElement('div');
                groupEl.style.cssText = 'margin-bottom:10px;';
                groupEl.dataset.settingGroup = group.key;

                const groupTitle = document.createElement('div');
                groupTitle.textContent = t('settings.' + group.key, group.label || group.key);
                if (group.key === 'general') {
                    const generalTitleColors = getThemeColors();
                    groupTitle.style.cssText = `font-size:13px;color:${generalTitleColors.text};margin-bottom:10px;margin-top:-20px;font-weight:600;text-align:center;`; // dw abt this margin-top -25px 🇧🇷 don't even look at it
                } else {
                    const otherTitleColors = getThemeColors();
                    groupTitle.style.cssText = `font-size:13px;font-weight:600;color:${otherTitleColors.accent};text-align:center;`;
                }
                groupEl.appendChild(groupTitle);

                if (group.description && group.key !== 'general') {
                    const groupDesc = document.createElement('div');
                    const descColors = getThemeColors();
                    groupDesc.style.cssText = `margin-top:4px;font-size:13px;color:${descColors.textSecondary};`;
                    groupDesc.textContent = t('settings.' + group.key + 'Description', group.description);
                    groupEl.appendChild(groupDesc);
                }

                const options = Array.isArray(group.options) ? group.options : [];
                for (let j = 0; j < options.length; j++) {
                    const option = options[j];
                    if (!option || !option.key) continue;

                    ensureDraftGroup(group.key);
                    if (!state.draft[group.key].hasOwnProperty(option.key)) {
                        const sourceGroup = (state.config.values && state.config.values[group.key]) || {};
                        const initialValue = sourceGroup.hasOwnProperty(option.key) ? sourceGroup[option.key] : option.default;
                        state.draft[group.key][option.key] = initialValue;
                    }

                    const optionEl = document.createElement('div');
                    const optionColors = getThemeColors();
                    if (j === 0) {
                        optionEl.style.cssText = 'margin-top:4px;padding-top:0;';
                    } else {
                        optionEl.style.cssText = `margin-top:8px;padding-top:12px;border-top:1px solid ${optionColors.border.replace('0.3', '0.1')};`;
                    }
                    optionEl.dataset.settingOption = option.key;

                    const optionLabel = document.createElement('div');
                    const optLabelColors = getThemeColors();
                    optionLabel.style.cssText = `font-size:12px;font-weight:500;color:${optLabelColors.text};`;
                    const labelKey = optionLabelKey(group.key, option.key);
                    const labelText = t(labelKey || ('settings.' + group.key + '.' + option.key + '.label'), option.label || option.key);
                    optionLabel.textContent = labelText;

                    // Build search text from label, description, and key
                    const descText = option.description || '';
                    optionEl.dataset.searchText = (labelText + ' ' + descText + ' ' + option.key + ' ' + group.key).toLowerCase();
                    optionEl.appendChild(optionLabel);

                    if (option.description) {
                        const optionDesc = document.createElement('div');
                        const optDescColors = getThemeColors();
                        optionDesc.style.cssText = `margin-top:2px;font-size:12px;color:${optDescColors.textSecondary};`;
                        const descKey = optionDescriptionKey(group.key, option.key);
                        optionDesc.textContent = t(descKey || ('settings.' + group.key + '.' + option.key + '.description'), option.description);
                        optionEl.appendChild(optionDesc);
                    }

                    const controlWrap = document.createElement('div');
                    controlWrap.style.cssText = 'margin-top:5px;';

                    if (option.type === 'select') {
                        const selectEl = document.createElement('select');
                        const selectColors = getThemeColors();
                        selectEl.style.cssText = `width:100% !important;padding:6px 8px !important;background:${selectColors.bgTertiary} !important;color:${selectColors.text} !important;border:1px solid ${selectColors.border} !important;border-radius:3px !important;font-size:14px !important;`;

                        const choices = Array.isArray(option.choices) ? option.choices : [];
                        for (let c = 0; c < choices.length; c++) {
                            const choice = choices[c];
                            if (!choice) continue;
                            const choiceOption = document.createElement('option');
                            choiceOption.value = String(choice.value);
                            choiceOption.textContent = choice.label || choice.value;
                            selectEl.appendChild(choiceOption);
                        }

                        const currentValue = state.draft[group.key][option.key];
                        if (typeof currentValue !== 'undefined') {
                            selectEl.value = String(currentValue);
                        }

                        selectEl.addEventListener('change', function () {
                            state.draft[group.key][option.key] = selectEl.value;
                            try {
                                backendLog('LuaTools: ' + option.key + ' select changed to ' + selectEl.value);
                            } catch (_) { }

                            // If theme changed, apply it immediately
                            if (group.key === 'general' && option.key === 'theme') {
                                try {
                                    backendLog('LuaTools: Theme change detected, new value: ' + selectEl.value);
                                } catch (_) { }
                                // Update the settings cache so getCurrentTheme() returns the new value
                                if (window.__LuaToolsSettings && window.__LuaToolsSettings.values) {
                                    if (!window.__LuaToolsSettings.values.general) {
                                        window.__LuaToolsSettings.values.general = {};
                                    }
                                    window.__LuaToolsSettings.values.general.theme = selectEl.value;
                                    try {
                                        backendLog('LuaTools: Updated cache, theme is now: ' + window.__LuaToolsSettings.values.general.theme);
                                    } catch (_) { }
                                }
                                // Reload styles immediately
                                ensureLuaToolsStyles();

                                // Update all modal elements with new theme colors
                                setTimeout(function () {
                                    const colors = getThemeColors();

                                    // Update modal background and border
                                    const modalEl = overlay && overlay.querySelector('[style*="background:linear-gradient"]');
                                    if (modalEl) {
                                        modalEl.style.background = colors.modalBg;
                                        modalEl.style.borderColor = colors.border;
                                    }

                                    // Update header border
                                    const headerEl = overlay && overlay.querySelector('[style*="border-bottom"]');
                                    if (headerEl) {
                                        headerEl.style.borderBottomColor = colors.border.replace('0.3', '0.2');
                                    }

                                    // Update all title and text colors
                                    const titles = overlay && overlay.querySelectorAll('[style*="text-shadow"]');
                                    if (titles) {
                                        titles.forEach(function (title) {
                                            title.style.backgroundImage = colors.gradientLight;
                                        });
                                    }

                                    // Update content wrapper border
                                    const contentWrapEl = overlay && overlay.querySelector('#luatools-content-wrap');
                                    if (contentWrapEl) {
                                        contentWrapEl.style.borderColor = colors.border;
                                        contentWrapEl.style.background = colors.bgContainer;
                                    }

                                    // Re-render the settings content
                                    renderSettings();
                                }, 50);

                                // Auto-save theme changes after a brief delay
                                setTimeout(function () {
                                    if (saveBtn && saveBtn.dataset.disabled !== '1' && saveBtn.dataset.busy !== '1') {
                                        saveBtn.click();
                                    }
                                }, 150);
                            }

                            updateSaveState();
                            setStatus(t('settings.unsaved', 'Unsaved changes'), '#c7d5e0');
                        });

                        controlWrap.appendChild(selectEl);
                    } else if (option.type === 'toggle') {
                        const toggleWrap = document.createElement('div');
                        toggleWrap.style.cssText = 'display:flex;gap:10px;flex-wrap:wrap;';

                        let yesLabel = option.metadata && option.metadata.yesLabel ? String(option.metadata.yesLabel) : 'Yes';
                        let noLabel = option.metadata && option.metadata.noLabel ? String(option.metadata.noLabel) : 'No';
                        if (group.key === 'general' && option.key === 'donateKeys') {
                            yesLabel = t('settings.donateKeys.yes', yesLabel);
                            noLabel = t('settings.donateKeys.no', noLabel);
                        }

                        const yesBtn = document.createElement('a');
                        yesBtn.className = 'btnv6_blue_hoverfade btn_small';
                        yesBtn.href = '#';
                        yesBtn.innerHTML = '<span>' + yesLabel + '</span>';

                        const noBtn = document.createElement('a');
                        noBtn.className = 'btnv6_blue_hoverfade btn_small';
                        noBtn.href = '#';
                        noBtn.innerHTML = '<span>' + noLabel + '</span>';

                        const yesSpan = yesBtn.querySelector('span');
                        const noSpan = noBtn.querySelector('span');

                        function refreshToggleButtons() {
                            const toggleColors = getThemeColors();
                            const currentValue = state.draft[group.key][option.key] === true;
                            if (currentValue) {
                                yesBtn.style.background = toggleColors.accent;
                                yesBtn.style.color = toggleColors.bgPrimary;
                                if (yesSpan) yesSpan.style.color = toggleColors.bgPrimary;
                                noBtn.style.background = '';
                                noBtn.style.color = '';
                                if (noSpan) noSpan.style.color = '';
                            } else {
                                noBtn.style.background = toggleColors.accent;
                                noBtn.style.color = toggleColors.bgPrimary;
                                if (noSpan) noSpan.style.color = toggleColors.bgPrimary;
                                yesBtn.style.background = '';
                                yesBtn.style.color = '';
                                if (yesSpan) yesSpan.style.color = '';
                            }
                        }

                        yesBtn.addEventListener('click', function (e) {
                            e.preventDefault();
                            state.draft[group.key][option.key] = true;
                            refreshToggleButtons();
                            updateSaveState();
                            if (option.key === 'useSteamLanguage') refreshDependencies();
                            setStatus(t('settings.unsaved', 'Unsaved changes'), '#c7d5e0');
                        });

                        noBtn.addEventListener('click', function (e) {
                            e.preventDefault();
                            state.draft[group.key][option.key] = false;
                            refreshToggleButtons();
                            updateSaveState();
                            if (option.key === 'useSteamLanguage') refreshDependencies();
                            setStatus(t('settings.unsaved', 'Unsaved changes'), '#c7d5e0');
                        });

                        toggleWrap.appendChild(yesBtn);
                        toggleWrap.appendChild(noBtn);
                        controlWrap.appendChild(toggleWrap);
                        refreshToggleButtons();
                    } else if (option.type === 'text') {
                        const textInput = document.createElement('input');
                        textInput.type = 'text';
                        const textColors = getThemeColors();
                        const placeholder = option.metadata && option.metadata.placeholder ? String(option.metadata.placeholder) : '';
                        textInput.placeholder = placeholder;
                        textInput.style.cssText = `width:100% !important;padding:8px 12px !important;background:${textColors.bgTertiary} !important;color:${textColors.text} !important;border:1px solid ${textColors.border} !important;border-radius:4px !important;font-size:14px !important;box-sizing:border-box !important;`;

                        const currentValue = state.draft[group.key][option.key];
                        if (typeof currentValue !== 'undefined' && currentValue !== null) {
                            textInput.value = String(currentValue);
                        }

                        textInput.addEventListener('input', function () {
                            state.draft[group.key][option.key] = textInput.value;
                            updateSaveState();
                            setStatus(t('settings.unsaved', 'Unsaved changes'), '#c7d5e0');
                        });

                        textInput.addEventListener('focus', function () {
                            textInput.style.borderColor = textColors.accent + ' !important';
                            textInput.style.outline = 'none';
                        });

                        textInput.addEventListener('blur', function () {
                            textInput.style.borderColor = textColors.border + ' !important';
                        });

                        controlWrap.appendChild(textInput);
                    } else {
                        const unsupported = document.createElement('div');
                        unsupported.style.cssText = 'font-size:12px;color:#ffb347;';
                        unsupported.textContent = lt('common.error.unsupportedOption').replace('{type}', option.type);
                        controlWrap.appendChild(unsupported);
                    }

                    optionEl.appendChild(controlWrap);
                    groupEl.appendChild(optionEl);
                }

                contentWrap.appendChild(groupEl);
            }

            // Render Installed Fixes section
            renderInstalledFixesSection();

            // Render Installed Lua Scripts section
            renderInstalledLuaSection();

            updateSaveState();
            refreshDependencies();
        }

        function refreshDependencies() {
            try {
                const languageEl = overlay.querySelector('[data-setting-option="language"]');
                if (languageEl) {
                    const useSteam = state.draft && state.draft.general && state.draft.general.useSteamLanguage;
                    if (useSteam !== false) {
                        languageEl.style.display = 'none';
                    } else {
                        languageEl.style.display = 'block';
                    }
                }
            } catch (_) { }
        }

        function renderInstalledFixesSection() {
            const sectionEl = document.createElement('div');
            sectionEl.id = 'luatools-installed-fixes-section';
            const sectionColors = getThemeColors();
            sectionEl.style.cssText = `margin-top:36px;padding:14px;background:linear-gradient(135deg, rgba(${sectionColors.rgbString},0.05) 0%, rgba(${sectionColors.rgbString},0.08) 100%);border:2px solid ${sectionColors.border};border-radius:14px;box-shadow:0 4px 15px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05);position:relative;overflow:hidden;`;

            const sectionGlow = document.createElement('div');
            sectionGlow.style.cssText = `position:absolute;top:-100%;left:-100%;width:300%;height:300%;background:radial-gradient(circle, rgba(${sectionColors.rgbString},0.08) 0%, transparent 70%);pointer-events:none;`;
            sectionEl.appendChild(sectionGlow);

            const sectionTitle = document.createElement('div');
            const titleColors = getThemeColors();
            sectionTitle.style.cssText = `font-size:13px;color:${titleColors.accent};margin-bottom:12px;font-weight:700;text-align:center;text-shadow:0 2px 10px ${titleColors.shadow};background:${titleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;position:relative;z-index:1;letter-spacing:0.5px;`;
            sectionTitle.innerHTML = '<i class="fa-solid fa-wrench" style="margin-right:10px;"></i>' + t('settings.installedFixes.title', 'Installed Fixes');
            sectionEl.appendChild(sectionTitle);

            const listContainer = document.createElement('div');
            listContainer.id = 'luatools-fixes-list';
            listContainer.style.cssText = 'min-height:50px;';
            sectionEl.appendChild(listContainer);

            contentWrap.appendChild(sectionEl);

            loadInstalledFixes(listContainer);
        }

        function loadInstalledFixes(container) {
            const loadingColors = getThemeColors();
            container.innerHTML = `<div style="padding:10px;text-align:center;color:${loadingColors.textSecondary};">${t('settings.installedFixes.loading', 'Scanning for installed fixes...')}</div>`;

            Millennium.callServerMethod('luatools', 'GetInstalledFixes', {
                contentScriptQuery: ''
            })
                .then(function (res) {
                    const response = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!response || !response.success) {
                        const errColors = getThemeColors();
                        container.innerHTML = `<div style="padding:10px;background:${errColors.bgTertiary};border:1px solid #ff5c5c;border-radius:4px;color:#ff5c5c;">${t('settings.installedFixes.error', 'Failed to load installed fixes.')}</div>`;
                        return;
                    }

                    const fixes = Array.isArray(response.fixes) ? response.fixes : [];
                    if (fixes.length === 0) {
                        const emptyColors = getThemeColors();
                        container.innerHTML = `<div style="padding:10px;background:${emptyColors.bgTertiary};border:1px solid ${emptyColors.border};border-radius:4px;color:${emptyColors.textSecondary};text-align:center;">${t('settings.installedFixes.empty', 'No fixes installed yet.')}</div>`;
                        return;
                    }

                    container.innerHTML = '';
                    for (let i = 0; i < fixes.length; i++) {
                        const fix = fixes[i];
                        const fixEl = createFixListItem(fix, container);
                        container.appendChild(fixEl);
                    }

                    // Re-apply search filter after loading
                    if (state.searchQuery) {
                        setTimeout(applySearchFilter, 50);
                    }
                })
                .catch(function (err) {
                    const catchColors = getThemeColors();
                    container.innerHTML = `<div style="padding:10px;background:${catchColors.bgTertiary};border:1px solid #ff5c5c;border-radius:4px;color:#ff5c5c;">${t('settings.installedFixes.error', 'Failed to load installed fixes.')}</div>`;
                });
        }

        function createFixListItem(fix, container) {
            const itemEl = document.createElement('div');
            const itemColors = getThemeColors();
            itemEl.style.cssText = `margin-bottom:8px;padding:10px;background:${itemColors.bgTertiary};border:1px solid ${itemColors.border};border-radius:6px;display:flex;justify-content:space-between;align-items:center;transition:all 0.2s ease;`;
            itemEl.onmouseover = function () {
                const c = getThemeColors();
                this.style.borderColor = c.accent;
                this.style.background = c.bgHover;
            };
            itemEl.onmouseout = function () {
                const c = getThemeColors();
                this.style.borderColor = c.border;
                this.style.background = c.bgTertiary;
            };

            // Add search data attributes
            itemEl.dataset.fixItem = fix.appid;
            const gameNameText = fix.gameName || 'Unknown Game';
            itemEl.dataset.searchText = (gameNameText + ' ' + fix.appid + ' ' + (fix.fixType || '') + ' fix').toLowerCase();

            const infoDiv = document.createElement('div');
            infoDiv.style.cssText = 'flex:1;';

            const gameName = document.createElement('div');
            const nameColors = getThemeColors();
            gameName.style.cssText = `font-size:15px;font-weight:600;color:${nameColors.text};margin-bottom:6px;`;
            gameName.textContent = gameNameText + (fix.gameName ? '' : ' (' + fix.appid + ')');
            infoDiv.appendChild(gameName);

            if (!fix.gameName || fix.gameName.startsWith('Unknown Game')) {
                fetchSteamGameName(fix.appid).then(function (name) {
                    if (name) {
                        fix.gameName = name;
                        gameName.textContent = name;
                        itemEl.dataset.searchText = (name + ' ' + fix.appid + ' ' + (fix.fixType || '') + ' fix').toLowerCase();
                    }
                });
            }

            const detailsDiv = document.createElement('div');
            const detailsColors = getThemeColors();
            detailsDiv.style.cssText = `font-size:12px;color:${detailsColors.textSecondary};line-height:1.35;`;

            if (fix.fixType) {
                const typeSpan = document.createElement('div');
                const typeColors = getThemeColors();
                typeSpan.innerHTML = `<strong style="color:${typeColors.accent};">${t('settings.installedFixes.type', 'Type:')}</strong> ${fix.fixType}`;
                detailsDiv.appendChild(typeSpan);
            }

            if (fix.date) {
                const dateSpan = document.createElement('div');
                const dateColors = getThemeColors();
                dateSpan.innerHTML = `<strong style="color:${dateColors.accent};">${t('settings.installedFixes.date', 'Installed:')}</strong> ${fix.date}`;
                detailsDiv.appendChild(dateSpan);
            }

            if (fix.filesCount > 0) {
                const filesSpan = document.createElement('div');
                const filesColors = getThemeColors();
                filesSpan.innerHTML = `<strong style="color:${filesColors.accent};">${t('settings.installedFixes.files', '{count} files').replace('{count}', fix.filesCount)}</strong>`;
                detailsDiv.appendChild(filesSpan);
            }

            infoDiv.appendChild(detailsDiv);
            itemEl.appendChild(infoDiv);

            const deleteBtn = document.createElement('a');
            deleteBtn.href = '#';
            deleteBtn.style.cssText = 'display:flex;align-items:center;justify-content:center;width:44px;height:44px;background:rgba(255,80,80,0.12);border:2px solid rgba(255,80,80,0.35);border-radius:12px;color:#ff5050;font-size:14px;text-decoration:none;transition:all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);cursor:pointer;flex-shrink:0;';
            deleteBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
            deleteBtn.title = t('settings.installedFixes.delete', 'Delete');
            deleteBtn.onmouseover = function () {
                this.style.background = 'rgba(255,80,80,0.25)';
                this.style.borderColor = 'rgba(255,80,80,0.6)';
                this.style.color = '#ff6b6b';
                this.style.transform = 'translateY(-2px) scale(1.05)';
                this.style.boxShadow = '0 6px 20px rgba(255,80,80,0.4), 0 0 0 4px rgba(255,80,80,0.1)';
            };
            deleteBtn.onmouseout = function () {
                this.style.background = 'rgba(255,80,80,0.12)';
                this.style.borderColor = 'rgba(255,80,80,0.35)';
                this.style.color = '#ff5050';
                this.style.transform = 'translateY(0) scale(1)';
                this.style.boxShadow = 'none';
            };

            deleteBtn.addEventListener('click', function (e) {
                e.preventDefault();
                if (deleteBtn.dataset.busy === '1') return;

                showLuaToolsConfirm(
                    fix.gameName || 'LuaTools',
                    t('settings.installedFixes.deleteConfirm', 'Are you sure you want to remove this fix? This will delete fix files and run Steam verification.'),
                    function () {
                        // User confirmed
                        deleteBtn.dataset.busy = '1';
                        deleteBtn.style.opacity = '0.6';
                        deleteBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

                        Millennium.callServerMethod('luatools', 'UnFixGame', {
                            appid: fix.appid,
                            installPath: fix.installPath || '',
                            fixDate: fix.date || '',
                            contentScriptQuery: ''
                        })
                            .then(function (res) {
                                const response = typeof res === 'string' ? JSON.parse(res) : res;
                                if (!response || !response.success) {
                                    alert(t('settings.installedFixes.deleteError', 'Failed to remove fix.'));
                                    deleteBtn.dataset.busy = '0';
                                    deleteBtn.style.opacity = '1';
                                    deleteBtn.innerHTML = '<span><i class="fa-solid fa-trash"></i> ' + t('settings.installedFixes.delete', 'Delete') + '</span>';
                                    return;
                                }

                                // Poll for unfix status
                                pollUnfixStatus(fix.appid, itemEl, deleteBtn, container);
                            })
                            .catch(function (err) {
                                alert(t('settings.installedFixes.deleteError', 'Failed to remove fix.') + ' ' + (err && err.message ? err.message : ''));
                                deleteBtn.dataset.busy = '0';
                                deleteBtn.style.opacity = '1';
                                deleteBtn.innerHTML = '<span><i class="fa-solid fa-trash"></i> ' + t('settings.installedFixes.delete', 'Delete') + '</span>';
                            });
                    },
                    function () {
                        // User cancelled - do nothing
                    }
                );
            });

            itemEl.appendChild(deleteBtn);
            return itemEl;
        }

        function pollUnfixStatus(appid, itemEl, deleteBtn, container) {
            let pollCount = 0;
            const maxPolls = 60;

            function checkStatus() {
                if (pollCount >= maxPolls) {
                    alert(t('settings.installedFixes.deleteError', 'Failed to remove fix.') + ' (Timeout)');
                    deleteBtn.dataset.busy = '0';
                    deleteBtn.style.opacity = '1';
                    deleteBtn.innerHTML = '<span><i class="fa-solid fa-trash"></i> ' + t('settings.installedFixes.delete', 'Delete') + '</span>';
                    return;
                }

                pollCount++;

                Millennium.callServerMethod('luatools', 'GetUnfixStatus', {
                    appid: appid,
                    contentScriptQuery: ''
                })
                    .then(function (res) {
                        const response = typeof res === 'string' ? JSON.parse(res) : res;
                        if (!response || !response.success) {
                            setTimeout(checkStatus, 500);
                            return;
                        }

                        const state = response.state || {};
                        const status = state.status;

                        if (status === 'done' && state.success) {
                            // Success - remove item from list with animation
                            itemEl.style.transition = 'all 0.3s ease';
                            itemEl.style.opacity = '0';
                            itemEl.style.transform = 'translateX(-20px)';
                            setTimeout(function () {
                                itemEl.remove();
                                // Check if list is now empty
                                if (container.children.length === 0) {
                                    const emptyFixesColors = getThemeColors();
                                    container.innerHTML = `<div style="padding:10px;background:${emptyFixesColors.bgTertiary};border:1px solid ${emptyFixesColors.border};border-radius:4px;color:${emptyFixesColors.textSecondary};text-align:center;">${t('settings.installedFixes.empty', 'No fixes installed yet.')}</div>`;
                                }
                            }, 300);

                            // Trigger Steam verification after a short delay
                            setTimeout(function () {
                                try {
                                    const verifyUrl = 'steam://validate/' + appid;
                                    window.location.href = verifyUrl;
                                    backendLog('LuaTools: Running verify for appid ' + appid);
                                } catch (_) { }
                            }, 1000);

                            return;
                        } else if (status === 'failed' || (status === 'done' && !state.success)) {
                            alert(t('settings.installedFixes.deleteError', 'Failed to remove fix.') + ' ' + (state.error || ''));
                            deleteBtn.dataset.busy = '0';
                            deleteBtn.style.opacity = '1';
                            deleteBtn.innerHTML = '<span><i class="fa-solid fa-trash"></i> ' + t('settings.installedFixes.delete', 'Delete') + '</span>';
                            return;
                        } else {
                            // Still in progress
                            setTimeout(checkStatus, 500);
                        }
                    })
                    .catch(function (err) {
                        setTimeout(checkStatus, 500);
                    });
            }

            checkStatus();
        }

        function renderInstalledLuaSection() {
            const sectionEl = document.createElement('div');
            sectionEl.id = 'luatools-installed-lua-section';
            const sectionLuaColors = getThemeColors();
            sectionEl.style.cssText = `margin-top:36px;padding:14px;background:linear-gradient(135deg, rgba(${sectionLuaColors.rgbString},0.05) 0%, rgba(${sectionLuaColors.rgbString},0.08) 100%);border:2px solid ${sectionLuaColors.border};border-radius:14px;box-shadow:0 4px 15px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05);position:relative;overflow:hidden;`;

            const sectionGlow = document.createElement('div');
            sectionGlow.style.cssText = `position:absolute;top:-100%;left:-100%;width:300%;height:300%;background:radial-gradient(circle, rgba(${sectionLuaColors.rgbString},0.08) 0%, transparent 70%);pointer-events:none;`;
            sectionEl.appendChild(sectionGlow);

            const sectionTitle = document.createElement('div');
            const luaTitleColors = getThemeColors();
            sectionTitle.style.cssText = `font-size:13px;color:${luaTitleColors.accent};margin-bottom:12px;font-weight:700;text-align:center;text-shadow:0 2px 10px ${luaTitleColors.shadow};background:${luaTitleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;position:relative;z-index:1;letter-spacing:0.5px;`;
            sectionTitle.innerHTML = '<i class="fa-solid fa-code" style="margin-right:10px;"></i>' + t('settings.installedLua.title', 'Installed Lua Scripts');
            sectionEl.appendChild(sectionTitle);

            const listContainer = document.createElement('div');
            listContainer.id = 'luatools-lua-list';
            listContainer.style.cssText = 'min-height:50px;';
            sectionEl.appendChild(listContainer);

            contentWrap.appendChild(sectionEl);

            loadInstalledLuaScripts(listContainer);
        }

        function loadInstalledLuaScripts(container) {
            container.innerHTML = '<div style="padding:10px;text-align:center;color:#c7d5e0;">' + t('settings.installedLua.loading', 'Scanning for installed Lua scripts...') + '</div>';

            Millennium.callServerMethod('luatools', 'GetInstalledLuaScripts', {
                contentScriptQuery: ''
            })
                .then(function (res) {
                    const response = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!response || !response.success) {
                        const errLuaColors = getThemeColors();
                        container.innerHTML = `<div style="padding:10px;background:${errLuaColors.bgTertiary};border:1px solid #ff5c5c;border-radius:4px;color:#ff5c5c;">${t('settings.installedLua.error', 'Failed to load installed Lua scripts.')}</div>`;
                        return;
                    }

                    const scripts = Array.isArray(response.scripts) ? response.scripts : [];
                    if (scripts.length === 0) {
                        const emptyLuaColors = getThemeColors();
                        container.innerHTML = `<div style="padding:10px;background:${emptyLuaColors.bgTertiary};border:1px solid ${emptyLuaColors.border};border-radius:4px;color:${emptyLuaColors.textSecondary};text-align:center;">${t('settings.installedLua.empty', 'No Lua scripts installed yet.')}</div>`;
                        return;
                    }

                    container.innerHTML = '';

                    // Check if there are any unknown games
                    const hasUnknownGames = scripts.some(function (s) {
                        return s.gameName && s.gameName.startsWith('Unknown Game');
                    });

                    // Show info banner if there are unknown games
                    if (hasUnknownGames) {
                        const infoBanner = document.createElement('div');
                        infoBanner.style.cssText = 'margin-bottom:10px;padding:8px 10px;background:rgba(255,193,7,0.1);border:1px solid rgba(255,193,7,0.3);border-radius:6px;color:#ffc107;font-size:13px;display:flex;align-items:center;gap:10px;';
                        infoBanner.innerHTML = '<i class="fa-solid fa-circle-info" style="font-size:16px;"></i><span>' + t('settings.installedLua.unknownInfo', 'Games showing \'Unknown Game\' were installed manually (not via LuaTools).') + '</span>';
                        container.appendChild(infoBanner);
                    }

                    for (let i = 0; i < scripts.length; i++) {
                        const script = scripts[i];
                        const scriptEl = createLuaListItem(script, container);
                        container.appendChild(scriptEl);
                    }

                    // Re-apply search filter after loading
                    if (state.searchQuery) {
                        setTimeout(applySearchFilter, 50);
                    }
                })
                .catch(function (err) {
                    const catchLuaColors = getThemeColors();
                    container.innerHTML = `<div style="padding:10px;background:${catchLuaColors.bgTertiary};border:1px solid #ff5c5c;border-radius:4px;color:#ff5c5c;">${t('settings.installedLua.error', 'Failed to load installed Lua scripts.')}</div>`;
                });
        }

        function createLuaListItem(script, container) {
            const itemEl = document.createElement('div');
            const itemLuaColors = getThemeColors();
            itemEl.style.cssText = `margin-bottom:8px;padding:10px;background:${itemLuaColors.bgTertiary};border:1px solid ${itemLuaColors.border};border-radius:6px;display:flex;justify-content:space-between;align-items:center;transition:all 0.2s ease;`;
            itemEl.onmouseover = function () {
                const c = getThemeColors();
                this.style.borderColor = c.accent;
                this.style.background = c.bgHover;
            };
            itemEl.onmouseout = function () {
                const c = getThemeColors();
                this.style.borderColor = c.border;
                this.style.background = c.bgTertiary;
            };

            // Add search data attributes
            itemEl.dataset.luaItem = script.appid;
            const gameNameText = script.gameName || 'Unknown Game';
            itemEl.dataset.searchText = (gameNameText + ' ' + script.appid + ' lua script' + (script.isDisabled ? ' disabled' : '')).toLowerCase();

            const infoDiv = document.createElement('div');
            infoDiv.style.cssText = 'flex:1;';

            const gameName = document.createElement('div');
            const gameNameLuaColors = getThemeColors();
            gameName.style.cssText = `font-size:15px;font-weight:600;color:${gameNameLuaColors.text};margin-bottom:6px;`;
            gameName.textContent = gameNameText + (script.gameName ? '' : ' (' + script.appid + ')');

            if (!script.gameName || script.gameName.startsWith('Unknown Game')) {
                fetchSteamGameName(script.appid).then(function (name) {
                    if (name) {
                        script.gameName = name;
                        gameName.textContent = name;
                        itemEl.dataset.searchText = (name + ' ' + script.appid + ' lua script' + (script.isDisabled ? ' disabled' : '')).toLowerCase();
                    }
                });
            }

            if (script.isDisabled) {
                const disabledBadge = document.createElement('span');
                disabledBadge.style.cssText = 'margin-left:8px;padding:2px 8px;background:rgba(255,92,92,0.2);border:1px solid #ff5c5c;border-radius:4px;font-size:11px;color:#ff5c5c;font-weight:500;';
                disabledBadge.textContent = t('settings.installedLua.disabled', 'Disabled');
                gameName.appendChild(disabledBadge);
            }

            infoDiv.appendChild(gameName);

            const detailsDiv = document.createElement('div');
            const detailsLuaColors = getThemeColors();
            detailsDiv.style.cssText = `font-size:12px;color:${detailsLuaColors.textSecondary};line-height:1.35;`;

            if (script.modifiedDate) {
                const dateSpan = document.createElement('div');
                const dateLuaColors = getThemeColors();
                dateSpan.innerHTML = `<strong style="color:${dateLuaColors.accent};">${t('settings.installedLua.modified', 'Modified:')}</strong> ${script.modifiedDate}`;
                detailsDiv.appendChild(dateSpan);
            }

            infoDiv.appendChild(detailsDiv);
            itemEl.appendChild(infoDiv);

            const deleteBtn = document.createElement('a');
            deleteBtn.href = '#';
            deleteBtn.style.cssText = 'display:flex;align-items:center;justify-content:center;width:44px;height:44px;background:rgba(255,80,80,0.12);border:2px solid rgba(255,80,80,0.35);border-radius:12px;color:#ff5050;font-size:14px;text-decoration:none;transition:all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);cursor:pointer;flex-shrink:0;';
            deleteBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
            deleteBtn.title = t('settings.installedLua.delete', 'Remove');
            deleteBtn.onmouseover = function () {
                this.style.background = 'rgba(255,80,80,0.25)';
                this.style.borderColor = 'rgba(255,80,80,0.6)';
                this.style.color = '#ff6b6b';
                this.style.transform = 'translateY(-2px) scale(1.05)';
                this.style.boxShadow = '0 6px 20px rgba(255,80,80,0.4), 0 0 0 4px rgba(255,80,80,0.1)';
            };
            deleteBtn.onmouseout = function () {
                this.style.background = 'rgba(255,80,80,0.12)';
                this.style.borderColor = 'rgba(255,80,80,0.35)';
                this.style.color = '#ff5050';
                this.style.transform = 'translateY(0) scale(1)';
                this.style.boxShadow = 'none';
            };

            deleteBtn.addEventListener('click', function (e) {
                e.preventDefault();
                if (deleteBtn.dataset.busy === '1') return;

                showLuaToolsConfirm(
                    script.gameName || 'LuaTools',
                    t('settings.installedLua.deleteConfirm', 'Remove via LuaTools for this game?'),
                    function () {
                        // User confirmed
                        deleteBtn.dataset.busy = '1';
                        deleteBtn.style.opacity = '0.6';
                        deleteBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

                        Millennium.callServerMethod('luatools', 'DeleteLuaToolsForApp', {
                            appid: script.appid,
                            contentScriptQuery: ''
                        })
                            .then(function (res) {
                                const response = typeof res === 'string' ? JSON.parse(res) : res;
                                if (!response || !response.success) {
                                    alert(t('settings.installedLua.deleteError', 'Failed to remove Lua script.'));
                                    deleteBtn.dataset.busy = '0';
                                    deleteBtn.style.opacity = '1';
                                    deleteBtn.innerHTML = '<span><i class="fa-solid fa-trash"></i> ' + t('settings.installedLua.delete', 'Delete') + '</span>';
                                    return;
                                }

                                // Success - remove item from list with animation
                                itemEl.style.transition = 'all 0.3s ease';
                                itemEl.style.opacity = '0';
                                itemEl.style.transform = 'translateX(-20px)';
                                setTimeout(function () {
                                    itemEl.remove();
                                    // Check if list is now empty
                                    if (container.children.length === 0) {
                                        const emptyLuaColors = getThemeColors();
                                        container.innerHTML = `<div style="padding:10px;background:${emptyLuaColors.bgTertiary};border:1px solid ${emptyLuaColors.border};border-radius:4px;color:${emptyLuaColors.textSecondary};text-align:center;">${t('settings.installedLua.empty', 'No Lua scripts installed yet.')}</div>`;
                                    }
                                }, 300);
                            })
                            .catch(function (err) {
                                alert(t('settings.installedLua.deleteError', 'Failed to remove Lua script.') + ' ' + (err && err.message ? err.message : ''));
                                deleteBtn.dataset.busy = '0';
                                deleteBtn.style.opacity = '1';
                                deleteBtn.innerHTML = '<span><i class="fa-solid fa-trash"></i> ' + t('settings.installedLua.delete', 'Delete') + '</span>';
                            });
                    },
                    function () {
                        // User cancelled - do nothing
                    }
                );
            });

            itemEl.appendChild(deleteBtn);
            return itemEl;
        }

        function handleLoad(force) {
            setStatus(t('settings.loading', 'Loading settings...'), '#c7d5e0');
            saveBtn.dataset.disabled = '1';
            saveBtn.style.opacity = '0.6';
            contentWrap.innerHTML = '<div style="padding:12px;color:#c7d5e0;">' + t('common.status.loading', 'Loading...') + '</div>';

            return fetchSettingsConfig(force).then(function (config) {
                state.config = {
                    schemaVersion: config.schemaVersion,
                    schema: Array.isArray(config.schema) ? config.schema : [],
                    values: initialiseSettingsDraft(config),
                    language: config.language,
                    locales: config.locales,
                };
                state.draft = initialiseSettingsDraft(config);
                applyStaticTranslations();
                renderSettings();
                setStatus('', '#c7d5e0');
            }).catch(function (err) {
                const message = err && err.message ? err.message : t('settings.error', 'Failed to load settings.');
                contentWrap.innerHTML = '<div style="padding:12px;color:#ff5c5c;">' + message + '</div>';
                setStatus(t('common.status.error', 'Error') + ': ' + message, '#ff5c5c');
            });
        }

        backBtn.addEventListener('click', function (e) {
            e.preventDefault();
            if (typeof onBack === 'function') {
                overlay.remove();
                onBack();
            }
        });

        rightButtons.appendChild(refreshBtn);
        rightButtons.appendChild(saveBtn);
        btnRow.appendChild(backBtn);
        btnRow.appendChild(rightButtons);

        refreshBtn.addEventListener('click', function (e) {
            e.preventDefault();
            if (refreshBtn.dataset.busy === '1') return;
            refreshBtn.dataset.busy = '1';
            handleLoad(true).finally(function () {
                refreshBtn.dataset.busy = '0';
                refreshBtn.style.opacity = '1';
                applyStaticTranslations();
            });
        });

        saveBtn.addEventListener('click', function (e) {
            e.preventDefault();
            if (saveBtn.dataset.disabled === '1' || saveBtn.dataset.busy === '1') return;

            const changes = collectChanges();
            try {
                backendLog('LuaTools: collectChanges payload ' + JSON.stringify(changes));
            } catch (_) { }
            if (!changes || Object.keys(changes).length === 0) {
                setStatus(t('settings.noChanges', 'No changes to save.'), '#c7d5e0');
                updateSaveState();
                return;
            }

            saveBtn.dataset.busy = '1';
            saveBtn.style.opacity = '0.6';
            setStatus(t('settings.saving', 'Saving...'), '#c7d5e0');
            saveBtn.style.opacity = '0.6';

            const payloadToSend = JSON.parse(JSON.stringify(changes));
            try {
                backendLog('LuaTools: sending settings payload ' + JSON.stringify(payloadToSend));
            } catch (_) { }
            // Pass flattened keys so Millennium handles the RPC arguments as expected.
            Millennium.callServerMethod('luatools', 'ApplySettingsChanges', {
                contentScriptQuery: '',
                changesJson: JSON.stringify(payloadToSend)
            }).then(function (res) {
                const response = typeof res === 'string' ? JSON.parse(res) : res;
                if (!response || response.success !== true) {
                    if (response && response.errors) {
                        const errorParts = [];
                        for (const groupKey in response.errors) {
                            if (!Object.prototype.hasOwnProperty.call(response.errors, groupKey)) continue;
                            const optionErrors = response.errors[groupKey];
                            for (const optionKey in optionErrors) {
                                if (!Object.prototype.hasOwnProperty.call(optionErrors, optionKey)) continue;
                                const errorMsg = optionErrors[optionKey];
                                errorParts.push(groupKey + '.' + optionKey + ': ' + errorMsg);
                            }
                        }
                        const errText = errorParts.length ? errorParts.join('\n') : 'Validation failed.';
                        setStatus(errText, '#ff5c5c');
                    } else {
                        const message = (response && response.error) ? response.error : t('settings.saveError', 'Failed to save settings.');
                        setStatus(message, '#ff5c5c');
                    }
                    return;
                }

                const newValues = (response && response.values && typeof response.values === 'object') ? response.values : state.draft;
                state.config.values = initialiseSettingsDraft({
                    schema: state.config.schema,
                    values: newValues
                });
                state.draft = initialiseSettingsDraft({
                    schema: state.config.schema,
                    values: newValues
                });

                try {
                    if (window.__LuaToolsSettings) {
                        window.__LuaToolsSettings.values = JSON.parse(JSON.stringify(state.config.values));
                        window.__LuaToolsSettings.schemaVersion = state.config.schemaVersion;
                        window.__LuaToolsSettings.lastFetched = Date.now();
                        if (response && response.translations && typeof response.translations === 'object') {
                            window.__LuaToolsSettings.translations = response.translations;
                        }
                        if (response && response.language) {
                            window.__LuaToolsSettings.language = response.language;
                        }
                    }
                } catch (_) { }

                // Invalidate the settings cache to force a fresh fetch on next settings load
                // This ensures any changes persist across page navigations
                try {
                    if (window.__LuaToolsSettings) {
                        window.__LuaToolsSettings.schema = null;
                    }
                } catch (_) { }

                if (response && response.translations && typeof response.translations === 'object') {
                    applyTranslationBundle({
                        language: response.language || (window.__LuaToolsI18n && window.__LuaToolsI18n.language) || 'en',
                        locales: (window.__LuaToolsI18n && window.__LuaToolsI18n.locales) || (state.config && state.config.locales) || [],
                        strings: response.translations
                    });
                    applyStaticTranslations();
                    updateButtonTranslations();
                }

                renderSettings();
                setStatus(t('settings.saveSuccess', 'Settings saved successfully.'), '#8bc34a');

                // Reload theme if it changed
                const oldTheme = state.config.values?.general?.theme;
                const newTheme = state.draft?.general?.theme;
                if (oldTheme !== newTheme) {
                    ensureLuaToolsStyles();
                }
            }).catch(function (err) {
                const message = err && err.message ? err.message : t('settings.saveError', 'Failed to save settings.');
                setStatus(message, '#ff5c5c');
            }).finally(function () {
                saveBtn.dataset.busy = '0';
                applyStaticTranslations();
                updateSaveState();
            });
        });

        closeIconBtn.addEventListener('click', function (e) {
            e.preventDefault();
            overlay.remove();
        });

        discordIconBtn.addEventListener('click', function (e) {
            e.preventDefault();
            const url = 'https://discord.gg/luatools';
            try {
                Millennium.callServerMethod('luatools', 'OpenExternalUrl', {
                    url,
                    contentScriptQuery: ''
                });
            } catch (_) { }
        });

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) {
                overlay.remove();
            }
        });

        handleLoad(!!forceRefresh);
    }

    // Force-close any open settings overlays to avoid stacking
    function closeSettingsOverlay() {
        try {
            // Remove all settings overlays (robust against older NodeList forEach support)
            var list = document.getElementsByClassName('luatools-settings-overlay');
            while (list && list.length > 0) {
                try {
                    list[0].remove();
                } catch (_) {
                    break;
                }
            }
            // Also remove any download/progress overlays if present
            var list2 = document.getElementsByClassName('luatools-overlay');
            while (list2 && list2.length > 0) {
                try {
                    list2[0].remove();
                } catch (_) {
                    break;
                }
            }
        } catch (_) { }
    }

    // Custom modern alert dialog
    function showLuaToolsAlert(title, message, onClose) {
        if (document.querySelector('.luatools-alert-overlay')) return;

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-alert-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);backdrop-filter:blur(10px);z-index:100001;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const alertModalColors = getThemeColors();
        modal.style.cssText = `background:${alertModalColors.modalBg};color:${alertModalColors.text};border:2px solid ${alertModalColors.border};border-radius:8px;width:380px;max-width:95vw;padding:12px 16px;box-shadow:0 20px 60px rgba(0,0,0,.9), 0 0 0 1px ${alertModalColors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const titleEl = document.createElement('div');
        const alertTitleColors = getThemeColors();
        titleEl.style.cssText = `font-size:13px;color:${alertTitleColors.text};margin-bottom:12px;font-weight:700;text-align:left;text-shadow:0 2px 8px ${alertTitleColors.shadow};background:${alertTitleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        titleEl.textContent = String(title || 'LuaTools');

        const messageEl = document.createElement('div');
        const alertMsgColors = getThemeColors();
        messageEl.style.cssText = `font-size:15px;line-height:1.35;margin-bottom:14px;color:${alertMsgColors.textSecondary};text-align:left;padding:0 8px;`;
        messageEl.textContent = String(message || '');

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;justify-content:flex-end;';

        const okBtn = document.createElement('a');
        okBtn.href = '#';
        okBtn.className = 'luatools-btn primary';
        okBtn.style.minWidth = '140px';
        okBtn.innerHTML = `<span>${lt('Close')}</span>`;
        okBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
            try {
                onClose && onClose();
            } catch (_) { }
        };

        btnRow.appendChild(okBtn);

        modal.appendChild(titleEl);
        modal.appendChild(messageEl);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) {
                overlay.remove();
                try {
                    onClose && onClose();
                } catch (_) { }
            }
        });

        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);
    }

    // Helper to show alert with fallback
    function ShowLuaToolsAlert(title, message) {
        try {
            showLuaToolsAlert(title, message);
        } catch (err) {
            backendLog('LuaTools: Alert error, falling back: ' + err);
            try {
                alert(String(title) + '\n\n' + String(message));
            } catch (_) { }
        }
    }

    // Steam-style confirm helper (ShowConfirmDialog only)
    function showLuaToolsConfirm(title, message, onConfirm, onCancel) {
        // Always close settings popup first so the confirm is visible on top
        closeSettingsOverlay();

        // Create custom modern confirmation dialog
        if (document.querySelector('.luatools-confirm-overlay')) return;

        ensureLuaToolsStyles();
        ensureFontAwesome();
        const overlay = document.createElement('div');
        overlay.className = 'luatools-confirm-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);backdrop-filter:blur(10px);z-index:100001;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const confirmColors = getThemeColors();
        modal.style.cssText = `background:${confirmColors.modalBg};color:${confirmColors.text};border:2px solid ${confirmColors.border};border-radius:8px;width:400px;max-width:95vw;padding:12px 16px;box-shadow:0 20px 60px rgba(0,0,0,.9), 0 0 0 1px ${confirmColors.shadowRgba};animation:slideUp 0.1s ease-out;`;

        const titleEl = document.createElement('div');
        const titleConfirmColors = getThemeColors();
        titleEl.style.cssText = `font-size:13px;color:${titleConfirmColors.text};margin-bottom:12px;font-weight:700;text-align:center;text-shadow:0 2px 8px ${titleConfirmColors.shadow};background:${titleConfirmColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        titleEl.textContent = String(title || 'LuaTools');

        const messageEl = document.createElement('div');
        const msgColors = getThemeColors();
        messageEl.style.cssText = `font-size:15px;line-height:1.35;margin-bottom:14px;color:${msgColors.textSecondary};text-align:center;`;
        messageEl.textContent = String(message || lt('Are you sure?'));

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:6px;justify-content:center;';

        const cancelBtn = document.createElement('a');
        cancelBtn.href = '#';
        cancelBtn.className = 'luatools-btn';
        cancelBtn.style.flex = '1';
        cancelBtn.innerHTML = `<span>${lt('Cancel')}</span>`;
        cancelBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
            try {
                onCancel && onCancel();
            } catch (_) { }
        };
        const confirmBtn = document.createElement('a');
        confirmBtn.href = '#';
        confirmBtn.className = 'luatools-btn primary';
        confirmBtn.style.flex = '1';
        confirmBtn.innerHTML = `<span>${lt('Confirm')}</span>`;
        confirmBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
            try {
                onConfirm && onConfirm();
            } catch (_) { }
        };

        btnRow.appendChild(cancelBtn);
        btnRow.appendChild(confirmBtn);

        modal.appendChild(titleEl);
        modal.appendChild(messageEl);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) {
                overlay.remove();
                try {
                    onCancel && onCancel();
                } catch (_) { }
            }
        });

        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);
    }

    // DLC warning modal
    function showDlcWarning(appid, fullgameAppid, fullgameName) {
        // Close settings so modal is visible
        closeSettingsOverlay();
        if (document.querySelector('.luatools-dlc-warning-overlay')) return;

        ensureLuaToolsStyles();
        ensureFontAwesome();

        const overlay = document.createElement('div');
        overlay.className = 'luatools-dlc-warning-overlay luatools-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);backdrop-filter:blur(10px);z-index:100001;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        const colors = getThemeColors();
        modal.style.cssText = `background:${colors.modalBg};color:${colors.text};border:2px solid ${colors.border};border-radius:12px;width:420px;max-width:95vw;padding:14px 18px;box-shadow:0 25px 70px rgba(0,0,0,.9);animation:slideUp 0.15s ease-out;`;

        const header = document.createElement('div');
        header.style.cssText = 'text-align:center;margin-bottom:12px;';
        const icon = document.createElement('i');
        icon.className = 'fa-solid fa-circle-info';
        icon.style.cssText = `color:${colors.accent};font-size:32px;filter:drop-shadow(0 0 10px ${colors.shadow});`;
        header.appendChild(icon);

        const titleEl = document.createElement('div');
        titleEl.style.cssText = `font-size:14px;font-weight:800;text-align:center;margin-bottom:10px;background:${colors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;`;
        titleEl.textContent = lt('DLC Detected');

        const messageEl = document.createElement('div');
        messageEl.style.cssText = `font-size:13px;line-height:1.35;margin-bottom:14px;color:${colors.textSecondary};text-align:center;`;
        var safeName = (fullgameName || lt('Base Game')).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        messageEl.innerHTML = lt('DLCs are added together with the base game. To add fixes for this DLC, please go to the base game page: <br><br><b>{gameName}</b>').replace('{gameName}', safeName);

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:10px;justify-content:center;';

        const cancelBtn = document.createElement('a');
        cancelBtn.href = '#';
        cancelBtn.className = 'luatools-btn';
        cancelBtn.style.flex = '1';
        cancelBtn.innerHTML = `<span>${lt('Cancel')}</span>`;
        cancelBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
        };

        const goBtn = document.createElement('a');
        goBtn.href = 'https://store.steampowered.com/app/' + fullgameAppid;
        goBtn.className = 'luatools-btn primary';
        goBtn.style.flex = '1.5';
        goBtn.innerHTML = `<span>${lt('Go to Base Game')}</span>`;
        goBtn.onclick = function (e) {
            // Let the default link behavior happen (navigation)
            // But we can also remove the overlay
            setTimeout(() => overlay.remove(), 100);
        };

        btnRow.appendChild(cancelBtn);
        btnRow.appendChild(goBtn);

        modal.appendChild(header);
        modal.appendChild(titleEl);
        modal.appendChild(messageEl);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.remove();
        });

        document.body.appendChild(overlay);

        setTimeout(function () {
            if (window.GamepadNav) window.GamepadNav.scanElements();
        }, 150);
    }

    function showLuaToolsPlayableWarning(message, onProceed, onCancel) {
        // Close settings so modal is visible
        closeSettingsOverlay();
        if (document.querySelector('.luatools-playable-warning-overlay')) return;

        ensureLuaToolsStyles();
        ensureFontAwesome();

        const overlay = document.createElement('div');
        overlay.className = 'luatools-playable-warning-overlay luatools-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);backdrop-filter:blur(6px);z-index:100001;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        modal.style.cssText = 'background:linear-gradient(180deg,#3a0f0f,#2a0b0b);color:#fff;border:2px solid rgba(255,80,80,0.9);border-radius:8px;width:440px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.9);';

        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:14px;justify-content:center;';
        const icon = document.createElement('i');
        icon.className = 'fa-solid fa-triangle-exclamation';
        icon.style.cssText = 'color:#ffddda;font-size:15px;';
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-size:14px;font-weight:700;text-align:center;';
        titleEl.textContent = t('common.warning', 'Warning');
        header.appendChild(icon);
        header.appendChild(titleEl);

        const messageEl = document.createElement('div');
        messageEl.style.cssText = 'font-size:14px;line-height:1.5;margin-bottom:10px;color:#ffecec;text-align:center;padding:0 6px;';
        messageEl.textContent = String(message || 'This game may not work, support for it wont be given in our discord');

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:6px;justify-content:center;';

        const cancelBtn = document.createElement('a');
        cancelBtn.href = '#';
        cancelBtn.className = 'luatools-btn';
        cancelBtn.style.flex = '1';
        cancelBtn.innerHTML = `<span>${lt('Cancel')}</span>`;
        cancelBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
            try {
                onCancel && onCancel();
            } catch (_) { }
        };

        const proceedBtn = document.createElement('a');
        proceedBtn.href = '#';
        proceedBtn.className = 'luatools-btn primary';
        proceedBtn.style.flex = '1';
        proceedBtn.innerHTML = `<span>${lt('Proceed')}</span>`;
        proceedBtn.onclick = function (e) {
            e.preventDefault();
            overlay.remove();
            try {
                onProceed && onProceed();
            } catch (_) { }
        };

        btnRow.appendChild(cancelBtn);
        btnRow.appendChild(proceedBtn);

        modal.appendChild(header);
        modal.appendChild(messageEl);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) {
                overlay.remove();
                try {
                    onCancel && onCancel();
                } catch (_) { }
            }
        });

        document.body.appendChild(overlay);

        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);
    }

    // Millennium disclaimer modal
    function showMillenniumDisclaimerModal() {
        if (document.querySelector('.luatools-disclaimer-overlay')) return;

        ensureLuaToolsStyles();
        ensureFontAwesome();

        const overlay = document.createElement('div');
        overlay.className = 'luatools-disclaimer-overlay luatools-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);backdrop-filter:blur(10px);z-index:100005;display:flex;align-items:center;justify-content:center;';

        const modal = document.createElement('div');
        modal.style.cssText = 'background:linear-gradient(180deg,#5a4100,#362600);color:#fff;border:2px solid rgba(255,180,60,0.9);border-radius:12px;width:440px;max-width:95vw;padding:14px 18px;box-shadow:0 25px 70px rgba(0,0,0,.9);animation:slideUp 0.2s ease-out;';

        const iconContainer = document.createElement('div');
        iconContainer.style.cssText = 'text-align:center;margin-bottom:10px;';
        const icon = document.createElement('i');
        icon.className = 'fa-solid fa-triangle-exclamation';
        icon.style.cssText = 'color:#FFE1A8;font-size:32px;filter:drop-shadow(0 0 10px rgba(255,225,168,0.5));';
        iconContainer.appendChild(icon);

        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-size:14px;font-weight:800;text-align:center;margin-bottom:14px;color:#FFE1A8;letter-spacing:0.5px;';
        titleEl.textContent = t('disclaimer.title', 'Security & Support Notice');

        const messageEl = document.createElement('div');
        messageEl.style.cssText = 'font-size:15px;line-height:1.35;margin-bottom:14px;color:#ffecec;text-align:center;';

        const line1 = document.createElement('div');
        line1.style.cssText = 'margin-bottom:12px;font-weight:600;';
        line1.textContent = t('disclaimer.line1', 'LuaTools is not affiliated in any way with Millennium');

        const line2 = document.createElement('div');
        line2.style.cssText = 'margin-bottom:12px;';
        line2.textContent = t('disclaimer.line2', 'Millennium will NOT offer you support for this plugin on their discord server');

        const line3 = document.createElement('div');
        line3.style.cssText = 'font-weight:700;color:#ff8e8e;';
        line3.textContent = t('disclaimer.line3', 'You will be BANNED from both LuaTools and Millennium servers if you go to their discord asking for help');

        messageEl.appendChild(line1);
        messageEl.appendChild(line2);
        messageEl.appendChild(line3);

        const inputGroup = document.createElement('div');
        inputGroup.style.cssText = 'margin-bottom:12px;';

        const inputLabel = document.createElement('div');
        inputLabel.style.cssText = 'font-size:12px;color:#8f98a0;margin-bottom:10px;text-align:center;text-transform:uppercase;letter-spacing:1px;';
        inputLabel.textContent = t('disclaimer.inputLabel', 'type "I Understand" in the box bellow to continue');

        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = t('disclaimer.inputPlaceholder', 'I Understand');
        input.style.cssText = 'width:100%;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:12px;color:#fff;font-size:14px;outline:none;text-align:center;transition:all 0.3s ease;';
        input.onfocus = function () {
            this.style.borderColor = 'rgba(255,255,255,0.3)';
            this.style.background = 'rgba(0,0,0,0.4)';
        };
        input.onblur = function () {
            this.style.borderColor = 'rgba(255,255,255,0.1)';
            this.style.background = 'rgba(0,0,0,0.3)';
        };

        inputGroup.appendChild(inputLabel);
        inputGroup.appendChild(input);

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;justify-content:center;';

        const confirmBtn = document.createElement('a');
        confirmBtn.href = '#';
        confirmBtn.className = 'luatools-btn primary';
        confirmBtn.style.minWidth = 'auto';
        confirmBtn.style.background = '#FFEA00';
        confirmBtn.style.color = '#000';
        confirmBtn.style.justifyContent = 'center';
        confirmBtn.innerHTML = `<span>${lt('Confirm')}</span>`;
        confirmBtn.style.opacity = '0.5';
        confirmBtn.style.pointerEvents = 'none';

        var expectedPhrase = t('disclaimer.inputPlaceholder', 'I Understand').trim().toLowerCase();
        input.oninput = function () {
            if (this.value.trim().toLowerCase() === expectedPhrase) {
                confirmBtn.style.opacity = '1';
                confirmBtn.style.pointerEvents = 'auto';
                confirmBtn.style.boxShadow = '0 0 15px rgba(255,234,0,0.6)';
            } else {
                confirmBtn.style.opacity = '0.5';
                confirmBtn.style.pointerEvents = 'none';
                confirmBtn.style.boxShadow = 'none';
            }
        };

        confirmBtn.onclick = function (e) {
            e.preventDefault();
            if (input.value.trim().toLowerCase() === expectedPhrase) {
                localStorage.setItem('luatools millennium disclaimer accepted', '1');
                overlay.remove();
            }
        };

        btnRow.appendChild(confirmBtn);

        modal.appendChild(iconContainer);
        modal.appendChild(titleEl);
        modal.appendChild(messageEl);
        modal.appendChild(inputGroup);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);

        document.body.appendChild(overlay);

        // Focus input after a short delay
        setTimeout(() => input.focus(), 300);

        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);
    }

    // Ensure consistent spacing for our buttons
    function ensureStyles() {
        if (!document.getElementById('luatools-spacing-styles')) {
            const style = document.createElement('style');
            style.id = 'luatools-spacing-styles';
            style.textContent = `
                .luatools-restart-button, .luatools-icon-button { margin-left: 6px !important; margin-right: 0 !important; }
                .luatools-button { margin-right: 0 !important; position: relative !important; }
                .luatools-pills-container {
                    position: absolute !important;
                    top: -25px !important;
                    left: 50% !important;
                    transform: translateX(-50%) !important;
                    display: inline-flex;
                    gap: 4px;
                    align-items: center;
                    pointer-events: none;
                    z-index: 10;
                    white-space: nowrap;
                }
                .luatools-pill {
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 9px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    display: inline-flex;
                    align-items: center;
                    height: 16px;
                    line-height: 1;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                    cursor: default;
                }
                .luatools-pill.red { background: rgba(255, 80, 80, 0.15); color: #ff5050; border: 1px solid rgba(255, 80, 80, 0.3); }
                .luatools-pill.green { background: rgba(92, 184, 92, 0.15); color: #5cb85c; border: 1px solid rgba(92, 184, 92, 0.3); }
                .luatools-pill.yellow { background: rgba(255, 193, 7, 0.15); color: #ffc107; border: 1px solid rgba(255, 193, 7, 0.3); }
                .luatools-pill.orange { background: rgba(255, 136, 0, 0.15); color: #ff8800; border: 1px solid rgba(255, 136, 0, 0.3); }
                .luatools-pill.gray { background: rgba(150, 150, 150, 0.15); color: #a0a0a0; border: 1px solid rgba(150, 150, 150, 0.3); }
            `;
            document.head.appendChild(style); // This is now separate from the main style block
        }
    }

    // Function to update button text with current translations
    function updateButtonTranslations() {
        try {
            // Update Restart Steam button
            const restartBtn = document.querySelector('.luatools-restart-button');
            if (restartBtn) {
                const restartText = lt('Restart Steam');
                restartBtn.title = restartText;
                restartBtn.setAttribute('data-tooltip-text', restartText);
                const rspan = restartBtn.querySelector('span');
                if (rspan) {
                    rspan.textContent = restartText;
                }
            }

            // Update Add via LuaTools button
            const luatoolsBtn = document.querySelector('.luatools-button');
            if (luatoolsBtn) {
                const addViaText = lt('Add via LuaTools');
                luatoolsBtn.title = addViaText;
                luatoolsBtn.setAttribute('data-tooltip-text', addViaText);
                const span = luatoolsBtn.querySelector('span');
                if (span) {
                    span.textContent = addViaText;
                }
            }
        } catch (err) {
            backendLog('LuaTools: updateButtonTranslations error: ' + err);
        }
    }

    // Function to add the LuaTools button
    // Add throttle to prevent excessive executions
    let lastButtonCheckTime = 0;
    const BUTTON_CHECK_THROTTLE = 500; // Only run once every 500ms

    function addLuaToolsButton() {
        // Throttle to prevent blocking gamepad input
        const now = Date.now();
        if (now - lastButtonCheckTime < BUTTON_CHECK_THROTTLE) {
            return; // Skip this execution, too soon
        }
        lastButtonCheckTime = now;

        // Track current URL to detect page changes
        const currentUrl = window.location.href;
        if (window.__LuaToolsLastUrl !== currentUrl) {
            // Page changed - reset button insertion flag and update translations
            window.__LuaToolsLastUrl = currentUrl;
            window.__LuaToolsButtonInserted = false;
            window.__LuaToolsRestartInserted = false;
            window.__LuaToolsIconInserted = false;
            window.__LuaToolsHeaderInserted = false;
            window.__LuaToolsPresenceCheckInFlight = false;
            window.__LuaToolsPresenceCheckAppId = undefined;
            // Ensure translations are loaded and update existing buttons
            ensureTranslationsLoaded(false).then(function () {
                updateButtonTranslations();
            });
        }

        // Store Header Button Logic (when not on app page)
        const isAppPath = window.location.pathname.includes('/app/');
        if (!isAppPath) {
            const headerContainer = document.querySelector('._1wn1lBlAzl3HMRqS1llwie');
            if (headerContainer && !document.querySelector('.luatools-header-button') && !window.__LuaToolsHeaderInserted) {
                ensureLuaToolsStyles();
                const headerBtn = document.createElement('a');
                headerBtn.href = '#';
                // Use luatools-btn primary class for that premium modal look
                headerBtn.className = 'luatools-btn primary luatools-header-button Focusable';
                headerBtn.style.cssText = 'margin-left:12px; display:inline-flex; align-items:center; justify-content:center; align-self:center; cursor:pointer; flex-shrink:0; width:36px; height:36px; padding:0; border-radius:8px; border-width:1px; box-shadow: 0 4px 12px rgba(0,0,0,0.4);';
                headerBtn.title = 'LuaTools Settings';

                headerBtn.setAttribute('data-tooltip-text', 'LuaTools Settings');

                const img = document.createElement('img');
                img.style.height = '18px';
                img.style.width = '18px';
                img.style.verticalAlign = 'middle';

                try {
                    Millennium.callServerMethod('luatools', 'GetIconDataUrl', {
                        contentScriptQuery: ''
                    }).then(function (res) {
                        try {
                            const payload = typeof res === 'string' ? JSON.parse(res) : res;
                            if (payload && payload.success && payload.dataUrl) {
                                img.src = payload.dataUrl;
                            } else {
                                img.src = 'LuaTools/luatools-icon.png';
                            }
                        } catch (_) {
                            img.src = 'LuaTools/luatools-icon.png';
                        }
                    });
                } catch (_) {
                    img.src = 'LuaTools/luatools-icon.png';
                }

                img.onerror = function () {
                    // cogwhell fallback
                    headerBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="LuaTools"><path fill="currentColor" d="M12 8a4 4 0 100 8 4 4 0 000-8zm9.94 3.06l-2.12-.35a7.962 7.962 0 00-1.02-2.46l1.29-1.72a.75.75 0 00-.09-.97l-1.41-1.41a.75.75 0 00-.97-.09l-1.72 1.29c-.77-.44-1.6-.78-2.46-1.02L13.06 2.06A.75.75 0 0012.31 2h-1.62a.75.75 0 00-.75.65l-.35 2.12a7.962 7.962 0 00-2.46 1.02L5 4.6a.75.75 0 00-.97.09L2.62 6.1a.75.75 0 00-.09.97l1.29 1.72c-.44.77-.78 1.6-1.02 2.46l-2.12.35a.75.75 0 00-.65.75v1.62c0 .37.27.69.63.75l2.14.36c.24.86.58 1.69 1.02 2.46L2.53 18a.75.75 0 00.09.97l1.41 1.41c.26.26.67.29.97.09l1.72-1.29c.77.44 1.6.78 2.46 1.02l.35 2.12c.06.36.38.63.75.63h1.62c.37 0 .69-.27.75-.63l.36-2.14c.86-.24 1.69-.58 2.46-1.02l1.72 1.29c.3.2.71.17.97-.09l1.41-1.41c.26-.26.29-.67.09-.97l-1.29-1.72c.44-.77.78-1.6 1.02-2.46l2.12-.35c.36-.06.63-.38.63-.75v-1.62a.75.75 0 00-.65-.75z"/></svg>';
                };

                headerBtn.appendChild(img);

                headerBtn.onclick = function (e) {
                    e.preventDefault();
                    showSettingsPopup();
                };

                headerContainer.appendChild(headerBtn);
                window.__LuaToolsHeaderInserted = true;
                backendLog('Inserted store header button (non-app page)');
            }
        }

        // Check if we're in Big Picture mode
        const isBigPicture = window.__LUATOOLS_IS_BIG_PICTURE__;

        // Look for the appropriate container based on mode
        let targetContainer;
        if (isBigPicture) {
            // In Big Picture mode, use the queue button's parent as reference
            const queueBtn = document.querySelector('#queueBtnFollow');
            targetContainer = queueBtn ? queueBtn.parentElement : null;
        } else {
            // In normal mode, use the SteamDB buttons container
            targetContainer = document.querySelector('.steamdb-buttons') ||
                document.querySelector('[data-steamdb-buttons]') ||
                document.querySelector('.apphub_OtherSiteInfo');
        }

        if (targetContainer) {
            const steamdbContainer = targetContainer;

            // Insert a Restart Steam button between Community Hub and our LuaTools button
            try {
                if (!document.querySelector('.luatools-restart-button') && !window.__LuaToolsRestartInserted) {
                    ensureStyles();
                    // In Big Picture mode, use queue button as reference; otherwise use first link in container
                    const referenceBtn = isBigPicture ?
                        document.querySelector('#queueBtnFollow') :
                        steamdbContainer.querySelector('a');

                    // Use same custom button for both modes
                    const restartBtn = document.createElement('a');
                    if (referenceBtn && referenceBtn.className) {
                        restartBtn.className = referenceBtn.className + ' luatools-restart-button';
                    } else {
                        restartBtn.className = 'btnv6_blue_hoverfade btn_medium luatools-restart-button';
                    }
                    restartBtn.href = '#';
                    const restartText = lt('Restart Steam');
                    restartBtn.title = restartText;
                    restartBtn.setAttribute('data-tooltip-text', restartText);
                    const rspan = document.createElement('span');
                    rspan.textContent = restartText;
                    restartBtn.appendChild(rspan);

                    // Normalize margins to match native buttons
                    try {
                        if (referenceBtn) {
                            const cs = window.getComputedStyle(referenceBtn);
                            restartBtn.style.marginLeft = cs.marginLeft;
                            restartBtn.style.marginRight = cs.marginRight;
                        }
                    } catch (_) { }

                    restartBtn.addEventListener('click', function (e) {
                        e.preventDefault();
                        try {
                            // Ensure any settings overlays are closed before confirm
                            closeSettingsOverlay();
                            showLuaToolsConfirm('LuaTools', lt('Restart Steam now?'),
                                function () {
                                    try {
                                        Millennium.callServerMethod('luatools', 'RestartSteam', {
                                            contentScriptQuery: ''
                                        });
                                    } catch (_) { }
                                },
                                function () {
                                    /* Cancel - do nothing */
                                }
                            );
                        } catch (_) {
                            showLuaToolsConfirm('LuaTools', lt('Restart Steam now?'),
                                function () {
                                    try {
                                        Millennium.callServerMethod('luatools', 'RestartSteam', {
                                            contentScriptQuery: ''
                                        });
                                    } catch (_) { }
                                },
                                function () {
                                    /* Cancel - do nothing */
                                }
                            );
                        }
                    });

                    if (referenceBtn && referenceBtn.parentElement) {
                        referenceBtn.after(restartBtn);
                    } else {
                        steamdbContainer.appendChild(restartBtn);
                    }
                    // Insert icon button right after Restart (only once)
                    try {
                        if (!document.querySelector('.luatools-icon-button') && !window.__LuaToolsIconInserted) {
                            // Use same custom button for both modes
                            const iconBtn = document.createElement('a');
                            if (referenceBtn && referenceBtn.className) {
                                iconBtn.className = referenceBtn.className + ' luatools-icon-button';
                            } else {
                                iconBtn.className = 'btnv6_blue_hoverfade btn_medium luatools-icon-button';
                            }
                            iconBtn.href = '#';
                            iconBtn.title = 'LuaTools Helper';
                            iconBtn.setAttribute('data-tooltip-text', 'LuaTools Helper');

                            // Normalize margins to match native buttons
                            try {
                                if (referenceBtn) {
                                    const cs = window.getComputedStyle(referenceBtn);
                                    iconBtn.style.marginLeft = cs.marginLeft;
                                    iconBtn.style.marginRight = cs.marginRight;
                                }
                            } catch (_) { }

                            const ispan = document.createElement('span');
                            const img = document.createElement('img');
                            img.alt = '';
                            img.style.height = '16px';
                            img.style.width = '16px';
                            img.style.verticalAlign = 'middle';
                            // Try to fetch data URL for the icon from backend to avoid path issues
                            try {
                                Millennium.callServerMethod('luatools', 'GetIconDataUrl', {
                                    contentScriptQuery: ''
                                }).then(function (res) {
                                    try {
                                        const payload = typeof res === 'string' ? JSON.parse(res) : res;
                                        if (payload && payload.success && payload.dataUrl) {
                                            img.src = payload.dataUrl;
                                        } else {
                                            img.src = 'LuaTools/luatools-icon.png';
                                        }
                                    } catch (_) {
                                        img.src = 'LuaTools/luatools-icon.png';
                                    }
                                });
                            } catch (_) {
                                img.src = 'LuaTools/luatools-icon.png';
                            }
                            // If image fails, fallback to inline SVG gear
                            img.onerror = function () {
                                ispan.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M12 8a4 4 0 100 8 4 4 0 000-8zm9.94 3.06l-2.12-.35a7.962 7.962 0 00-1.02-2.46l1.29-1.72a.75.75 0 00-.09-.97l-1.41-1.41a.75.75 0 00-.97-.09l-1.72 1.29c-.77-.44-1.6-.78-2.46-1.02L13.06 2.06A.75.75 0 0012.31 2h-1.62a.75.75 0 00-.75.65l-.35 2.12a7.962 7.962 0 00-2.46 1.02L5 4.6a.75.75 0 00-.97.09L2.62 6.1a.75.75 0 00-.09.97l1.29 1.72c-.44.77-.78 1.6-1.02 2.46l-2.12.35a.75.75 0 00-.65.75v1.62c0 .37.27.69.63.75l2.14.36c.24.86.58 1.69 1.02 2.46L2.53 18a.75.75 0 00.09.97l1.41 1.41c.26.26.67.29.97.09l1.72-1.29c.77.44 1.6.78 2.46 1.02l.35 2.12c.06.36.38.63.75.63h1.62c.37 0 .69-.27.75-.63l.36-2.14c.86-.24 1.69-.58 2.46-1.02l1.72 1.29c.3.2.71.17.97-.09l1.41-1.41c.26-.26.29-.67.09-.97l-1.29-1.72c.44-.77.78-1.6 1.02-2.46l2.12-.35c.36-.06.63-.38.63-.75v-1.62a.75.75 0 00-.65-.75z"/></svg>';
                            };
                            ispan.appendChild(img);
                            iconBtn.appendChild(ispan);
                            iconBtn.addEventListener('click', function (e) {
                                e.preventDefault();
                                showSettingsPopup();
                            });

                            steamdbContainer.appendChild(iconBtn);

                            window.__LuaToolsIconInserted = true;
                            backendLog('Inserted Icon button');
                        }
                    } catch (_) { }
                    window.__LuaToolsRestartInserted = true;
                    backendLog('Inserted Restart Steam button');
                }
            } catch (_) { }

            // Status Pills Logic
            // Always update translations for existing buttons (even if not a page change)
            const existingBtn = document.querySelector('.luatools-button');
            if (existingBtn) {
                ensureTranslationsLoaded(false).then(function () {
                    updateButtonTranslations();
                });
            }

            // Check if button already exists to avoid duplicates
            if (!existingBtn && !window.__LuaToolsButtonInserted) {

                // Create the LuaTools button modeled after existing SteamDB/PCGW buttons
                // In Big Picture mode, use queue button as reference; otherwise use first link in container
                let referenceBtn = isBigPicture ?
                    document.querySelector('#queueBtnFollow') :
                    steamdbContainer.querySelector('a');

                // Use same custom button for both modes
                const luatoolsButton = document.createElement('a');
                luatoolsButton.href = '#';
                // Copy classes from an existing button to match look-and-feel, but set our own label
                if (referenceBtn && referenceBtn.className) {
                    luatoolsButton.className = referenceBtn.className + ' luatools-button';
                } else {
                    luatoolsButton.className = 'btnv6_blue_hoverfade btn_medium luatools-button';
                }
                const span = document.createElement('span');
                const addViaText = lt('Add via LuaTools');
                span.textContent = addViaText;
                luatoolsButton.appendChild(span);
                // Tooltip/title
                luatoolsButton.title = addViaText;
                luatoolsButton.setAttribute('data-tooltip-text', addViaText);

                // Normalize margins to match native buttons
                try {
                    if (referenceBtn) {
                        const cs = window.getComputedStyle(referenceBtn);
                        luatoolsButton.style.marginLeft = cs.marginLeft;
                        luatoolsButton.style.marginRight = cs.marginRight;
                    }
                } catch (_) { }

                // Local click handler suppressed; delegated handler manages actions
                luatoolsButton.addEventListener('click', function (e) {
                    e.preventDefault();
                    backendLog('LuaTools button clicked (delegated handler will process)');
                });

                // Before inserting, ask backend if LuaTools already exists for this appid
                try {
                    const match = window.location.href.match(/https:\/\/store\.steampowered\.com\/app\/(\d+)/) || window.location.href.match(/https:\/\/steamcommunity\.com\/app\/(\d+)/);
                    const appid = match ? parseInt(match[1], 10) : NaN;
                    if (!isNaN(appid) && typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
                        // prevent multiple concurrent checks
                        if (window.__LuaToolsPresenceCheckInFlight && window.__LuaToolsPresenceCheckAppId === appid) {
                            return;
                        }
                        window.__LuaToolsPresenceCheckInFlight = true;
                        window.__LuaToolsPresenceCheckAppId = appid;
                        window.__LuaToolsCurrentAppId = appid;
                        Millennium.callServerMethod('luatools', 'HasLuaToolsForApp', {
                            appid,
                            contentScriptQuery: ''
                        }).then(function (res) {
                            try {
                                const payload = typeof res === 'string' ? JSON.parse(res) : res;
                                if (payload && payload.success && payload.exists === true) {
                                    backendLog('LuaTools already present for this app; not inserting button');
                                    window.__LuaToolsPresenceCheckInFlight = false;
                                    return; // do not insert
                                }
                                // Re-check in case another caller inserted during async
                                if (!document.querySelector('.luatools-button') && !window.__LuaToolsButtonInserted) {
                                    // Insert after icon button (order: Restart → Icon → Add)
                                    const iconExisting = steamdbContainer.querySelector('.luatools-icon-button');
                                    const restartExisting = steamdbContainer.querySelector('.luatools-restart-button');
                                    if (iconExisting && iconExisting.before) {
                                        iconExisting.before(luatoolsButton);
                                    } else if (restartExisting && restartExisting.after) {
                                        restartExisting.after(luatoolsButton);
                                    } else if (referenceBtn && referenceBtn.after) {
                                        referenceBtn.after(luatoolsButton);
                                    } else {
                                        steamdbContainer.appendChild(luatoolsButton);
                                    }
                                    window.__LuaToolsButtonInserted = true;
                                    backendLog('LuaTools button inserted');
                                }
                                window.__LuaToolsPresenceCheckInFlight = false;
                            } catch (_) {
                                if (!document.querySelector('.luatools-button') && !window.__LuaToolsButtonInserted) {
                                    steamdbContainer.appendChild(luatoolsButton);
                                    window.__LuaToolsButtonInserted = true;
                                    backendLog('LuaTools button inserted');
                                }
                                window.__LuaToolsPresenceCheckInFlight = false;
                            }
                        });
                    } else {
                        if (!document.querySelector('.luatools-button') && !window.__LuaToolsButtonInserted) {
                            // Insert after icon button (order: Restart → Icon → Add)
                            const iconExisting = steamdbContainer.querySelector('.luatools-icon-button');
                            const restartExisting = steamdbContainer.querySelector('.luatools-restart-button');
                            if (iconExisting && iconExisting.before) {
                                iconExisting.before(luatoolsButton);
                            } else if (restartExisting && restartExisting.after) {
                                restartExisting.after(luatoolsButton);
                            } else if (referenceBtn && referenceBtn.after) {
                                referenceBtn.after(luatoolsButton);
                            } else {
                                steamdbContainer.appendChild(luatoolsButton);
                            }
                            window.__LuaToolsButtonInserted = true;
                            backendLog('LuaTools button inserted');
                        }
                    }
                } catch (_) {
                    if (!document.querySelector('.luatools-button') && !window.__LuaToolsButtonInserted) {
                        const restartExisting = steamdbContainer.querySelector('.luatools-restart-button');
                        if (restartExisting && restartExisting.after) {
                            restartExisting.after(luatoolsButton);
                        } else if (referenceBtn && referenceBtn.after) {
                            referenceBtn.after(luatoolsButton);
                        } else {
                            steamdbContainer.appendChild(luatoolsButton);
                        }
                        window.__LuaToolsButtonInserted = true;
                        backendLog('LuaTools button inserted');
                    }
                }
            }

            // status pills — only run once per appid
            try {
                const match = window.location.href.match(/https:\/\/store\.steampowered\.com\/app\/(\d+)/) || window.location.href.match(/https:\/\/steamcommunity\.com\/app\/(\d+)/);
                const appid = match ? parseInt(match[1], 10) : (window.__LuaToolsCurrentAppId || NaN);

                if (!isNaN(appid)) {
                    const pillBtn = steamdbContainer.querySelector('.luatools-button');
                    if (pillBtn) {
                        // Skip if pills already built for this appid
                        var existingPills = pillBtn.querySelector('.luatools-pills-container');
                        if (!(existingPills && existingPills.dataset.appid === String(appid) && existingPills.dataset.content)) {
                            fetchGamesDatabase().then(function (db) {
                                const btn = steamdbContainer.querySelector('.luatools-button');
                                if (!btn) return;

                                let pillsContainer = btn.querySelector('.luatools-pills-container');

                                if (!pillsContainer) {
                                    pillsContainer = document.createElement('div');
                                    pillsContainer.className = 'luatools-pills-container';
                                    btn.appendChild(pillsContainer);
                                }
                                pillsContainer.dataset.appid = String(appid);

                                const key = String(appid);
                                const gameData = (db && db[key]) ? db[key] : null;

                                // check denuvo
                                const drmNotice = document.querySelector('.DRM_notice');
                                const hasDenuvo = drmNotice && drmNotice.textContent.includes('Denuvo');

                                fetchFixes(appid).then(function (fixesData) {
                                    // If backend is rate-limited, treat fixes as unknown (don't show pill)
                                    if (fixesData && fixesData.rateLimited) {
                                        return; // skip pills rendering while rate-limited
                                    }
                                    const hasFixes = fixesData && (
                                        (fixesData.genericFix && fixesData.genericFix.status === 200) ||
                                        (fixesData.onlineFix && fixesData.onlineFix.status === 200)
                                    );
                                    const showDenuvoPill = hasDenuvo && !hasFixes;

                                    const cacheKey = JSON.stringify({
                                        d: gameData || 'untested',
                                        showDenuvo: showDenuvoPill,
                                        hasFixes: hasFixes
                                    });

                                    if (pillsContainer.dataset.content === cacheKey) return;
                                    pillsContainer.dataset.content = cacheKey;

                                    pillsContainer.innerHTML = '';

                                    let status = 'untested';
                                    if (gameData && typeof gameData.playable !== 'undefined') {
                                        if (gameData.playable === 1) status = 'playable';
                                        else if (gameData.playable === 0) status = 'unplayable';
                                        else if (gameData.playable === 2) status = 'needs_fixes';
                                    }

                                    if (status === 'untested' && hasFixes) {
                                        status = 'needs_fixes';
                                    }

                                    if (status !== 'untested') {
                                        const pill = document.createElement('span');
                                        pill.className = 'luatools-pill';
                                        if (status === 'playable') {
                                            pill.classList.add('green');
                                            pill.textContent = t('gameStatus.playable', 'Playable');
                                        } else if (status === 'unplayable') {
                                            pill.classList.add('red');
                                            pill.textContent = t('gameStatus.unplayable', 'Unplayable');
                                        } else if (status === 'needs_fixes') {
                                            pill.classList.add('yellow');
                                            pill.textContent = t('gameStatus.needsFixes', 'Needs fixes');
                                        }
                                        pillsContainer.appendChild(pill);
                                    }

                                    // reset button state
                                    const btn = steamdbContainer.querySelector('.luatools-button');
                                    if (btn) {
                                        btn.style.opacity = '';
                                        btn.style.pointerEvents = '';
                                        btn.style.cursor = '';
                                        const span = btn.querySelector('span');
                                        if (span && span.textContent === 'Unplayable') {
                                            span.textContent = lt('Add via LuaTools');
                                        }
                                    }

                                    if (showDenuvoPill) {
                                        const pill = document.createElement('span');
                                        pill.className = 'luatools-pill orange';
                                        pill.textContent = t('gameStatus.denuvo', 'Denuvo');
                                        pillsContainer.appendChild(pill);
                                    }
                                });
                            });
                        }
                    }
                }
            } catch (e) {
                /* ignore */
            }
        } else {
            if (!logState.missingOnce) {
                backendLog('LuaTools: steamdbContainer not found on this page');
                logState.missingOnce = true;
            }
        }
    }

    // Try to add the button immediately if DOM is ready
    function onFrontendReady() {
        // Fetch settings + translations FIRST, then insert the button once in the correct language
        try {
            fetchSettingsConfig(true).then(function (cfg) {
                try {
                    ensureLuaToolsStyles();
                } catch (_) { }

                // Show disclaimer after translations are loaded so it displays in the correct language
                try {
                    if (window.location.hostname === 'store.steampowered.com') {
                        if (localStorage.getItem('luatools millennium disclaimer accepted') !== '1') {
                            showMillenniumDisclaimerModal();
                        }
                    }
                } catch (_) { }

                // Now translations are ready — insert the button in the correct language
                addLuaToolsButton();
            }).catch(function (_) {
                // Settings failed, still insert button (English fallback)
                addLuaToolsButton();
            });
        } catch (_) {
            addLuaToolsButton();
        }

        // Show gamepad hint if connected (only in Big Picture mode)
        setTimeout(function () {
            if (window.GamepadNav && window.GamepadNav.isConnected && window.GamepadNav.isConnected()) {
                backendLog('[LuaTools] Gamepad detected - Navigation enabled');

                // Only show visual hint in Big Picture mode
                if (window.__LUATOOLS_IS_BIG_PICTURE__) {
                    const hint = document.createElement('div');
                    hint.id = 'luatools-gamepad-hint';
                    hint.innerHTML = '🎮 ' + lt('bigpicture.mouseTip');
                    hint.style.cssText = '\
                        position: fixed;\
                        bottom: 20px;\
                        right: 20px;\
                        background: rgba(11, 20, 30, 0.9);\
                        color: #66c0f4;\
                        padding: 12px 16px;\
                        border-radius: 8px;\
                        font-size: 14px;\
                        z-index: 99998;\
                        border: 1px solid rgba(102, 192, 244, 0.3);\
                        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);\
                        animation: fadeInOut 3s ease-in-out;\
                    ';

                    // Add CSS animation if not already present
                    if (!document.querySelector('#luatools-gamepad-hint-styles')) {
                        const style = document.createElement('style');
                        style.id = 'luatools-gamepad-hint-styles';
                        style.textContent = '\
                            @keyframes fadeInOut {\
                                0% { opacity: 0; transform: translateY(10px); }\
                                10% { opacity: 1; transform: translateY(0); }\
                                90% { opacity: 1; transform: translateY(0); }\
                                100% { opacity: 0; transform: translateY(10px); }\
                            }\
                        ';
                        document.head.appendChild(style);
                    }

                    document.body.appendChild(hint);

                    // Auto-remove after animation
                    setTimeout(function () {
                        if (hint && hint.parentElement) {
                            hint.remove();
                        }
                    }, 3000);
                }
            }
        }, 500);

        // Ask backend if there is a queued startup message from InitApis
        try {
            if (typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
                Millennium.callServerMethod('luatools', 'GetInitApisMessage', {
                    contentScriptQuery: ''
                }).then(function (res) {
                    try {
                        const payload = typeof res === 'string' ? JSON.parse(res) : res;
                        if (payload && payload.message) {
                            const msg = String(payload.message);
                            // Check if this is an update message (contains "update" or "restart")
                            const isUpdateMsg = msg.toLowerCase().includes('update') || msg.toLowerCase().includes('restart');

                            if (isUpdateMsg) {
                                // For update messages, use confirm dialog with OK (restart) and Cancel options
                                showLuaToolsConfirm('LuaTools', msg, function () {
                                    // User clicked Confirm - restart Steam
                                    try {
                                        Millennium.callServerMethod('luatools', 'RestartSteam', {
                                            contentScriptQuery: ''
                                        });
                                    } catch (_) { }
                                }, function () {
                                    // User clicked Cancel - do nothing (just closes dialog)
                                });
                            } else {
                                // For non-update messages, use regular alert
                                ShowLuaToolsAlert('LuaTools', msg);
                            }
                        }
                    } catch (_) { }
                });
                // Also show loaded apps list if present (only once per session, store page only)
                try {
                    if (window.location.hostname === 'store.steampowered.com') {
                        if (!sessionStorage.getItem('LuaToolsLoadedAppsGate')) {
                            sessionStorage.setItem('LuaToolsLoadedAppsGate', '1');
                            Millennium.callServerMethod('luatools', 'ReadLoadedApps', {
                                contentScriptQuery: ''
                            }).then(function (res) {
                                try {
                                    const payload = typeof res === 'string' ? JSON.parse(res) : res;
                                    const apps = (payload && payload.success && Array.isArray(payload.apps)) ? payload.apps : [];
                                    if (apps.length > 0) {
                                        showLoadedAppsPopup(apps);
                                    }
                                } catch (_) { }
                            });
                        }
                    }
                } catch (_) { }
            }
        } catch (_) { }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onFrontendReady);
    } else {
        onFrontendReady();
    }

    // Delegate click handling in case the DOM is re-rendered and listeners are lost
    // Use bubble phase instead of capture phase to avoid interfering with gamepad navigation
    document.addEventListener('click', function (evt) {
        // Quick exit if target doesn't have closest method or isn't an element
        if (!evt.target || !evt.target.closest) return;

        const anchor = evt.target.closest('.luatools-button');
        if (anchor) {
            evt.preventDefault();
            evt.stopPropagation(); // Stop propagation to avoid conflicts
            backendLog('LuaTools delegated click');
            try {
                const match = window.location.href.match(/https:\/\/store\.steampowered\.com\/app\/(\d+)/) || window.location.href.match(/https:\/\/steamcommunity\.com\/app\/(\d+)/);
                const appid = match ? parseInt(match[1], 10) : NaN;
                if (!isNaN(appid) && typeof Millennium !== 'undefined' && typeof Millennium.callServerMethod === 'function') {
                    if (runState.inProgress && runState.appid === appid) {
                        backendLog('LuaTools: operation already in progress for this appid');
                        return;
                    }

                    // Helper that continues with the normal add flow
                    const continueWithAdd = function () {
                        if (!document.querySelector('.luatools-overlay')) {
                            showTestPopup();
                        }
                        runState.inProgress = true;
                        runState.appid = appid;
                        Millennium.callServerMethod('luatools', 'StartAddViaLuaTools', {
                            appid,
                            contentScriptQuery: ''
                        }).then(function(res) {
                            try {
                                const parsed = typeof res === 'string' ? JSON.parse(res) : res;
                                if (parsed && parsed.error === 'already_in_progress') {
                                    // Backend dedup guard triggered — show toast and attach to existing download
                                    try { showLuaToolsToast('⏳ Already downloading AppID ' + appid + ' — attaching…', 3000, 'info'); } catch (_) {}
                                    // Still start polling to show progress of the already-running download
                                    startPolling(appid);
                                    return;
                                }
                            } catch (_) {}
                            try { LuaToolsMods.fireHook('onDownloadStart', { appid: appid }); } catch (_) { }
                            startPolling(appid);
                        }).catch(function() {
                            try { LuaToolsMods.fireHook('onDownloadStart', { appid: appid }); } catch (_) { }
                            startPolling(appid);
                        });
                    };

                    // First check if it's a DLC
                    fetch('https://store.steampowered.com/api/appdetails?appids=' + appid + '&filters=basic')
                        .then(function (res) {
                            return res.json();
                        })
                        .then(function (data) {
                            if (data && data[appid] && data[appid].success && data[appid].data) {
                                const info = data[appid].data;
                                if (info.type === 'dlc' && info.fullgame && info.fullgame.appid) {
                                    showDlcWarning(appid, info.fullgame.appid, info.fullgame.name);
                                    return;
                                }
                            }

                            // Not a DLC (or failed to check), proceed with database check
                            return fetchGamesDatabase().then(function (db) {
                                try {
                                    const key = String(appid);
                                    const gameData = db && db[key] ? db[key] : null;
                                    if (gameData && gameData.playable === 0) {
                                        // warning modal
                                        showLuaToolsPlayableWarning('This game may not work, support for it wont be given in our discord', function () {
                                            continueWithAdd();
                                        }, function () { });
                                    } else {
                                        continueWithAdd();
                                    }
                                } catch (_) {
                                    continueWithAdd();
                                }
                            });
                        })
                        .catch(function (err) {
                            backendLog('LuaTools: DLC check failed: ' + err);
                            continueWithAdd();
                        });
                }
            } catch (_) { }
        }
    }, false); // Changed from true to false (bubble phase instead of capture phase)

    // Poll backend for progress and update progress bar and text
    function startPolling(appid) {
        let done = false;
        let lastCheckedApi = null;
        let successfulApi = null; // Track which API successfully found the file

        // Speed + ETA tracking
        let lastBytesRead = 0;
        let lastPollTime = Date.now();
        let speedSamples = []; // rolling window of KB/s samples

        function formatSpeed(kbps) {
            if (kbps >= 1024) return (kbps / 1024).toFixed(1) + ' MB/s';
            return Math.round(kbps) + ' KB/s';
        }
        function formatETA(seconds) {
            if (!isFinite(seconds) || seconds <= 0) return '';
            if (seconds < 60) return Math.ceil(seconds) + 's';
            const m = Math.floor(seconds / 60), s = Math.ceil(seconds % 60);
            return m + 'm ' + s + 's';
        }

        // Adaptive poll rate: faster when overlay visible, slower when hidden
        let pollInterval = 300;
        const timer = setInterval(() => {
            const overlay = document.querySelector('.luatools-overlay');
            const newInterval = overlay ? 300 : 1000;
            // (interval change takes effect next tick — acceptable for our purposes)

            if (done) {
                clearInterval(timer);
                return;
            }
            try {
                Millennium.callServerMethod('luatools', 'GetAddViaLuaToolsStatus', {
                    appid,
                    contentScriptQuery: ''
                }).then(function (res) {
                    try {
                        const payload = typeof res === 'string' ? JSON.parse(res) : res;
                        const st = payload && payload.state ? payload.state : {};

                        // Try to find overlay (may or may not be visible)
                        const overlay = document.querySelector('.luatools-overlay');
                        const title = overlay ? overlay.querySelector('.luatools-title') : null;
                        const status = overlay ? overlay.querySelector('.luatools-status') : null;
                        const wrap = overlay ? overlay.querySelector('.luatools-progress-wrap') : null;
                        const progressInfo = overlay ? overlay.querySelector('.luatools-progress-info') : null;
                        const percent = overlay ? overlay.querySelector('.luatools-percent') : null;
                        const downloadSize = overlay ? overlay.querySelector('.luatools-download-size') : null;
                        const bar = overlay ? overlay.querySelector('.luatools-progress-bar') : null;

                        // Update individual API status in the list
                        if (overlay) {
                            const colors = getThemeColors();
                            const apiItems = overlay.querySelectorAll('.luatools-api-item');

                            // Track successful API when download/processing starts
                            if ((st.status === 'downloading' || st.status === 'processing' || st.status === 'installing' || st.status === 'done') && st.currentApi && !successfulApi) {
                                successfulApi = st.currentApi;

                                // Mark all APIs: not found before successful, skipped after
                                let foundSuccessful = false;
                                apiItems.forEach((item) => {
                                    const apiName = item.getAttribute('data-api-name');
                                    const apiStatus = item.querySelector('.luatools-api-status');
                                    if (!apiStatus) return;

                                    if (apiName === successfulApi) {
                                        foundSuccessful = true;
                                        item.style.background = `rgba(${colors.rgbString},0.2)`;
                                        item.style.borderColor = colors.accent;
                                        apiStatus.innerHTML = `<span style="color:${colors.accent};">${lt('Found')}</span><i class="fa-solid fa-check" style="color:${colors.accent};"></i>`;
                                    } else if (!foundSuccessful) {
                                        // This API comes before the successful one, check if it has an error first
                                        if (st.apiErrors && st.apiErrors[apiName]) {
                                            const apiError = st.apiErrors[apiName];
                                            item.style.background = `rgba(255, 0, 0, 0.15)`;
                                            item.style.borderColor = '#ff5c5c';
                                            if (apiError.type === 'timeout') {
                                                apiStatus.innerHTML = `<span style="color:#ff5c5c;">${lt('Error, Timed Out')}</span><i class="fa-solid fa-clock" style="color:#ff5c5c;"></i>`;
                                            } else if (apiError.type === 'error') {
                                                const code = apiError.code ? String(apiError.code) : '';
                                                apiStatus.innerHTML = `<span style="color:#ff5c5c;">${lt('Error, Code: {code}').replace('{code}', code)}</span><i class="fa-solid fa-exclamation-triangle" style="color:#ff5c5c;"></i>`;
                                            }
                                        } else {
                                            // Mark as not found
                                            item.style.background = `rgba(0,0,0,0.2)`;
                                            item.style.borderColor = colors.borderRgba;
                                            apiStatus.innerHTML = `<span style="color:${colors.textSecondary};">${lt('Not found')}</span><i class="fa-solid fa-xmark" style="color:${colors.textSecondary};"></i>`;
                                        }
                                    } else {
                                        // This API comes after the successful one, mark as skipped
                                        item.style.background = `rgba(0,0,0,0.15)`;
                                        item.style.borderColor = colors.borderRgba;
                                        apiStatus.innerHTML = `<span style="color:${colors.textSecondary};">${lt('Skipped')}</span><i class="fa-solid fa-minus" style="color:${colors.textSecondary};"></i>`;
                                    }
                                });
                            }

                            // Mark previous API as not found if we moved to a new one (only during checking phase)
                            if (st.status === 'checking' && st.currentApi && st.currentApi !== lastCheckedApi && lastCheckedApi) {
                                apiItems.forEach((item) => {
                                    const apiName = item.getAttribute('data-api-name');
                                    const apiStatus = item.querySelector('.luatools-api-status');
                                    if (!apiStatus) return;

                                    if (apiName === lastCheckedApi) {
                                        item.style.background = `rgba(0,0,0,0.2)`;
                                        item.style.borderColor = colors.borderRgba;
                                        apiStatus.innerHTML = `<span style="color:${colors.textSecondary};">${lt('Not found')}</span><i class="fa-solid fa-xmark" style="color:${colors.textSecondary};"></i>`;
                                    }
                                });
                            }

                            // Update current API status during checking
                            if (st.status === 'checking' && st.currentApi) {
                                apiItems.forEach((item) => {
                                    const apiName = item.getAttribute('data-api-name');
                                    const apiStatus = item.querySelector('.luatools-api-status');
                                    if (!apiStatus) return;

                                    if (apiName === st.currentApi) {
                                        item.style.background = `rgba(${colors.rgbString},0.15)`;
                                        item.style.borderColor = colors.accent;
                                        apiStatus.innerHTML = `<span style="color:${colors.accent};">${lt('Checking…')}</span><i class="fa-solid fa-spinner" style="color:${colors.accent};animation: spin 1.5s linear infinite;"></i>`;
                                    }
                                });

                                lastCheckedApi = st.currentApi;
                            }

                            // Show error statuses for APIs that errored (when not checking them anymore)
                            if (st.apiErrors && typeof st.apiErrors === 'object') {
                                apiItems.forEach((item) => {
                                    const apiName = item.getAttribute('data-api-name');
                                    const apiStatus = item.querySelector('.luatools-api-status');
                                    if (!apiStatus || !apiName) return;

                                    const apiError = st.apiErrors[apiName];
                                    if (!apiError) return;

                                    // Only show error if this API is not currently being checked
                                    if (st.currentApi === apiName && st.status === 'checking') return;

                                    // Don't overwrite "Found" status
                                    const statusText = apiStatus.textContent || '';
                                    if (statusText.includes('Found') || statusText.includes('Encontrado')) return;

                                    item.style.background = `rgba(255, 0, 0, 0.15)`;
                                    item.style.borderColor = '#ff5c5c';

                                    if (apiError.type === 'timeout') {
                                        apiStatus.innerHTML = `<span style="color:#ff5c5c;">${lt('Error, Timed Out')}</span><i class="fa-solid fa-clock" style="color:#ff5c5c;"></i>`;
                                    } else if (apiError.type === 'error') {
                                        const code = apiError.code ? String(apiError.code) : '';
                                        apiStatus.innerHTML = `<span style="color:#ff5c5c;">${lt('Error, Code: {code}').replace('{code}', code)}</span><i class="fa-solid fa-exclamation-triangle" style="color:#ff5c5c;"></i>`;
                                    }
                                });
                            }
                        }

                        // Update UI if overlay is present
                        if (st.status === 'checking' && st.currentApi && title) {
                            title.textContent = lt('LuaTools · {api}').replace('{api}', st.currentApi);
                        } else if ((st.status === 'downloading' || st.status === 'processing' || st.status === 'installing') && title) {
                            title.textContent = t('common.appName', 'LuaTools');
                        }

                        if (status) {
                            if (st.status === 'checking') status.textContent = lt('Checking availability…');
                            if (st.status === 'downloading') status.textContent = lt('Downloading…');
                            if (st.status === 'processing') status.textContent = lt('Processing package…');
                            if (st.status === 'installing') status.textContent = lt('Installing…');
                            if (st.status === 'checking content') status.textContent = lt('Checking content…');
                            // if (st.status === 'done') status.textContent = lt('Finishing…');
                            if (st.status === 'failed') status.textContent = lt('Failed');
                        }
                        if (["downloading", "processing", "installing"].includes(st.status)) {
                            // reveal progress UI (if overlay visible)
                            if (wrap && wrap.style.display === 'none') wrap.style.display = 'block';
                            if (progressInfo && progressInfo.style.display === 'none') {
                                progressInfo.style.display = 'flex';
                            }

                            const total = st.totalBytes || 0;
                            const read = st.bytesRead || 0;
                            let pct = total > 0 ? Math.floor((read / total) * 100) : (read ? 1 : 0);
                            if (pct > 100) pct = 100;
                            if (pct < 0) pct = 0;

                            // Update bar and percentage
                            if (bar) bar.style.width = pct + '%';
                            if (percent) percent.textContent = pct + '%';

                            // Format file sizes
                            const formatBytes = (bytes) => {
                                if (!bytes || bytes === 0) return '0 B';
                                const k = 1024;
                                const sizes = ['B', 'KB', 'MB', 'GB'];
                                const i = Math.floor(Math.log(bytes) / Math.log(k));
                                return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
                            };
                            if (downloadSize) {
                                downloadSize.textContent = total > 0
                                    ? formatBytes(read) + ' / ' + formatBytes(total)
                                    : (read > 0 ? formatBytes(read) : '');
                            }

                            // Speed + ETA calculation (only during active download)
                            if (st.status === 'downloading' && read > 0) {
                                const now = Date.now();
                                const dtMs = now - lastPollTime;
                                const dBytes = read - lastBytesRead;
                                if (dtMs > 0 && dBytes >= 0) {
                                    const kbps = (dBytes / 1024) / (dtMs / 1000);
                                    if (kbps > 0) {
                                        speedSamples.push(kbps);
                                        if (speedSamples.length > 6) speedSamples.shift(); // keep last 6 samples
                                    }
                                }
                                lastBytesRead = read;
                                lastPollTime = now;

                                // Display smoothed speed
                                const overlaySpeed = overlay ? overlay.querySelector('.luatools-speed') : null;
                                const overlayEta = overlay ? overlay.querySelector('.luatools-eta') : null;
                                if (overlaySpeed && speedSamples.length > 0) {
                                    const avgKbps = speedSamples.reduce((a, b) => a + b, 0) / speedSamples.length;
                                    overlaySpeed.textContent = '⬇ ' + formatSpeed(avgKbps);
                                    if (overlayEta && total > 0 && avgKbps > 0) {
                                        const remaining = (total - read) / 1024 / avgKbps;
                                        overlayEta.textContent = 'ETA ' + formatETA(remaining);
                                    }
                                }
                            } else if (st.status !== 'downloading') {
                                // Reset speed tracking when not downloading
                                lastBytesRead = 0;
                                speedSamples = [];
                                const overlaySpeed = overlay ? overlay.querySelector('.luatools-speed') : null;
                                const overlayEta = overlay ? overlay.querySelector('.luatools-eta') : null;
                                if (overlaySpeed) overlaySpeed.textContent = '';
                                if (overlayEta) overlayEta.textContent = '';
                            }

                            // Show Cancel button during download
                            const cancelBtn = overlay ? overlay.querySelector('.luatools-cancel-btn') : null;
                            if (cancelBtn && st.status === 'downloading') cancelBtn.style.display = '';
                        }
                        
                        if (["checking content", "done"].includes(st.status)) {
                            // Update popup if visible
                            if (title) title.textContent = t('common.appName', 'LuaTools');
                            if (bar) bar.style.width = '100%';
                            if (percent) percent.textContent = '100%';

                            // hide progress visuals after a short beat
                            if (wrap || progressInfo) {
                                setTimeout(function () {
                                    if (wrap) wrap.style.display = 'none';
                                    if (progressInfo) progressInfo.style.display = 'none';
                                }, 300);
                            }

                            // Hide Cancel button
                            const cancelBtn = overlay ? overlay.querySelector('.luatools-cancel-btn') : null;
                            if (cancelBtn) cancelBtn.style.display = 'none';
                        }

                        if (st.status === 'done') {
                            try { LuaToolsMods.fireHook('onDownloadComplete', { appid: runState.appid, source: st.api || '' }); } catch (_) { }
                            try { showLuaToolsToast('✅ ' + (st.api || 'Downloaded') + ' — AppID ' + runState.appid, 4000, 'success'); } catch (_) { }
                            // Update popup if visible
                            if (status) {
                                const result = st.contentCheckResult;
                                
                                if (!result) return status.innerText = lt('Game added!');

                                // \u00A0 is a white space (unless it's automatically trimmed)
                                const status_content = [
                                    lt("Game added!"),
                                    lt("Content details =>"),
                                    `\u00A0\u00A0• ${lt("Workshop: ")}${lt(result.workshop)}`,
                                ]
    
                                if (result.dlc.missing.length || result.dlc.included.length) {
                                    status_content.push(`\u00A0\u00A0• ${lt("Dlc: ")}`)
                                    
                                    if (result.dlc.included.length > 0) {
                                        status_content.push(`\u00A0\u00A0\u00A0\u00A0◦ ${lt("Included")}: ${result.dlc.included.length}`)
                                    }
                                    if (result.dlc.missing.length > 0) {
                                        status_content.push(`\u00A0\u00A0\u00A0\u00A0◦ ${lt("Missing")}: ${result.dlc.missing.length} (${result.dlc.missing.join(', ')})`)
                                    }
                                }
                                
                                status.style.whiteSpace = "pre-line";
                                status.innerText = status_content.join('\n');
                            }

                            // Update Hide button to Close
                            const hideBtn = overlay ? overlay.querySelector('.luatools-hide-btn') : null;
                            if (hideBtn) hideBtn.innerHTML = '<span>' + lt('Close') + '</span>';
                            done = true;
                            clearInterval(timer);
                            runState.inProgress = false;
                            runState.appid = null;
                            // Remove button since game is added (works even if popup is hidden)
                            const btnEl = document.querySelector('.luatools-button');
                            if (btnEl && btnEl.parentElement) {
                                btnEl.parentElement.removeChild(btnEl);
                            }
                        }
                        if (st.status === 'failed') {
                            // Detect no-network early-abort
                            const isNoNetwork = st.error && (
                                st.error.toLowerCase().includes('network unavailable') ||
                                st.error.toLowerCase().includes('connection refused') ||
                                st.error.toLowerCase().includes('actively refused')
                            );

                            // Mark API list items
                            if (overlay && !successfulApi) {
                                const colors = getThemeColors();
                                const apiItems = overlay.querySelectorAll('.luatools-api-item');
                                apiItems.forEach((item) => {
                                    const apiName = item.getAttribute('data-api-name');
                                    const apiStatus = item.querySelector('.luatools-api-status');
                                    if (!apiStatus) return;

                                    if (isNoNetwork) {
                                        // All APIs offline — show disconnected icon
                                        const statusText = apiStatus.textContent || '';
                                        if (!statusText.includes('Not found') && !statusText.includes('Found')) {
                                            item.style.background = 'rgba(255,200,0,0.08)';
                                            item.style.borderColor = 'rgba(255,200,0,0.3)';
                                            apiStatus.innerHTML = '<span style="color:#ffc800;">Offline</span><i class="fa-solid fa-wifi" style="color:#ffc800;text-decoration:line-through;"></i>';
                                        }
                                        return;
                                    }

                                    if (st.apiErrors && st.apiErrors[apiName]) {
                                        const apiError = st.apiErrors[apiName];
                                        item.style.background = 'rgba(255, 0, 0, 0.15)';
                                        item.style.borderColor = '#ff5c5c';
                                        if (apiError.type === 'timeout') {
                                            apiStatus.innerHTML = `<span style="color:#ff5c5c;">${lt('Error, Timed Out')}</span><i class="fa-solid fa-clock" style="color:#ff5c5c;"></i>`;
                                        } else if (apiError.type === 'error') {
                                            const code = apiError.code ? String(apiError.code) : '';
                                            apiStatus.innerHTML = `<span style="color:#ff5c5c;">${lt('Error, Code: {code}').replace('{code}', code)}</span><i class="fa-solid fa-exclamation-triangle" style="color:#ff5c5c;"></i>`;
                                        }
                                        return;
                                    }

                                    const statusText = apiStatus.textContent || '';
                                    if (statusText.includes('Waiting') || statusText.includes('Esperando') || statusText.includes('Checking') || statusText.includes('Verificando')) {
                                        item.style.background = 'rgba(0,0,0,0.2)';
                                        item.style.borderColor = colors.borderRgba;
                                        apiStatus.innerHTML = `<span style="color:${colors.textSecondary};">${lt('Not found')}</span><i class="fa-solid fa-xmark" style="color:${colors.textSecondary};"></i>`;
                                    }
                                });

                                // No-network banner above the API list
                                if (isNoNetwork && !overlay.querySelector('.lt-no-network-banner')) {
                                    const banner = document.createElement('div');
                                    banner.className = 'lt-no-network-banner';
                                    banner.style.cssText = 'display:flex;align-items:center;gap:8px;background:rgba(255,200,0,0.1);border:1px solid rgba(255,200,0,0.35);border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:11px;color:#ffc800;';
                                    banner.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i><span>Network unavailable — connection refused by all sources. Check your proxy/VPN settings.</span>';
                                    const apiListContainer = overlay.querySelector('.luatools-api-list');
                                    if (apiListContainer) apiListContainer.before(banner);
                                }
                            }

                            // show error in the popup if visible
                            if (status) {
                                if (isNoNetwork) {
                                    status.innerHTML = '<span style="color:#ffc800;"><i class="fa-solid fa-wifi" style="margin-right:6px;"></i>Network unavailable</span>';
                                } else {
                                    status.textContent = lt('Failed: {error}').replace('{error}', st.error || lt('Unknown error'));
                                }
                            }
                            // Hide Cancel button and update Hide to Close
                            const cancelBtn = overlay ? overlay.querySelector('.luatools-cancel-btn') : null;
                            if (cancelBtn) cancelBtn.style.display = 'none';
                            const hideBtn = overlay ? overlay.querySelector('.luatools-hide-btn') : null;
                            if (hideBtn) hideBtn.innerHTML = '<span>' + lt('Close') + '</span>';
                            if (wrap) wrap.style.display = 'none';
                            if (progressInfo) progressInfo.style.display = 'none';
                            done = true;
                            clearInterval(timer);
                            runState.inProgress = false;
                            runState.appid = null;
                        }
                    } catch (_) { }
                });
            } catch (_) {
                clearInterval(timer);
            }
        }, 300);
    }

    // Also try after a delay to catch dynamically loaded content
    setTimeout(addLuaToolsButton, 1000);
    setTimeout(addLuaToolsButton, 3000);

    // Listen for URL changes (Steam uses pushState for navigation)
    let lastUrl = window.location.href;

    function checkUrlChange() {
        const currentUrl = window.location.href;
        if (currentUrl !== lastUrl) {
            lastUrl = currentUrl;
            // URL changed - reset flags and update buttons
            window.__LuaToolsButtonInserted = false;
            window.__LuaToolsRestartInserted = false;
            window.__LuaToolsIconInserted = false;
            window.__LuaToolsHeaderInserted = false;

            window.__LuaToolsPresenceCheckInFlight = false;
            window.__LuaToolsPresenceCheckAppId = undefined;
            // Update translations and re-add buttons
            ensureTranslationsLoaded(false).then(function () {
                updateButtonTranslations();
                addLuaToolsButton();
            });
        }
    }
    // Check URL changes periodically and on popstate
    // Reduced frequency to avoid blocking gamepad input
    setInterval(checkUrlChange, 2000); // Changed from 500ms to 2000ms (2 seconds)
    window.addEventListener('popstate', checkUrlChange);
    // Override pushState/replaceState to detect navigation
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;
    history.pushState = function () {
        originalPushState.apply(history, arguments);
        setTimeout(checkUrlChange, 100);
    };
    history.replaceState = function () {
        originalReplaceState.apply(history, arguments);
        setTimeout(checkUrlChange, 100);
    };

    // Use MutationObserver to catch dynamically added content
    // Heavily optimized and throttled version to avoid blocking gamepad
    if (typeof MutationObserver !== 'undefined') {
        let mutationTimeout;
        let lastMutationProcessTime = 0;
        const MUTATION_THROTTLE = 1000; // Only process once per second

        const observer = new MutationObserver(function (mutations) {
            // Additional throttle on top of debounce
            const now = Date.now();
            if (now - lastMutationProcessTime < MUTATION_THROTTLE) {
                return; // Skip if processed recently
            }

            // Debounce mutations to avoid blocking the UI
            clearTimeout(mutationTimeout);
            mutationTimeout = setTimeout(function () {
                lastMutationProcessTime = Date.now();

                let shouldUpdate = false;
                // Quick check: only process first 10 mutations to avoid long loops
                const mutationsToCheck = Math.min(mutations.length, 10);

                for (let i = 0; i < mutationsToCheck; i++) {
                    const mutation = mutations[i];
                    if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                        // Only check first 3 added nodes to avoid blocking
                        const nodesToCheck = Math.min(mutation.addedNodes.length, 3);

                        for (let j = 0; j < nodesToCheck; j++) {
                            const node = mutation.addedNodes[j];
                            if (node.nodeType === 1) { // Element node
                                // Quick class check without querySelector (faster)
                                if (node.classList && (
                                    node.classList.contains('steamdb-buttons') ||
                                    node.classList.contains('apphub_OtherSiteInfo') ||
                                    node.id === 'queueBtnFollow'
                                )) {
                                    shouldUpdate = true;
                                    break;
                                }
                            }
                        }
                    }
                    if (shouldUpdate) break;
                }

                if (shouldUpdate) {
                    updateButtonTranslations();
                    addLuaToolsButton();
                }
            }, 300); // Increased debounce to 300ms
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    function showLoadedAppsPopup(apps) {
        // Avoid duplicates
        if (document.querySelector('.luatools-loadedapps-overlay')) return;
        ensureFontAwesome();
        ensureLuaToolsStyles();
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.2s ease-out;';
        overlay.className = 'luatools-loadedapps-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.2s ease-out;';
        overlay.className = 'luatools-loadedapps-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(8px);z-index:99999;display:flex;align-items:center;justify-content:center;';
        const modal = document.createElement('div');
        const loadedAppsModalColors = getThemeColors();
        modal.style.cssText = `background:${loadedAppsModalColors.modalBg};color:${loadedAppsModalColors.text};border:2px solid ${loadedAppsModalColors.border};border-radius:8px;width:460px;max-width:95vw;padding:14px 18px;box-shadow:0 20px 60px rgba(0,0,0,.8), 0 0 0 1px ${loadedAppsModalColors.shadowRgba};animation:slideUp 0.1s ease-out;`;
        const title = document.createElement('div');
        const loadedAppsTitleColors = getThemeColors();
        title.style.cssText = `font-size:14px;color:${loadedAppsTitleColors.text};margin-bottom:12px;font-weight:700;text-shadow:0 2px 8px ${loadedAppsTitleColors.shadow};background:${loadedAppsTitleColors.gradientLight};-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;text-align:center;`;
        title.textContent = lt('LuaTools · Added Games');
        const body = document.createElement('div');
        const loadedAppsBodyColors = getThemeColors();
        body.style.cssText = `font-size:13px;line-height:1.35;margin-bottom:10px;max-height:280px;overflow:auto;padding:12px;border:1px solid ${loadedAppsBodyColors.border};border-radius:8px;background:${loadedAppsBodyColors.bgContainer};`;
        if (apps && apps.length) {
            const list = document.createElement('div');
            apps.forEach(function (item) {
                const a = document.createElement('a');
                a.href = 'steam://install/' + String(item.appid);
                a.textContent = String(item.name || item.appid);
                const linkColors = getThemeColors();
                a.style.cssText = `display:block;color:${linkColors.textSecondary};text-decoration:none;padding:10px 16px;margin-bottom:8px;background:rgba(${linkColors.rgbString},0.08);border:1px solid rgba(${linkColors.rgbString},0.2);border-radius:4px;transition:all 0.3s ease;`;
                a.onmouseover = function () {
                    const c = getThemeColors();
                    this.style.background = `rgba(${c.rgbString},0.2)`;
                    this.style.borderColor = c.accent;
                    this.style.transform = 'translateX(4px)';
                    this.style.color = c.text;
                };
                a.onmouseout = function () {
                    const c = getThemeColors();
                    this.style.background = `rgba(${c.rgbString},0.08)`;
                    this.style.borderColor = `rgba(${c.rgbString},0.2)`;
                    this.style.transform = 'translateX(0)';
                    this.style.color = c.textSecondary;
                };
                a.onclick = function (e) {
                    e.preventDefault();
                    try {
                        window.location.href = a.href;
                    } catch (_) { }
                };
                a.oncontextmenu = function (e) {
                    e.preventDefault();
                    const url = 'https://steamdb.info/app/' + String(item.appid) + '/';
                    try {
                        Millennium.callServerMethod('luatools', 'OpenExternalUrl', {
                            url,
                            contentScriptQuery: ''
                        });
                    } catch (_) { }
                };
                list.appendChild(a);
            });
            body.appendChild(list);
        } else {
            body.style.textAlign = 'center';
            body.textContent = lt('No games found.');
        }
        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'margin-top:8px;display:flex;gap:8px;justify-content:space-between;align-items:center;';
        const instructionText = document.createElement('div');
        instructionText.style.cssText = 'font-size:12px;color:#8f98a0;';
        instructionText.textContent = lt('Left click to install, Right click for SteamDB');
        const dismissBtn = document.createElement('a');
        dismissBtn.className = 'luatools-btn';
        dismissBtn.innerHTML = '<span>' + lt('Dismiss') + '</span>';
        dismissBtn.href = '#';
        dismissBtn.onclick = function (e) {
            e.preventDefault();
            try {
                Millennium.callServerMethod('luatools', 'DismissLoadedApps', {
                    contentScriptQuery: ''
                });
            } catch (_) { }
            try {
                sessionStorage.setItem('LuaToolsLoadedAppsShown', '1');
            } catch (_) { }
            overlay.remove();
        };
        btnRow.appendChild(instructionText);
        btnRow.appendChild(dismissBtn);
        modal.appendChild(title);
        modal.appendChild(body);
        modal.appendChild(btnRow);
        overlay.appendChild(modal);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.remove();
        });
        document.body.appendChild(overlay);

        // Re-scan elements for gamepad navigation
        setTimeout(function () {
            if (window.GamepadNav) {
                window.GamepadNav.scanElements();
            }
        }, 150);
    }

    // ============================================
    // TOAST NOTIFICATION SYSTEM
    // ============================================

    var _toastStyleInjected = false;
    function showLuaToolsToast(message, durationMs, type) {
        if (!_toastStyleInjected) {
            var s = document.createElement('style');
            s.textContent = '@keyframes lt-toast-in{from{transform:translateX(100px);opacity:0}to{transform:translateX(0);opacity:1}}@keyframes lt-toast-out{from{opacity:1}to{opacity:0;transform:translateX(50px)}}';
            document.head.appendChild(s);
            _toastStyleInjected = true;
        }
        var colors = getThemeColors();
        var bgMap = { success: 'rgba(74,222,128,0.12)', error: 'rgba(248,113,113,0.12)', info: 'rgba(102,192,244,0.12)' };
        var borderMap = { success: 'rgba(74,222,128,0.3)', error: 'rgba(248,113,113,0.3)', info: 'rgba(102,192,244,0.3)' };
        var colorMap = { success: '#4ade80', error: '#f87171', info: '#66c0f4' };
        var t = type || 'info';
        var toast = document.createElement('div');
        toast.style.cssText = 'position:fixed;bottom:20px;right:20px;background:' + (bgMap[t] || bgMap.info) + ';color:' + (colorMap[t] || colorMap.info) + ';padding:10px 16px;border-radius:8px;border:1px solid ' + (borderMap[t] || borderMap.info) + ';font-size:12px;z-index:100001;box-shadow:0 4px 16px rgba(0,0,0,0.3);animation:lt-toast-in 0.3s ease;max-width:320px;backdrop-filter:blur(8px);';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(function () {
            toast.style.animation = 'lt-toast-out 0.3s ease forwards';
            setTimeout(function () { try { toast.remove(); } catch (_) { } }, 300);
        }, durationMs || 3000);
        return toast;
    }

    // ============================================
    // MOD LOADER ENGINE (Kite-compatible)
    // ============================================

    window.LuaToolsMods = {
        _mods: {},
        _hooks: {},
        version: '1.0.0',

        registerMod: function (modDef) {
            if (!modDef || !modDef.id) return;
            this._mods[modDef.id] = modDef;
            var hookNames = ['onOverlayOpen', 'onOverlayClose', 'onFixApplied', 'onFixFailed',
                'onGameDetected', 'onSettingsOpen', 'onDownloadStart', 'onDownloadComplete', 'onModsPanel'];
            for (var i = 0; i < hookNames.length; i++) {
                var hook = hookNames[i];
                if (typeof modDef[hook] === 'function') {
                    if (!this._hooks[hook]) this._hooks[hook] = [];
                    this._hooks[hook].push({ modId: modDef.id, fn: modDef[hook] });
                }
            }
            backendLog('ModLoader: Registered mod ' + modDef.id + ' v' + (modDef.version || '?'));
        },

        fireHook: function (hookName, data) {
            var handlers = this._hooks[hookName] || [];
            for (var i = 0; i < handlers.length; i++) {
                try { handlers[i].fn.call(this._mods[handlers[i].modId], data); }
                catch (err) { console.error('[ModLoader] ' + handlers[i].modId + '.' + hookName + ':', err); }
            }
        },

        getMods: function () {
            return Object.keys(this._mods).map(function (id) { return this._mods[id]; }.bind(this));
        },

        hasMod: function (id) { return !!this._mods[id]; },

        injectCSS: function (id, cssText) {
            var existing = document.getElementById('ltmod-css-' + id);
            if (existing) existing.remove();
            var style = document.createElement('style');
            style.id = 'ltmod-css-' + id;
            style.textContent = cssText;
            document.head.appendChild(style);
        },

        createPanel: function (options) {
            var colors = getThemeColors();
            var panel = document.createElement('div');
            panel.id = 'ltmod-panel-' + (options.id || 'unknown');
            panel.style.cssText = 'background:rgba(30,30,30,0.95);border:1px solid ' + colors.borderRgba + ';border-radius:6px;padding:10px;margin-top:8px;';
            if (options.title) {
                var title = document.createElement('div');
                title.style.cssText = 'font-size:12px;font-weight:600;color:' + colors.accent + ';margin-bottom:6px;';
                title.textContent = options.title;
                panel.appendChild(title);
            }
            if (options.content) {
                var content = document.createElement('div');
                content.style.cssText = 'font-size:11px;color:#aaa;line-height:1.4;';
                if (typeof options.content === 'string') content.textContent = options.content;
                else content.appendChild(options.content);
                panel.appendChild(content);
            }
            return panel;
        },

        showToast: function (message, durationMs) {
            showLuaToolsToast(message, durationMs, 'info');
        },

        getStorage: function (modId) {
            var prefix = 'ltmod_' + modId + '_';
            return {
                get: function (key, def) { try { var r = localStorage.getItem(prefix + key); return r === null ? (def !== undefined ? def : null) : JSON.parse(r); } catch (_) { return def !== undefined ? def : null; } },
                set: function (key, val) { try { localStorage.setItem(prefix + key, JSON.stringify(val)); } catch (_) { } },
                remove: function (key) { localStorage.removeItem(prefix + key); },
                clear: function () { var rm = []; for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && k.indexOf(prefix) === 0) rm.push(k); } rm.forEach(function (k) { localStorage.removeItem(k); }); },
                keys: function () { var r = []; for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && k.indexOf(prefix) === 0) r.push(k.substring(prefix.length)); } return r; }
            };
        }
    };

    // Load mods from backend
    function _loadMods() {
        if (typeof Millennium === 'undefined' || typeof Millennium.callServerMethod !== 'function') return;
        Millennium.callServerMethod('luatools', 'GetModList', { contentScriptQuery: '' })
            .then(function (res) {
                try {
                    var mods = typeof res === 'string' ? JSON.parse(res) : res;
                    if (!Array.isArray(mods) || mods.length === 0) return;
                    backendLog('ModLoader: Found ' + mods.length + ' mod(s)');

                    // Topological sort for dependencies
                    var modMap = {};
                    for (var i = 0; i < mods.length; i++) modMap[mods[i].id] = mods[i];
                    var sorted = [], visited = {};
                    function visit(mod) {
                        if (visited[mod.id]) return;
                        visited[mod.id] = true;
                        (mod.dependencies || []).forEach(function (d) { if (modMap[d]) visit(modMap[d]); });
                        sorted.push(mod);
                    }
                    mods.forEach(function (m) { visit(m); });

                    sorted.forEach(function (mod) {
                        if (!mod.enabled) return;
                        // Check deps
                        var missing = (mod.dependencies || []).filter(function (d) { return !modMap[d] || !modMap[d].enabled; });
                        if (missing.length > 0) {
                            showLuaToolsToast('⚠️ ' + mod.id + ' needs: ' + missing.join(', '), 5000, 'error');
                            return;
                        }
                        try {
                            // Load CSS
                            if (mod.style) {
                                Millennium.callServerMethod('luatools', 'GetModFile', { mod_id: mod.id, filename: mod.style, contentScriptQuery: '' })
                                    .then(function (css) { if (css) LuaToolsMods.injectCSS(mod.id, css); });
                            }
                            // Load JS
                            Millennium.callServerMethod('luatools', 'GetModFile', { mod_id: mod.id, filename: mod.main, contentScriptQuery: '' })
                                .then(function (js) {
                                    if (!js) return;
                                    var script = document.createElement('script');
                                    script.textContent = '(function(){try{' + js + '}catch(e){console.error("[ModLoader] ' + mod.id + ':",e)}})();';
                                    script.dataset.modId = mod.id;
                                    document.head.appendChild(script);
                                });
                        } catch (err) { console.error('[ModLoader] Failed: ' + mod.id, err); }
                    });
                } catch (e) { backendLog('ModLoader: parse error: ' + e.message); }
            })
            .catch(function (e) { /* Backend not ready */ });
    }

    // Boot mod loader after core init
    setTimeout(_loadMods, 800);

    // ============================================
    // GAMEPAD NAVIGATION INTEGRATION
    // ============================================
    // Note: The gamepad back handler is configured in the gamepad system at the top of this file
    // It already handles all overlay types automatically using OVERLAY_SELECTOR_STRING

})();