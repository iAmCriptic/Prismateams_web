// WebSocket-Verbindung für Live-Updates
let socket = null;

if (typeof io !== 'undefined') {
    socket = io();
    
    socket.on('music:queue_updated', function(data) {
        // Aktualisiere die Seite wenn Queue geändert wurde
        location.reload();
    });
    
    socket.on('music:wish_added', function(data) {
        // Aktualisiere die Seite wenn ein Wunsch hinzugefügt wurde
        location.reload();
    });
    
    socket.on('music:wishlist_cleared', function(data) {
        // Aktualisiere die Seite wenn Wunschliste geleert wurde
        location.reload();
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

