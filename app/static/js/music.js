// WebSocket-Verbindung für Live-Updates
let socket = null;

if (typeof io !== 'undefined') {
    socket = io();
    
    socket.on('music:queue_updated', function(data) {
        console.log('Queue-Update empfangen:', data);
        updateQueueDisplay();
    });
    
    socket.on('music:wish_added', function(data) {
        console.log('Wunsch hinzugefügt:', data);
        addWishToDisplay(data);
        updateWishlistBadge();
    });
    
    socket.on('music:wishlist_cleared', function(data) {
        console.log('Wunschliste geleert');
        clearWishlistDisplay();
        updateWishlistBadge();
    });
}

// Funktionen für Live-Updates
function updateWishlistBadge() {
    // Lade aktuelle Anzahl der Wünsche
    fetch('/music/api/wishlist/count')
        .then(response => response.json())
        .then(data => {
            const badge = document.querySelector('#wishlist-tab .badge');
            if (badge && data.count !== undefined) {
                badge.textContent = data.count;
            }
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren des Wishlist-Badges:', error);
        });
}

function updateQueueBadge() {
    // Lade aktuelle Anzahl der Queue-Einträge
    fetch('/music/api/queue/count')
        .then(response => response.json())
        .then(data => {
            const badge = document.querySelector('#queue-tab .badge');
            if (badge && data.count !== undefined) {
                badge.textContent = data.count;
            }
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren des Queue-Badges:', error);
        });
}

function addWishToDisplay(wishData) {
    // Prüfe ob wir auf der Wishlist-Seite sind
    const wishlistContainer = document.querySelector('#wishlist .list-group');
    if (!wishlistContainer) return;
    
    // Prüfe ob Wunsch bereits existiert
    const existingWish = wishlistContainer.querySelector(`[data-wish-id="${wishData.wish_id}"]`);
    if (existingWish) {
        // Aktualisiere Wish-Count
        const wishCountBadge = existingWish.querySelector('.wish-count-badge');
        if (wishCountBadge && wishData.wish_count) {
            wishCountBadge.textContent = wishData.wish_count + 'x';
            // Aktualisiere Badge-Farbe basierend auf Count
            wishCountBadge.className = 'badge ms-2 wish-count-badge';
            if (wishData.wish_count <= 3) {
                wishCountBadge.classList.add('bg-primary');
            } else if (wishData.wish_count <= 5) {
                wishCountBadge.classList.add('bg-warning');
            } else {
                wishCountBadge.classList.add('bg-danger');
            }
        }
        // Aktualisiere Badge trotzdem
        updateWishlistBadge();
        return;
    }
    
    // Erstelle neues Wish-Element
    const wishItem = document.createElement('div');
    wishItem.className = 'list-group-item';
    wishItem.setAttribute('data-wish-id', wishData.wish_id);
    
    const providerClass = wishData.provider === 'spotify' ? 'success' : 'danger';
    const wishCount = wishData.wish_count || 1;
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
    
    const imageHtml = wishData.image_url 
        ? `<img src="${escapeHtml(wishData.image_url)}" alt="Cover" class="me-3" style="width: 48px; height: 48px; object-fit: cover; border-radius: 4px;">`
        : `<div class="me-3" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note"></i></div>`;
    
    wishItem.innerHTML = `
        <div class="d-flex align-items-center">
            ${imageHtml}
            <div class="flex-grow-1">
                <h6 class="mb-1">
                    ${escapeHtml(wishData.title || 'Unbekannt')}
                    <span class="badge ${countBadgeClass} ms-2 wish-count-badge">${wishCount}x</span>
                </h6>
                <p class="text-muted mb-1 small">${escapeHtml(wishData.artist || 'Unbekannter Künstler')}</p>
                <span class="badge bg-${providerClass} provider-badge">${wishData.provider}</span>
            </div>
            <div class="btn-group-vertical btn-group-sm">
                <button class="btn btn-sm btn-success" onclick="addToQueue(${wishData.wish_id}, 'next')" title="Als nächstes hinzufügen">
                    <i class="bi bi-arrow-up-circle"></i>
                </button>
                <button class="btn btn-sm btn-primary" onclick="addToQueue(${wishData.wish_id}, 'last')" title="Als letztes hinzufügen">
                    <i class="bi bi-arrow-down-circle"></i>
                </button>
                <button class="btn btn-sm btn-secondary" onclick="addToQueue(${wishData.wish_id}, 'end')" title="Am Ende hinzufügen">
                    <i class="bi bi-arrow-down"></i>
                </button>
            </div>
        </div>
    `;
    
    // Füge am Anfang der Liste hinzu
    if (wishlistContainer.children.length === 0 || wishlistContainer.querySelector('.text-muted.text-center')) {
        // Liste ist leer, ersetze "Leer"-Nachricht
        wishlistContainer.innerHTML = '';
    }
    wishlistContainer.insertBefore(wishItem, wishlistContainer.firstChild);
    
    // Aktualisiere Badge
    updateWishlistBadge();
}

function clearWishlistDisplay() {
    const wishlistContainer = document.querySelector('#wishlist .list-group');
    if (!wishlistContainer) return;
    
    wishlistContainer.innerHTML = '<p class="text-muted text-center py-4">Keine Wünsche vorhanden</p>';
    updateWishlistBadge();
}

function updateQueueDisplay() {
    // Lade aktuelle Queue-Daten
    fetch('/music/api/queue/list')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Fehler beim Laden der Queue:', data.error);
                return;
            }
            
            const queueContainer = document.querySelector('#queue-list');
            if (!queueContainer) return;
            
            if (!data.queue || data.queue.length === 0) {
                queueContainer.innerHTML = '<p class="text-muted text-center py-4">Warteschlange ist leer</p>';
                updateQueueBadge();
                return;
            }
            
            // Erstelle Queue-Elemente
            queueContainer.innerHTML = data.queue.map(entry => {
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
                
                const imageHtml = entry.wish.image_url 
                    ? `<img src="${escapeHtml(entry.wish.image_url)}" alt="Cover" class="me-3" style="width: 48px; height: 48px; object-fit: cover; border-radius: 4px;">`
                    : `<div class="me-3" style="width: 48px; height: 48px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="bi bi-music-note"></i></div>`;
                
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
            
            // Re-initialisiere Drag & Drop
            initializeDragAndDrop();
            updateQueueBadge();
        })
        .catch(error => {
            console.error('Fehler beim Aktualisieren der Queue:', error);
        });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
                location.reload();
            } else {
                alert('Fehler beim Verschieben: ' + (data.error || 'Unbekannter Fehler'));
                location.reload();
            }
        })
        .catch(error => {
            alert('Fehler: ' + error.message);
            location.reload();
        });
        
        draggedElement = null;
    });
    
    // Mache alle Queue-Items draggable
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
});

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

