// WebSocket-Verbindung für Live-Updates
let socket = null;

// Debouncing für Updates
let updateQueueTimeout = null;
let updateWishlistTimeout = null;

// Cache für Counts
let cachedCounts = {
    wishlist: 0,
    queue: 0,
    played: 0
};

// Cache für API-Responses (TTL: optimiert für Performance)
let apiCache = {};
const CACHE_TTL = 5000; // 5 Sekunden für Listen
const CACHE_TTL_COUNT = 10000; // 10 Sekunden für Counts (weniger häufig geändert)

// Cache-Helper
function getCached(key, ttl = CACHE_TTL) {
    const cached = apiCache[key];
    if (cached && Date.now() - cached.timestamp < ttl) {
        return cached.data;
    }
    delete apiCache[key];
    return null;
}

function setCached(key, data) {
    apiCache[key] = {
        data: data,
        timestamp: Date.now()
    };
}

// Cache invalidation
function invalidateCache(pattern) {
    Object.keys(apiCache).forEach(key => {
        if (key.includes(pattern)) {
            delete apiCache[key];
        }
    });
}

if (typeof io !== 'undefined') {
    socket = io();
    
    socket.on('music:queue_updated', function(data) {
        console.log('Queue-Update empfangen:', data);
        // Invalidiere Cache
        invalidateCache('queue');
        // Verwende vollständige Queue-Daten aus Event
        if (data.queue !== undefined) {
            updateQueueDisplayDirect(data.queue);
        } else {
            // Fallback: Lade Daten falls nicht vorhanden
            updateQueueDisplay();
        }
    });
    
    socket.on('music:wish_added', function(data) {
        console.log('Wunsch hinzugefügt:', data);
        // Invalidiere Cache
        invalidateCache('wishlist');
        if (data.wish) {
            addWishToDisplayDirect(data.wish);
            // Aktualisiere Badge basierend auf tatsächlicher Anzahl im DOM
            const wishlistContainer = document.querySelector('#wishlist-list');
            if (wishlistContainer) {
                const wishItems = wishlistContainer.querySelectorAll('.list-group-item[data-wish-id]');
                cachedCounts.wishlist = wishItems.length;
                updateWishlistBadgeDirect(wishItems.length);
            } else {
                cachedCounts.wishlist += 1;
                updateWishlistBadgeDirect(cachedCounts.wishlist);
            }
        }
    });
    
    socket.on('music:wish_updated', function(data) {
        console.log('Wunsch aktualisiert:', data);
        // Invalidiere Cache
        invalidateCache('wishlist');
        if (data.wish) {
            updateWishInDisplay(data.wish);
            // Aktualisiere Badge basierend auf tatsächlicher Anzahl im DOM
            const wishlistContainer = document.querySelector('#wishlist-list');
            if (wishlistContainer) {
                const wishItems = wishlistContainer.querySelectorAll('.list-group-item[data-wish-id]');
                cachedCounts.wishlist = wishItems.length;
                updateWishlistBadgeDirect(wishItems.length);
            }
        }
    });
    
    socket.on('music:wishlist_cleared', function(data) {
        console.log('Wunschliste geleert', data);
        // Invalidiere Cache
        invalidateCache('wishlist');
        
        // Wenn force_reload gesetzt ist, lade die Seite komplett neu
        if (data && data.force_reload) {
            // Kurze Verzögerung, damit SocketIO-Event verarbeitet wird
            setTimeout(function() {
                window.location.reload();
            }, 100);
            return;
        }
        
        // Ansonsten normale DOM-Update
        clearWishlistDisplay();
        cachedCounts.wishlist = 0;
        updateWishlistBadgeDirect(0);
    });
    
    socket.on('music:played_updated', function(data) {
        console.log('Played-Update empfangen:', data);
        // Invalidiere Cache für Played-Liste
        invalidateCache('played');
        
        // Aktualisiere Badge
        if (data.count !== undefined) {
            updatePlayedBadgeDirect(data.count);
        }
        
        // Wenn Wish-Daten vorhanden sind, füge zur Played-Liste hinzu
        if (data.wish) {
            addToPlayedDisplayDirect(data.wish);
        }
    });
    
    socket.on('connect', function() {
        console.log('SocketIO verbunden');
        // Trete dem Musikmodul-Room bei
        socket.emit('music:join', {});
        console.log('Musikmodul: Room beigetreten');
        // Initialisiere Badges nach Verbindung
        setTimeout(initializeBadges, 500);
    });
    
    // Verlasse den Room beim Schließen der Seite oder Wechseln zu anderer Seite
    window.addEventListener('beforeunload', function() {
        if (socket && socket.connected) {
            socket.emit('music:leave', {});
        }
    });
    
    // Verlasse den Room auch bei Visibility Change (Tab-Wechsel) - optional für weitere Optimierung
    // Kommentiert aus, da es bei Tab-Wechseln zu aggressiv sein könnte
    // document.addEventListener('visibilitychange', function() {
    //     if (document.hidden && socket && socket.connected) {
    //         socket.emit('music:leave', {});
    //     } else if (!document.hidden && socket && socket.connected) {
    //         socket.emit('music:join', {});
    //     }
    // });
}

// Direktes DOM-Update für Queue ohne Fetch-Request
function updateQueueDisplayDirect(queueData) {
    // Debouncing: Warte 100ms bevor Update ausgeführt wird
    if (updateQueueTimeout) {
        clearTimeout(updateQueueTimeout);
    }
    
    updateQueueTimeout = setTimeout(() => {
        const queueContainer = document.querySelector('#queue-list');
        if (!queueContainer) return;
        
        // Aktualisiere Cache und Badge
        const queueCount = queueData ? queueData.length : 0;
        cachedCounts.queue = queueCount;
        updateQueueBadgeDirect(queueCount);
        
        if (!queueData || queueData.length === 0) {
            queueContainer.innerHTML = '<p class="text-muted text-center py-4">Warteschlange ist leer</p>';
            return;
        }
        
        // Erstelle Queue-Elemente
        queueContainer.innerHTML = queueData.map(entry => {
            const providerClass = entry.wish.provider === 'spotify' ? 'success' : 'danger';
            const wishCount = entry.wish.wish_count || 1;
            let countBadgeClass = 'bg-secondary';
            if (wishCount > 1) {
                if (wishCount <= 3) {
                    countBadgeClass = 'bg-primary';
                } else if (wishCount <= 5) {
                    countBadgeClass = 'bg-warning';
                } else {
                    countBadgeClass = 'bg-danger';
                }
            }
            
            const imageUrl = entry.wish.image_url && entry.wish.image_url !== 'undefined' && entry.wish.image_url !== 'null' && entry.wish.image_url.trim() !== '' ? entry.wish.image_url : null;
            const imageHtml = imageUrl
                ? `<div class="me-3 position-relative" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i><img data-src="${escapeHtml(imageUrl)}" alt="Cover" class="lazy-image position-absolute" style="width: 48px; height: 48px; object-fit: cover; border-radius: 4px; top: 0; left: 0; opacity: 0; transition: opacity 0.3s;" onerror="this.onerror=null; this.style.display='none';" onload="this.style.opacity='1'; this.previousElementSibling.style.display='none';"></div>`
                : `<div class="me-3" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i></div>`;
            
            return `
                <div class="list-group-item queue-item" data-queue-id="${entry.id}" data-position="${entry.position}" draggable="true">
                    <div class="d-flex align-items-center">
                        <i class="bi bi-grip-vertical text-muted me-2" style="cursor: move;"></i>
                        <span class="badge bg-secondary me-2">${entry.position}</span>
                        ${imageHtml}
                        <div class="flex-grow-1">
                            <h6 class="mb-1">
                                ${escapeHtml(entry.wish.title || 'Unbekannt')}
                                <span class="badge ${countBadgeClass} ms-2">${wishCount}x</span>
                            </h6>
                            <p class="text-muted mb-1 small">${escapeHtml(entry.wish.artist || 'Unbekannter Künstler')}</p>
                            <span class="badge bg-${providerClass} provider-badge">${entry.wish.provider}</span>
                        </div>
                        <button class="btn btn-sm btn-outline-danger" onclick="removeFromQueue(${entry.id})">
                            <i class="bi bi-x"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
        
        // Lade Bilder lazy
        loadLazyImages();
        
        // Re-initialisiere Drag & Drop
        initializeDragAndDrop();
    }, 100);
}

// Fallback: Lade Queue-Daten per Fetch (wenn Event keine Daten enthält)
function updateQueueDisplay() {
    const cacheKey = 'queue_list';
    const cached = getCached(cacheKey);
    if (cached) {
        updateQueueDisplayDirect(cached);
        return;
    }
    
    fetch('/music/api/queue/list')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Fehler beim Laden der Queue:', data.error);
                return;
            }
            setCached(cacheKey, data.queue);
            updateQueueDisplayDirect(data.queue);
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren der Queue:', error);
        });
}

// Direktes DOM-Update für Wish ohne Fetch-Request
function addWishToDisplayDirect(wish) {
    // Debouncing: Warte 100ms bevor Update ausgeführt wird
    if (updateWishlistTimeout) {
        clearTimeout(updateWishlistTimeout);
    }
    
    updateWishlistTimeout = setTimeout(() => {
        // Versuche mehrere Selektoren
        let wishlistContainer = document.querySelector('#wishlist-list');
        if (!wishlistContainer) {
            wishlistContainer = document.querySelector('#wishlist .list-group');
        }
        if (!wishlistContainer) {
            wishlistContainer = document.querySelector('#wishlist .card-body .list-group');
        }
        if (!wishlistContainer) return;
        
        // Prüfe ob Wunsch bereits existiert
        const existingWish = wishlistContainer.querySelector(`[data-wish-id="${wish.id}"]`);
        if (existingWish) {
            // Aktualisiere bestehenden Wunsch
            updateWishInDisplay(wish);
            return;
        }
        
        // Erstelle neues Wish-Element
        const wishItem = document.createElement('div');
        wishItem.className = 'list-group-item';
        wishItem.setAttribute('data-wish-id', wish.id);
        
        const providerClass = wish.provider === 'spotify' ? 'success' : 'danger';
        const wishCount = wish.wish_count || 1;
        let countBadgeClass = 'bg-secondary';
        if (wishCount > 1) {
            if (wishCount <= 3) {
                countBadgeClass = 'bg-primary';
            } else if (wishCount <= 5) {
                countBadgeClass = 'bg-warning';
            } else {
                countBadgeClass = 'bg-danger';
            }
        }
        
        const imageUrl = wish.image_url && wish.image_url !== 'undefined' && wish.image_url !== 'null' && wish.image_url.trim() !== '' ? wish.image_url : null;
        const imageHtml = imageUrl
            ? `<div class="me-3 position-relative" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i><img data-src="${escapeHtml(imageUrl)}" alt="Cover" class="lazy-image position-absolute" style="width: 48px; height: 48px; object-fit: cover; border-radius: 4px; top: 0; left: 0; opacity: 0; transition: opacity 0.3s;" onerror="this.onerror=null; this.style.display='none';" onload="this.style.opacity='1'; this.previousElementSibling.style.display='none';"></div>`
            : `<div class="me-3" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i></div>`;
        
        wishItem.innerHTML = `
            <div class="d-flex align-items-center">
                ${imageHtml}
                <div class="flex-grow-1">
                    <h6 class="mb-1">
                        ${escapeHtml(wish.title || 'Unbekannt')}
                        <span class="badge ${countBadgeClass} ms-2 wish-count-badge">${wishCount}x</span>
                    </h6>
                    <p class="text-muted mb-1 small">${escapeHtml(wish.artist || 'Unbekannter Künstler')}</p>
                    <span class="badge bg-${providerClass} provider-badge">${wish.provider}</span>
                </div>
                <div class="btn-group-vertical btn-group-sm">
                    <button class="btn btn-sm btn-success" onclick="addToQueue(${wish.id}, 'next')" title="An 1. Stelle einfügen">
                        <i class="bi bi-arrow-up-circle"></i>
                    </button>
                    <button class="btn btn-sm btn-primary" onclick="addToQueue(${wish.id}, 'last')" title="An letzter Stelle einfügen">
                        <i class="bi bi-arrow-down-circle"></i>
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="markAsPlayed(${wish.id})" title="Zu bereits gespielt verschieben">
                        <i class="bi bi-x-circle"></i>
                    </button>
                </div>
            </div>
        `;
        
        // Entferne "Leer"-Nachricht falls vorhanden
        const emptyMessage = wishlistContainer.querySelector('.text-muted.text-center');
        if (emptyMessage) {
            emptyMessage.remove();
        }
        
        // Stelle sicher, dass Container eine list-group ist
        if (!wishlistContainer.classList.contains('list-group')) {
            wishlistContainer.classList.add('list-group');
        }
        
        // Füge am Anfang der Liste hinzu
        if (wishlistContainer.children.length === 0) {
            wishlistContainer.appendChild(wishItem);
        } else {
            wishlistContainer.insertBefore(wishItem, wishlistContainer.firstChild);
        }
        
        // Aktualisiere Badge basierend auf tatsächlicher Anzahl
        const wishItems = wishlistContainer.querySelectorAll('.list-group-item[data-wish-id]');
        cachedCounts.wishlist = wishItems.length;
        updateWishlistBadgeDirect(wishItems.length);
        
        // Lade Bilder lazy
        loadLazyImages();
    }, 100);
}

// Aktualisiere bestehenden Wish in der Anzeige
function updateWishInDisplay(wish) {
    // Versuche mehrere Selektoren
    let wishlistContainer = document.querySelector('#wishlist-list');
    if (!wishlistContainer) {
        wishlistContainer = document.querySelector('#wishlist .list-group');
    }
    if (!wishlistContainer) {
        wishlistContainer = document.querySelector('#wishlist .card-body .list-group');
    }
    if (!wishlistContainer) return;
    
    const existingWish = wishlistContainer.querySelector(`[data-wish-id="${wish.id}"]`);
    if (!existingWish) {
        // Wenn nicht in Wishlist, aber Status ist pending, füge hinzu
        if (wish.status === 'pending') {
            addWishToDisplayDirect(wish);
        }
        return;
    }
    
    // Aktualisiere Wish-Count
    const wishCountBadge = existingWish.querySelector('.wish-count-badge');
    if (wishCountBadge && wish.wish_count) {
        wishCountBadge.textContent = wish.wish_count + 'x';
        // Aktualisiere Badge-Farbe basierend auf Count
        wishCountBadge.className = 'badge ms-2 wish-count-badge';
        if (wish.wish_count <= 3) {
            wishCountBadge.classList.add('bg-primary');
        } else if (wish.wish_count <= 5) {
            wishCountBadge.classList.add('bg-warning');
        } else {
            wishCountBadge.classList.add('bg-danger');
        }
    }
    
    // Wenn Status nicht mehr pending ist, entferne aus Wishlist
    if (wish.status !== 'pending') {
        existingWish.remove();
        // Prüfe ob Liste jetzt leer ist
        if (wishlistContainer.children.length === 0) {
            wishlistContainer.innerHTML = '<p class="text-muted text-center py-4">Keine Wünsche vorhanden</p>';
        }
        // Aktualisiere Badge
        const wishItems = wishlistContainer.querySelectorAll('.list-group-item[data-wish-id]');
        cachedCounts.wishlist = wishItems.length;
        updateWishlistBadgeDirect(wishItems.length);
    }
    
    // Lade Bilder lazy (falls Bild-URL aktualisiert wurde)
    loadLazyImages();
}

function clearWishlistDisplay() {
    // Versuche mehrere Selektoren
    let wishlistContainer = document.querySelector('#wishlist-list');
    if (!wishlistContainer) {
        wishlistContainer = document.querySelector('#wishlist .list-group');
    }
    if (!wishlistContainer) {
        wishlistContainer = document.querySelector('#wishlist .card-body .list-group');
    }
    if (!wishlistContainer) return;
    
    // Entferne ALLE Wish-Items aus dem DOM
    while (wishlistContainer.firstChild) {
        wishlistContainer.removeChild(wishlistContainer.firstChild);
    }
    
    // Setze leere Nachricht
    wishlistContainer.innerHTML = '<p class="text-muted text-center py-4">Keine Wünsche vorhanden</p>';
    
    // Aktualisiere Badge sofort
    updateWishlistBadgeDirect(0);
    cachedCounts.wishlist = 0;
    
    // Invalidiere alle Caches
    invalidateCache('wishlist');
}

// Direktes Badge-Update ohne Fetch-Request
function updateWishlistBadgeDirect(count) {
    cachedCounts.wishlist = count;
    const badge = document.querySelector('#wishlist-tab .badge');
    if (badge) {
        badge.textContent = count;
    }
}

function updateQueueBadgeDirect(count) {
    cachedCounts.queue = count;
    const badge = document.querySelector('#queue-tab .badge');
    if (badge) {
        badge.textContent = count;
    }
}

function updatePlayedBadgeDirect(count) {
    cachedCounts.played = count;
    const badge = document.querySelector('#played-tab .badge');
    if (badge) {
        badge.textContent = count;
    }
}

// Fallback: Lade Counts per Fetch (für Initial-Load)
function updateWishlistBadge() {
    const cacheKey = 'wishlist_count';
    const cached = getCached(cacheKey, CACHE_TTL_COUNT);
    if (cached !== null) {
        updateWishlistBadgeDirect(cached);
        return;
    }
    
    fetch('/music/api/wishlist/count')
        .then(response => response.json())
        .then(data => {
            const count = data.count || 0;
            setCached(cacheKey, count);
            updateWishlistBadgeDirect(count);
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren des Wishlist-Badges:', error);
        });
}

function updateQueueBadge() {
    const cacheKey = 'queue_count';
    const cached = getCached(cacheKey, CACHE_TTL_COUNT);
    if (cached !== null) {
        updateQueueBadgeDirect(cached);
        return;
    }
    
    fetch('/music/api/queue/count')
        .then(response => response.json())
        .then(data => {
            const count = data.count || 0;
            setCached(cacheKey, count);
            updateQueueBadgeDirect(count);
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren des Queue-Badges:', error);
        });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Lazy Loading für Bilder mit Intersection Observer
let imageObserver = null;

function loadLazyImages() {
    const lazyImages = document.querySelectorAll('img.lazy-image[data-src]');
    
    if (lazyImages.length === 0) return;
    
    if ('IntersectionObserver' in window) {
        // Erstelle Observer nur einmal, wenn noch nicht vorhanden
        if (!imageObserver) {
            imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        const imageUrl = img.dataset.src;
                        
                        // Prüfe ob URL gültig ist
                        if (!imageUrl || imageUrl === 'undefined' || imageUrl === 'null' || imageUrl.trim() === '') {
                            // Ungültige URL - verstecke Bild und zeige Platzhalter
                            img.removeAttribute('data-src');
                            img.classList.remove('lazy-image');
                            img.style.display = 'none';
                            observer.unobserve(img);
                            return;
                        }
                        
                        // Erstelle neues Image-Objekt zum Testen, bevor wir src setzen
                        const testImg = new Image();
                        testImg.onload = function() {
                            // Bild erfolgreich geladen
                            img.src = imageUrl;
                            img.removeAttribute('data-src');
                            img.classList.remove('lazy-image');
                            // Zeige Bild mit Fade-In
                            img.style.opacity = '1';
                            // Verstecke Platzhalter-Icon
                            const placeholder = img.previousElementSibling;
                            if (placeholder && (placeholder.tagName === 'I' || placeholder.tagName === 'DIV')) {
                                placeholder.style.display = 'none';
                            }
                            observer.unobserve(img);
                        };
                        testImg.onerror = function() {
                            // Bild konnte nicht geladen werden (404, etc.) - stumme Fehlerbehandlung
                            img.removeAttribute('data-src');
                            img.classList.remove('lazy-image');
                            img.style.display = 'none';
                            // Platzhalter-Icon bleibt sichtbar
                            observer.unobserve(img);
                        };
                        // Starte Test-Laden
                        testImg.src = imageUrl;
                    }
                });
            }, {
                rootMargin: '50px' // Lade Bilder 50px bevor sie sichtbar werden
            });
        }
        
        // Beobachte alle neuen Bilder
        lazyImages.forEach(img => {
            // Prüfe ob Bild bereits beobachtet wird
            if (!img.dataset.observed) {
                imageObserver.observe(img);
                img.dataset.observed = 'true';
            }
        });
    } else {
        // Fallback für Browser ohne IntersectionObserver
        lazyImages.forEach(img => {
            const imageUrl = img.dataset.src;
            if (imageUrl && imageUrl !== 'undefined' && imageUrl !== 'null' && imageUrl.trim() !== '') {
                img.src = imageUrl;
                img.removeAttribute('data-src');
                img.classList.remove('lazy-image');
            } else {
                // Ungültige URL - verstecke Bild
                img.style.display = 'none';
            }
        });
    }
}

function initializeDragAndDrop() {
    const queueList = document.getElementById('queue-list');
    if (!queueList) return;
    
    const queueItems = queueList.querySelectorAll('.queue-item');
    queueItems.forEach(item => {
        item.draggable = true;
        item.classList.add('draggable');
        
        item.addEventListener('dragstart', function(e) {
            this.classList.add('dragging');
        });
        
        item.addEventListener('dragend', function(e) {
            this.classList.remove('dragging');
        });
    });
}

// Lazy Loading für Tabs
let loadedTabs = {
    wishlist: false,
    queue: false,
    played: false
};

let playedPagination = {
    currentPage: 1,
    perPage: 50,
    total: 0,
    pages: 0
};

// Lade "Bereits gespielt" Tab beim ersten Öffnen
function loadPlayedTab(page = 1) {
    if (loadedTabs.played && page === 1) {
        return; // Bereits geladen
    }
    
    const playedContainer = document.querySelector('#played .list-group');
    if (!playedContainer) return;
    
    // Prüfe Cache
    const cacheKey = `played_list_${page}`;
    const cached = getCached(cacheKey);
    if (cached && page === 1) {
        // Verwende gecachte Daten
        playedContainer.innerHTML = '';
        cached.forEach(wish => {
            const wishItem = createPlayedItem(wish);
            playedContainer.appendChild(wishItem);
        });
        loadLazyImages();
        return;
    }
    
    // Zeige Loading-Indikator
    if (page === 1) {
        playedContainer.innerHTML = '<div class="text-center py-4"><div class="spinner-border" role="status"><span class="visually-hidden">Laden...</span></div></div>';
    }
    
    fetch(`/music/api/played/list?page=${page}&per_page=${playedPagination.perPage}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Fehler beim Laden der gespielten Lieder:', data.error);
                playedContainer.innerHTML = '<p class="text-muted text-center py-4">Fehler beim Laden</p>';
                return;
            }
            
            if (page === 1) {
                playedContainer.innerHTML = '';
            }
            
            if (!data.played || data.played.length === 0) {
                if (page === 1) {
                    playedContainer.innerHTML = '<p class="text-muted text-center py-4">Keine gespielten Lieder vorhanden</p>';
                }
                return;
            }
            
            // Cache für erste Seite
            if (page === 1) {
                setCached(cacheKey, data.played);
            }
            
            // Füge Einträge hinzu
            data.played.forEach(wish => {
                const wishItem = createPlayedItem(wish);
                playedContainer.appendChild(wishItem);
            });
            
            // Aktualisiere Pagination-Info
            if (data.pagination) {
                playedPagination.currentPage = data.pagination.page;
                playedPagination.total = data.pagination.total;
                playedPagination.pages = data.pagination.pages;
                
                // Erstelle/Update Pagination-Controls
                updatePlayedPaginationControls();
            }
            
            // Lade Bilder lazy
            loadLazyImages();
            
            loadedTabs.played = true;
        })
        .catch(error => {
            console.error('Fehler beim Laden der gespielten Lieder:', error);
            playedContainer.innerHTML = '<p class="text-muted text-center py-4">Fehler beim Laden</p>';
        });
}

// Update Pagination-Controls für "Bereits gespielt"
function updatePlayedPaginationControls() {
    let paginationContainer = document.getElementById('played-pagination');
    if (!paginationContainer) {
        // Erstelle Pagination-Container
        const playedCard = document.querySelector('#played .card-body');
        if (!playedCard) return;
        
        paginationContainer = document.createElement('div');
        paginationContainer.id = 'played-pagination';
        paginationContainer.className = 'mt-3 d-flex justify-content-center';
        playedCard.appendChild(paginationContainer);
    }
    
    if (playedPagination.pages <= 1) {
        paginationContainer.innerHTML = '';
        return;
    }
    
    let paginationHTML = '<nav><ul class="pagination">';
    
    // Previous Button
    if (playedPagination.currentPage > 1) {
        paginationHTML += `<li class="page-item"><a class="page-link" href="#" onclick="loadPlayedTab(${playedPagination.currentPage - 1}); return false;">Vorherige</a></li>`;
    } else {
        paginationHTML += `<li class="page-item disabled"><span class="page-link">Vorherige</span></li>`;
    }
    
    // Page Numbers (max 5 Seiten anzeigen)
    const startPage = Math.max(1, playedPagination.currentPage - 2);
    const endPage = Math.min(playedPagination.pages, playedPagination.currentPage + 2);
    
    if (startPage > 1) {
        paginationHTML += `<li class="page-item"><a class="page-link" href="#" onclick="loadPlayedTab(1); return false;">1</a></li>`;
        if (startPage > 2) {
            paginationHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }
    
    for (let i = startPage; i <= endPage; i++) {
        if (i === playedPagination.currentPage) {
            paginationHTML += `<li class="page-item active"><span class="page-link">${i}</span></li>`;
        } else {
            paginationHTML += `<li class="page-item"><a class="page-link" href="#" onclick="loadPlayedTab(${i}); return false;">${i}</a></li>`;
        }
    }
    
    if (endPage < playedPagination.pages) {
        if (endPage < playedPagination.pages - 1) {
            paginationHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
        paginationHTML += `<li class="page-item"><a class="page-link" href="#" onclick="loadPlayedTab(${playedPagination.pages}); return false;">${playedPagination.pages}</a></li>`;
    }
    
    // Next Button
    if (playedPagination.currentPage < playedPagination.pages) {
        paginationHTML += `<li class="page-item"><a class="page-link" href="#" onclick="loadPlayedTab(${playedPagination.currentPage + 1}); return false;">Nächste</a></li>`;
    } else {
        paginationHTML += `<li class="page-item disabled"><span class="page-link">Nächste</span></li>`;
    }
    
    paginationHTML += '</ul></nav>';
    paginationContainer.innerHTML = paginationHTML;
}

// Lade Wishlist vollständig wenn nötig (mehr als 50 Einträge)
function loadFullWishlist() {
    const wishlistContainer = document.querySelector('#wishlist .list-group');
    if (!wishlistContainer) return;
    
    // Prüfe ob bereits mehr als 50 Einträge geladen sind
    const currentItems = wishlistContainer.querySelectorAll('.list-group-item').length;
    if (currentItems < 50) {
        return; // Weniger als 50, keine weitere Ladung nötig
    }
    
    // Lade weitere Einträge
    fetch('/music/api/wishlist/list?page=1&per_page=100')
        .then(response => response.json())
        .then(data => {
            if (data.error || !data.wishes) return;
            
            // Ersetze nur wenn mehr Einträge vorhanden sind
            if (data.wishes.length > currentItems) {
                // Aktualisiere nur die zusätzlichen Einträge
                // (Für jetzt: Ersetze alles, könnte optimiert werden)
                wishlistContainer.innerHTML = '';
                data.wishes.forEach(wish => {
                    const wishItem = createWishItem(wish);
                    wishlistContainer.appendChild(wishItem);
                });
                
                loadLazyImages();
            }
        })
        .catch(error => {
            console.error('Fehler beim Laden der vollständigen Wishlist:', error);
        });
}

// Helper: Erstelle Wish-Item Element
function createWishItem(wish) {
    const wishItem = document.createElement('div');
    wishItem.className = 'list-group-item';
    wishItem.setAttribute('data-wish-id', wish.id);
    
    const providerClass = wish.provider === 'spotify' ? 'success' : 'danger';
    const wishCount = wish.wish_count || 1;
    let countBadgeClass = 'bg-secondary';
    if (wishCount > 1) {
        if (wishCount <= 3) {
            countBadgeClass = 'bg-primary';
        } else if (wishCount <= 5) {
            countBadgeClass = 'bg-warning';
        } else {
            countBadgeClass = 'bg-danger';
        }
    }
    
    const imageUrl = wish.image_url && wish.image_url !== 'undefined' && wish.image_url !== 'null' && wish.image_url.trim() !== '' ? wish.image_url : null;
    const imageHtml = imageUrl
        ? `<div class="me-3 position-relative" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i><img data-src="${escapeHtml(imageUrl)}" alt="Cover" class="lazy-image position-absolute" style="width: 48px; height: 48px; object-fit: cover; border-radius: 4px; top: 0; left: 0; opacity: 0; transition: opacity 0.3s;" onerror="this.onerror=null; this.style.display='none';" onload="this.style.opacity='1'; this.previousElementSibling.style.display='none';"></div>`
        : `<div class="me-3" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i></div>`;
    
    wishItem.innerHTML = `
        <div class="d-flex align-items-center">
            ${imageHtml}
            <div class="flex-grow-1">
                <h6 class="mb-1">
                    ${escapeHtml(wish.title || 'Unbekannt')}
                    <span class="badge ${countBadgeClass} ms-2 wish-count-badge">${wishCount}x</span>
                </h6>
                <p class="text-muted mb-1 small">${escapeHtml(wish.artist || 'Unbekannter Künstler')}</p>
                <span class="badge bg-${providerClass} provider-badge">${wish.provider}</span>
            </div>
            <div class="btn-group-vertical btn-group-sm">
                <button class="btn btn-sm btn-success" onclick="addToQueue(${wish.id}, 'next')" title="An 1. Stelle einfügen">
                    <i class="bi bi-arrow-up-circle"></i>
                </button>
                <button class="btn btn-sm btn-primary" onclick="addToQueue(${wish.id}, 'last')" title="An letzter Stelle einfügen">
                    <i class="bi bi-arrow-down-circle"></i>
                </button>
                <button class="btn btn-sm btn-danger" onclick="markAsPlayed(${wish.id})" title="Zu bereits gespielt verschieben">
                    <i class="bi bi-x-circle"></i>
                </button>
            </div>
        </div>
    `;
    
    return wishItem;
}

// Direktes DOM-Update für Played-Liste ohne Fetch-Request
function addToPlayedDisplayDirect(wish) {
    const playedContainer = document.querySelector('#played .list-group');
    if (!playedContainer) return;
    
    // Prüfe ob bereits existiert
    const existingItem = playedContainer.querySelector(`[data-wish-id="${wish.id}"]`);
    if (existingItem) {
        // Aktualisiere bestehendes Element
        const wishItem = createPlayedItem(wish);
        existingItem.replaceWith(wishItem);
        loadLazyImages();
        return;
    }
    
    // Entferne "Leer"-Nachricht falls vorhanden
    const emptyMessage = playedContainer.querySelector('.text-muted.text-center');
    if (emptyMessage) {
        emptyMessage.remove();
    }
    
    // Erstelle neues Element
    const wishItem = createPlayedItem(wish);
    
    // Füge am Anfang der Liste hinzu (neueste zuerst)
    if (playedContainer.children.length === 0) {
        playedContainer.appendChild(wishItem);
    } else {
        playedContainer.insertBefore(wishItem, playedContainer.firstChild);
    }
    
    // Lade Bilder lazy
    loadLazyImages();
}

// Helper: Erstelle Played-Item Element
function createPlayedItem(wish) {
    const wishItem = document.createElement('div');
    wishItem.className = 'list-group-item';
    wishItem.setAttribute('data-wish-id', wish.id);
    
    const providerClass = wish.provider === 'spotify' ? 'success' : 'danger';
    const wishCount = wish.wish_count || 1;
    let countBadgeClass = 'bg-secondary';
    if (wishCount > 1) {
        if (wishCount <= 3) {
            countBadgeClass = 'bg-primary';
        } else if (wishCount <= 5) {
            countBadgeClass = 'bg-warning';
        } else {
            countBadgeClass = 'bg-danger';
        }
    }
    
    const imageUrl = wish.image_url && wish.image_url !== 'undefined' && wish.image_url !== 'null' && wish.image_url.trim() !== '' ? wish.image_url : null;
    const imageHtml = imageUrl
        ? `<div class="me-3 position-relative" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i><img data-src="${escapeHtml(imageUrl)}" alt="Cover" class="lazy-image position-absolute" style="width: 48px; height: 48px; object-fit: cover; border-radius: 4px; top: 0; left: 0; opacity: 0; transition: opacity 0.3s;" onerror="this.onerror=null; this.style.display='none';" onload="this.style.opacity='1'; this.previousElementSibling.style.display='none';"></div>`
        : `<div class="me-3" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note" style="color: #000000;"></i></div>`;
    
    const updatedAt = wish.updated_at ? new Date(wish.updated_at).toLocaleString('de-DE') : 'Unbekannt';
    
    wishItem.innerHTML = `
        <div class="d-flex align-items-center">
            ${imageHtml}
            <div class="flex-grow-1">
                <h6 class="mb-1">
                    ${escapeHtml(wish.title || 'Unbekannt')}
                    <span class="badge ${countBadgeClass} ms-2">${wishCount}x</span>
                </h6>
                <p class="text-muted mb-1 small">${escapeHtml(wish.artist || 'Unbekannter Künstler')}</p>
                <span class="badge bg-${providerClass} provider-badge">${wish.provider}</span>
                <small class="text-muted d-block mt-1">
                    <i class="bi bi-clock"></i> Gespielt: ${updatedAt}
                </small>
            </div>
        </div>
    `;
    
    return wishItem;
}

// Drag & Drop für Warteschlange
document.addEventListener('DOMContentLoaded', function() {
    const queueList = document.getElementById('queue-list');
    if (!queueList) return;
    
    let draggedElement = null;
    
    // Drag-Events
    queueList.addEventListener('dragstart', function(e) {
        if (e.target.classList.contains('queue-item')) {
            draggedElement = e.target;
            e.target.style.opacity = '0.5';
        }
    });
    
    queueList.addEventListener('dragend', function(e) {
        if (e.target.classList.contains('queue-item')) {
            e.target.style.opacity = '1';
        }
    });
    
    queueList.addEventListener('dragover', function(e) {
        e.preventDefault();
        const afterElement = getDragAfterElement(queueList, e.clientY);
        const dragging = document.querySelector('.dragging');
        if (dragging) {
            if (afterElement == null) {
                queueList.appendChild(dragging);
            } else {
                queueList.insertBefore(dragging, afterElement);
            }
        }
    });
    
    queueList.addEventListener('drop', function(e) {
        e.preventDefault();
        if (!draggedElement) return;
        
        const items = Array.from(queueList.querySelectorAll('.queue-item'));
        const newPosition = items.indexOf(draggedElement) + 1;
        const queueId = draggedElement.dataset.queueId;
        
        // Sende neue Position an Server
        fetch('/music/queue/move', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                queue_id: parseInt(queueId),
                position: newPosition
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // SocketIO-Event wird automatisch die Queue aktualisieren
                // Kein location.reload() mehr nötig!
            } else {
                alert('Fehler beim Verschieben: ' + (data.error || 'Unbekannter Fehler'));
                // Lade Queue neu bei Fehler
                updateQueueDisplay();
            }
        })
        .catch(error => {
            alert('Fehler: ' + error.message);
            updateQueueDisplay();
        });
        
        draggedElement = null;
    });
    
    // Initialisiere Lazy Loading für Bilder
    loadLazyImages();
    
    // Lade Lazy Images auch nach DOM-Updates (z.B. nach SocketIO-Events)
    const observer = new MutationObserver(function(mutations) {
        loadLazyImages();
    });
    
    // Beobachte Änderungen in den Listen-Containern
    const wishlistContainer = document.querySelector('#wishlist-list');
    const queueContainer = document.querySelector('#queue-list');
    if (wishlistContainer) {
        observer.observe(wishlistContainer, { childList: true, subtree: true });
    }
    if (queueContainer) {
        observer.observe(queueContainer, { childList: true, subtree: true });
    }
    
    // Tab-Wechsel-Listener für Lazy Loading
    const tabButtons = document.querySelectorAll('#musicTabs button[data-bs-toggle="tab"]');
    tabButtons.forEach(button => {
        button.addEventListener('shown.bs.tab', function(event) {
            const targetTab = event.target.getAttribute('data-bs-target');
            
            // Lade "Bereits gespielt" Tab beim ersten Öffnen
            if (targetTab === '#played' && !loadedTabs.played) {
                loadPlayedTab(1);
            }
            
            // Lade Bilder lazy beim Tab-Wechsel
            loadLazyImages();
        });
    });
    
    // Initialisiere Badges basierend auf tatsächlichen DOM-Elementen
    initializeBadges();
});

// Fallback: Lade Played-Count per Fetch (für Initial-Load)
function updatePlayedBadge() {
    const cacheKey = 'played_count';
    const cached = getCached(cacheKey, CACHE_TTL_COUNT);
    if (cached !== null) {
        updatePlayedBadgeDirect(cached);
        return;
    }
    
    fetch('/music/api/played/count')
        .then(response => response.json())
        .then(data => {
            const count = data.count || 0;
            setCached(cacheKey, count);
            updatePlayedBadgeDirect(count);
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren des Played-Badges:', error);
        });
}

// Initialisiere Badges beim Laden der Seite
function initializeBadges() {
    // Zähle tatsächliche Wünsche im DOM
    const wishlistContainer = document.querySelector('#wishlist-list');
    if (wishlistContainer) {
        const wishItems = wishlistContainer.querySelectorAll('.list-group-item[data-wish-id]');
        const wishCount = wishItems.length;
        cachedCounts.wishlist = wishCount;
        updateWishlistBadgeDirect(wishCount);
    } else {
        // Fallback: Lade Count per API
        updateWishlistBadge();
    }
    
    // Zähle tatsächliche Queue-Items im DOM
    const queueContainer = document.querySelector('#queue-list');
    if (queueContainer) {
        const queueItems = queueContainer.querySelectorAll('.queue-item[data-queue-id]');
        const queueCount = queueItems.length;
        cachedCounts.queue = queueCount;
        updateQueueBadgeDirect(queueCount);
    } else {
        // Fallback: Lade Count per API
        updateQueueBadge();
    }
    
    // Played-Count wird per API geladen (da Tab lazy geladen wird)
    updatePlayedBadge();
}

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.queue-item:not(.dragging)')];
    
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}
