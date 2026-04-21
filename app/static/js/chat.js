(function () {
    const cfg = window.ChatPageConfig || {};
    const chatId = cfg.chatId;
    const currentUserId = cfg.currentUserId;
    const text = cfg.text || {};
    const i18n = cfg.i18n || {};

    if (!chatId || !currentUserId) {
        return;
    }

    let lastMessageId = cfg.lastMessageId || 0;
    let isPolling = true;
    let isSendingMessage = false;
    let currentMemberCount = cfg.initialMemberCount || 0;
    let notificationsMuted = false;
    let cachedFolderOptions = null;
    let cachedCalendarOptions = null;
    let mediaRecorder;
    let audioChunks = [];

    function byId(id) {
        return document.getElementById(id);
    }

    function escapeHtml(value) {
        const div = document.createElement("div");
        div.textContent = value || "";
        return div.innerHTML;
    }

    function scrollToBottom() {
        const container = byId("messages-container");
        if (!container) return;
        requestAnimationFrame(() => {
            container.scrollTop = container.scrollHeight;
            setTimeout(() => {
                container.scrollTop = container.scrollHeight;
            }, 50);
        });
    }

    function formatTime(value) {
        const date = new Date(value);
        const localeMap = { de: "de-DE", en: "en-US" };
        const locale = localeMap[cfg.language] || cfg.language || "de-DE";
        return date.toLocaleString(locale, {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function formatHourMinute(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        const localeMap = { de: "de-DE", en: "en-US" };
        const locale = localeMap[cfg.language] || cfg.language || "de-DE";
        return date.toLocaleTimeString(locale, {
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function formatDateOnly(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        const localeMap = { de: "de-DE", en: "en-US" };
        const locale = localeMap[cfg.language] || cfg.language || "de-DE";
        return date.toLocaleDateString(locale, {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
        });
    }

    function isAllDayEvent(metadata) {
        if (metadata && metadata.is_all_day === true) return true;
        const start = metadata && metadata.start_time ? new Date(metadata.start_time) : null;
        const end = metadata && metadata.end_time ? new Date(metadata.end_time) : null;
        if (!start || !end || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return false;
        const startsMidnight = start.getHours() === 0 && start.getMinutes() === 0;
        const sameDay = start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth() && start.getDate() === end.getDate();
        const endsSameDay2359 = sameDay && end.getHours() === 23 && end.getMinutes() === 59;
        const endsNextDayMidnight = end.getTime() > start.getTime() && end.getHours() === 0 && end.getMinutes() === 0 && !sameDay;
        return startsMidnight && (endsSameDay2359 || endsNextDayMidnight);
    }

    function getMediaUrl(filename) {
        return `/chat/media/${encodeURIComponent(filename || "")}`;
    }

    function fileCard(message) {
        const metadata = message.metadata || {};
        const name = metadata.original_name || message.media_url || i18n.file_generic || "Datei";
        const size = metadata.size_label ? `<small class="text-muted d-block">${escapeHtml(metadata.size_label)}</small>` : "";
        return `
            <div class="message-card message-card-file">
                <div class="message-card-icon"><i class="bi bi-file-earmark"></i></div>
                <div class="message-card-body">
                    <a href="${getMediaUrl(message.media_url)}" target="_blank" rel="noopener">${escapeHtml(name)}</a>
                    ${size}
                </div>
            </div>
        `;
    }

    function folderCard(message) {
        const metadata = message.metadata || {};
        const folderId = metadata.folder_id ? String(metadata.folder_id) : "";
        const folderUrl = metadata.folder_url || (folderId ? `/files/folder/${encodeURIComponent(folderId)}` : "") || metadata.share_url || "";
        const folderPath = metadata.folder_path ? `<small class="text-muted d-block">${escapeHtml(metadata.folder_path)}</small>` : "";
        const note = (message.content || "").trim();
        const noteHtml = note ? `<p class="mt-2 mb-0">${escapeHtml(note)}</p>` : "";
        return `
            <div class="message-card message-card-folder">
                <div class="message-card-icon"><i class="bi bi-folder2-open"></i></div>
                <div class="message-card-body">
                    <strong>${escapeHtml(metadata.folder_name || i18n.folder_label || "Ordner")}</strong>
                    ${folderPath}
                    ${folderUrl ? `<a href="${escapeHtml(folderUrl)}" class="btn btn-sm btn-outline-secondary mt-2">Ordner öffnen</a>` : `<small class="text-muted fst-italic">Ordner konnte nicht geöffnet werden.</small>`}
                    ${noteHtml}
                </div>
            </div>
        `;
    }

    function calendarCard(message) {
        const metadata = message.metadata || {};
        const allDay = isAllDayEvent(metadata);
        const startLabel = allDay ? "Ganztägig" : (formatHourMinute(metadata.start_time) || metadata.start_time_label || "");
        const dateLabel = metadata.date_label || formatDateOnly(metadata.start_time) || "";
        const note = (message.content || "").trim();
        const noteHtml = note ? `<p class="mt-2 mb-0">${escapeHtml(note)}</p>` : "";
        const description = (metadata.description || "").trim();
        const descriptionHtml = description ? `<p class="mt-2 mb-2">${escapeHtml(description)}</p>` : "";
        const currentStatus = (metadata.current_user_status || "pending").toLowerCase();
        const acceptedBtnClass = currentStatus === "accepted" ? "btn-success" : "btn-outline-success";
        const declinedBtnClass = currentStatus === "declined" ? "btn-danger" : "btn-outline-danger";
        return `
            <div class="message-card message-card-calendar">
                <div class="message-card-icon"><i class="bi bi-calendar-event"></i></div>
                <div class="message-card-body">
                    <strong>${escapeHtml(metadata.title || i18n.calendar_label || "Termin")}</strong>
                    ${dateLabel ? `<div>${escapeHtml(dateLabel)}</div>` : ""}
                    <div>${escapeHtml(startLabel)}</div>
                    ${metadata.location ? `<small class="text-muted">${escapeHtml(metadata.location)}</small>` : ""}
                    ${descriptionHtml}
                    <div class="d-flex flex-wrap gap-1 mt-2">
                        <span class="badge text-bg-success">Zugesagt: ${Number(metadata.accepted_count || 0)}</span>
                        <span class="badge text-bg-danger">Abgesagt: ${Number(metadata.declined_count || 0)}</span>
                    </div>
                    <small class="text-muted d-block mt-1">Dein Status: ${currentStatus === "accepted" ? "Zugesagt" : (currentStatus === "declined" ? "Abgesagt" : "Offen")}</small>
                    <div class="d-flex gap-2 mt-2">
                        <button type="button" class="btn btn-sm ${acceptedBtnClass} calendar-rsvp-btn" data-message-id="${message.id}" data-status="accepted">Zusagen</button>
                        <button type="button" class="btn btn-sm ${declinedBtnClass} calendar-rsvp-btn" data-message-id="${message.id}" data-status="declined">Absagen</button>
                        ${metadata.event_url ? `<a href="${escapeHtml(metadata.event_url)}" class="btn btn-sm btn-outline-secondary">Öffnen</a>` : ""}
                    </div>
                    ${noteHtml}
                </div>
            </div>
        `;
    }

    function pollCard(message) {
        const metadata = message.metadata || {};
        const options = Array.isArray(metadata.options) ? metadata.options : [];
        const allowMultiple = Boolean(metadata.allow_multiple);
        const description = (metadata.description || "").trim();
        const descriptionHtml = description ? `<p class="mb-2">${escapeHtml(description)}</p>` : "";
        const maxVotes = options.reduce((max, option) => {
            const count = Array.isArray(option.votes) ? option.votes.length : 0;
            return count > max ? count : max;
        }, 0);
        const optionsHtml = options
            .map((opt) => {
                const voteCount = Array.isArray(opt.votes) ? opt.votes.length : 0;
                const fillPercent = maxVotes > 0 ? (voteCount / maxVotes) * 100 : 0;
                return `<button class="btn btn-outline-secondary btn-sm poll-option-btn" data-message-id="${message.id}" data-option-id="${escapeHtml(opt.id || "")}">
                    <span class="poll-option-fill" style="width:${fillPercent.toFixed(2)}%;"></span>
                    <span class="poll-option-content">
                        <span>${escapeHtml(opt.text || "")}</span>
                        <span class="poll-vote-count">${voteCount}</span>
                    </span>
                </button>`;
            })
            .join("");
        return `
            <div class="message-card message-card-poll">
                <div class="message-card-icon"><i class="bi bi-bar-chart"></i></div>
                <div class="message-card-body">
                    <strong>${escapeHtml(metadata.question || i18n.poll_label || "Abstimmung")}</strong>
                    ${descriptionHtml}
                    <small class="text-muted">${allowMultiple ? "Mehrfachauswahl erlaubt" : "Nur eine Antwort erlaubt"}</small>
                    <div class="d-flex flex-column gap-2 mt-2">${optionsHtml}</div>
                </div>
            </div>
        `;
    }

    function messageContentHtml(message) {
        if (message.message_type === "image") {
            return `<img src="${getMediaUrl(message.media_url)}" class="img-fluid rounded" style="max-width:320px;" alt="Bild">`;
        }
        if (message.message_type === "video") {
            return `<video controls class="rounded" style="max-width:320px;"><source src="${getMediaUrl(message.media_url)}"></video>`;
        }
        if (message.message_type === "voice") {
            return `<audio controls><source src="${getMediaUrl(message.media_url)}"></audio>`;
        }
        if (message.message_type === "file") {
            return fileCard(message);
        }
        if (message.message_type === "folder_link") {
            return folderCard(message);
        }
        if (message.message_type === "calendar_event") {
            return calendarCard(message);
        }
        if (message.message_type === "poll") {
            return pollCard(message);
        }
        return `<div class="message-content">${escapeHtml(message.content || "")}</div>`;
    }

    function renderMessage(message) {
        const wrapper = document.createElement("div");
        const own = parseInt(message.sender_id, 10) === parseInt(currentUserId, 10);
        wrapper.className = `chat-message ${own ? "own" : "other"}`;
        wrapper.dataset.messageId = String(message.id || "");
        if (message.message_type === "poll") {
            const pollUpdatedAt = message.metadata && message.metadata.updated_at ? String(message.metadata.updated_at) : "";
            wrapper.dataset.pollUpdatedAt = pollUpdatedAt;
        }
        if (message.message_type === "calendar_event") {
            const calendarUpdatedAt = message.metadata && message.metadata.updated_at ? String(message.metadata.updated_at) : "";
            wrapper.dataset.calendarUpdatedAt = calendarUpdatedAt;
        }
        const sender = own ? (text.you || "Du") : escapeHtml(message.sender || message.sender_name || text.unknownUser || "Unbekannt");
        wrapper.innerHTML = `
            <div class="message-header"><strong>${sender}</strong></div>
            ${messageContentHtml(message)}
            ${message.content && message.message_type !== "text" && message.message_type !== "folder_link" && message.message_type !== "calendar_event" ? `<p class="mt-2 mb-0">${escapeHtml(message.content)}</p>` : ""}
            <div class="message-time"><small class="text-muted">${formatTime(message.created_at)}</small></div>
        `;
        return wrapper;
    }

    function addMessageToChat(message) {
        const container = byId("messages-container");
        if (!container) return;
        container.appendChild(renderMessage(message));
    }

    function replacePollCardInMessage(messageElement, message) {
        if (!messageElement || !message || message.message_type !== "poll") return;
        const existingPollCard = messageElement.querySelector(".message-card-poll");
        if (!existingPollCard) return;
        const tempWrapper = document.createElement("div");
        tempWrapper.innerHTML = pollCard(message);
        const newPollCard = tempWrapper.firstElementChild;
        if (newPollCard) {
            existingPollCard.replaceWith(newPollCard);
            const pollUpdatedAt = message.metadata && message.metadata.updated_at ? String(message.metadata.updated_at) : "";
            messageElement.dataset.pollUpdatedAt = pollUpdatedAt;
        }
    }

    function replaceCalendarCardInMessage(messageElement, message) {
        if (!messageElement || !message || message.message_type !== "calendar_event") return;
        const existingCalendarCard = messageElement.querySelector(".message-card-calendar");
        if (!existingCalendarCard) return;
        const tempWrapper = document.createElement("div");
        tempWrapper.innerHTML = calendarCard(message);
        const newCalendarCard = tempWrapper.firstElementChild;
        if (newCalendarCard) {
            existingCalendarCard.replaceWith(newCalendarCard);
            const calendarUpdatedAt = message.metadata && message.metadata.updated_at ? String(message.metadata.updated_at) : "";
            messageElement.dataset.calendarUpdatedAt = calendarUpdatedAt;
        }
    }

    function fileChanged(inputId, labelId) {
        const input = byId(inputId);
        const label = byId(labelId);
        if (!input || !label) return;
        input.addEventListener("change", function () {
            const fileName = this.files && this.files[0] ? this.files[0].name : "";
            label.textContent = fileName ? (i18n.file_label || "{filename}").replace("{filename}", fileName) : "";
        });
    }

    async function sendFormMessage(formId, inputId, fileId, fileLabelId) {
        if (isSendingMessage) return;
        const form = byId(formId);
        const input = byId(inputId);
        const fileInput = byId(fileId);
        if (!form || !input || !fileInput) return;

        const formData = new FormData(form);
        const file = fileInput.files && fileInput.files[0];
        if (!input.value.trim() && !file) return;

        isSendingMessage = true;
        try {
            const response = await fetch(`/chat/${chatId}/send`, {
                method: "POST",
                body: formData,
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || i18n.send_error_generic || "Fehler");
            addMessageToChat(payload);
            lastMessageId = payload.id;
            input.value = "";
            fileInput.value = "";
            if (fileLabelId && byId(fileLabelId)) byId(fileLabelId).textContent = "";
            scrollToBottom();
        } catch (err) {
            alert((i18n.send_error_prefix || "Fehler: {error}").replace("{error}", err.message || ""));
        } finally {
            isSendingMessage = false;
        }
    }

    async function sendStructuredMessage(messageType, metadata, content) {
        if (isSendingMessage) return;
        isSendingMessage = true;
        try {
            const response = await fetch(`/chat/${chatId}/send`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({
                    message_type: messageType,
                    metadata: metadata || {},
                    content: content || "",
                }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "Fehler");
            addMessageToChat(payload);
            lastMessageId = payload.id;
            scrollToBottom();
        } catch (err) {
            alert(err.message || "Fehler beim Senden");
        } finally {
            isSendingMessage = false;
        }
    }

    async function sendVoiceMessage(audioBlob, mimeType) {
        if (isSendingMessage) return;
        const extension = mimeType.includes("ogg") ? "ogg" : "webm";
        const formData = new FormData();
        formData.append("file", audioBlob, `voice_message.${extension}`);
        formData.append("content", "");
        isSendingMessage = true;
        try {
            const response = await fetch(`/chat/${chatId}/send`, {
                method: "POST",
                body: formData,
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || i18n.voice_error || "Fehler");
            addMessageToChat(payload);
            lastMessageId = payload.id;
            scrollToBottom();
        } catch (e) {
            alert(e.message || i18n.voice_error || "Sprachnachricht fehlgeschlagen");
        } finally {
            isSendingMessage = false;
        }
    }

    window.startVoiceRecording = async function () {
        const micIcon = byId("mic-icon");
        const micIconDesktop = byId("mic-icon-desktop");
        if (mediaRecorder && mediaRecorder.state === "recording") {
            mediaRecorder.stop();
            if (micIcon) micIcon.className = "bi bi-mic fs-5";
            if (micIconDesktop) micIconDesktop.className = "bi bi-mic";
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/ogg";
            mediaRecorder = new MediaRecorder(stream, { mimeType });
            audioChunks = [];
            mediaRecorder.ondataavailable = function (event) {
                if (event.data.size > 0) audioChunks.push(event.data);
            };
            mediaRecorder.onstop = function () {
                const blob = new Blob(audioChunks, { type: mimeType });
                stream.getTracks().forEach((track) => track.stop());
                sendVoiceMessage(blob, mimeType);
            };
            mediaRecorder.start();
            if (micIcon) micIcon.className = "bi bi-stop-circle fs-5 text-danger";
            if (micIconDesktop) micIconDesktop.className = "bi bi-stop-circle text-danger";
        } catch (e) {
            alert(i18n.microphone_denied || "Mikrofonzugriff verweigert");
        }
    };

    async function pollMessages() {
        if (!isPolling) return;
        try {
            const response = await fetch(`/api/chats/${chatId}/messages?since=${lastMessageId}`, { headers: { "X-Requested-With": "XMLHttpRequest" } });
            if (response.ok) {
                const payload = await response.json();
                const messages = Array.isArray(payload) ? payload : (payload.messages || []);
                messages.forEach((msg) => {
                    if (msg.id > lastMessageId) {
                        addMessageToChat(msg);
                        lastMessageId = msg.id;
                    }
                });
                if (messages.length) scrollToBottom();
            }
        } catch (e) {
            console.error(e);
        }
        setTimeout(pollMessages, 2000);
    }

    async function syncStructuredMessageUpdates() {
        if (!isPolling) return;
        try {
            const response = await fetch(`/api/chats/${chatId}/messages?limit=200`, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (response.ok) {
                const payload = await response.json();
                const messages = Array.isArray(payload) ? payload : (payload.messages || []);
                messages.forEach((message) => {
                    if (message.message_type === "poll") {
                        const messageElement = document.querySelector(`.chat-message[data-message-id="${message.id}"]`);
                        if (!messageElement) return;
                        const incomingUpdatedAt = message.metadata && message.metadata.updated_at ? String(message.metadata.updated_at) : "";
                        const currentUpdatedAt = messageElement.dataset.pollUpdatedAt || "";
                        if (incomingUpdatedAt && incomingUpdatedAt !== currentUpdatedAt) {
                            replacePollCardInMessage(messageElement, message);
                        }
                        return;
                    }
                    if (message.message_type !== "calendar_event") return;
                    const messageElement = document.querySelector(`.chat-message[data-message-id="${message.id}"]`);
                    if (!messageElement) return;
                    const incomingUpdatedAt = message.metadata && message.metadata.updated_at ? String(message.metadata.updated_at) : "";
                    const currentUpdatedAt = messageElement.dataset.calendarUpdatedAt || "";
                    if (incomingUpdatedAt && incomingUpdatedAt !== currentUpdatedAt) {
                        replaceCalendarCardInMessage(messageElement, message);
                    }
                });
            }
        } catch (e) {
            console.error(e);
        }
        setTimeout(syncStructuredMessageUpdates, 3000);
    }

    function syncMobileComposerSpacing() {
        if (window.innerWidth >= 768) return;
        const composer = document.querySelector(".chat-input-container.d-md-none");
        if (!composer) return;
        const height = Math.ceil(composer.getBoundingClientRect().height || composer.offsetHeight || 0);
        if (height > 0) {
            const spacing = Math.max(176, height + 56);
            document.documentElement.style.setProperty("--chat-mobile-composer-space", `${spacing}px`);
        }
    }

    async function loadFolderPickerOptions() {
        if (cachedFolderOptions) return cachedFolderOptions;
        const response = await fetch(`/chat/${chatId}/folder-options`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Ordner konnten nicht geladen werden");
        }
        const folders = Array.isArray(payload.folders) ? payload.folders : [];
        cachedFolderOptions = {
            folders,
            isGuest: Boolean(payload.is_guest),
        };
        return cachedFolderOptions;
    }

    async function loadCalendarPickerOptions() {
        if (cachedCalendarOptions) return cachedCalendarOptions;
        const response = await fetch("/api/events", {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Termine konnten nicht geladen werden");
        }
        const events = Array.isArray(payload) ? payload : [];
        cachedCalendarOptions = events;
        return cachedCalendarOptions;
    }

    async function openFolderPickerModal() {
        const modalEl = byId("folderPickerModal");
        const selectEl = byId("folder-picker-select");
        const guestNoteEl = byId("folder-picker-guest-note");
        if (!modalEl || !selectEl) return;

        selectEl.innerHTML = `<option value="">Bitte auswählen...</option>`;
        if (guestNoteEl) guestNoteEl.classList.add("d-none");

        try {
            const pickerData = await loadFolderPickerOptions();
            pickerData.folders.forEach((folder) => {
                const option = document.createElement("option");
                option.value = String(folder.id);
                option.textContent = folder.path || folder.name || `Ordner ${folder.id}`;
                option.dataset.folderName = folder.name || "";
                option.dataset.folderPath = folder.path || "";
                selectEl.appendChild(option);
            });
            if (pickerData.isGuest && pickerData.folders.length === 0 && guestNoteEl) {
                guestNoteEl.classList.remove("d-none");
            }
            new bootstrap.Modal(modalEl).show();
        } catch (error) {
            alert(error.message || "Ordner konnten nicht geladen werden");
        }
    }

    async function openCalendarPickerModal() {
        const modalEl = byId("calendarPickerModal");
        const selectEl = byId("calendar-picker-select");
        if (!modalEl || !selectEl) return;

        selectEl.innerHTML = `<option value="">Bitte auswählen...</option>`;
        try {
            const events = await loadCalendarPickerOptions();
            events
                .slice()
                .sort((a, b) => {
                    const aTime = new Date(a.start_time || 0).getTime();
                    const bTime = new Date(b.start_time || 0).getTime();
                    return aTime - bTime;
                })
                .forEach((eventItem) => {
                    const option = document.createElement("option");
                    option.value = String(eventItem.id);
                    option.textContent = `${eventItem.title || `Termin ${eventItem.id}`} - ${formatTime(eventItem.start_time)}`;
                    selectEl.appendChild(option);
                });
            new bootstrap.Modal(modalEl).show();
        } catch (error) {
            alert(error.message || "Termine konnten nicht geladen werden");
        }
    }

    async function respondToCalendarEvent(messageId, status) {
        try {
            const response = await fetch(`/api/chats/${chatId}/messages/${messageId}/calendar-rsvp`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({ status }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "Antwort konnte nicht gespeichert werden");
            const existingButton = document.querySelector(`.calendar-rsvp-btn[data-message-id="${messageId}"]`);
            const messageElement = existingButton ? existingButton.closest(".chat-message") : null;
            if (messageElement && payload.message) {
                replaceCalendarCardInMessage(messageElement, payload.message);
            }
        } catch (error) {
            alert(error.message || "Antwort konnte nicht gespeichert werden");
        }
    }

    async function markRead() {
        if (!isPolling) return;
        try {
            await fetch(`/api/chats/${chatId}/mark-read`, {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
        } catch (e) {
            console.error(e);
        }
        setTimeout(markRead, 15000);
    }

    async function updateMuteState(enabled) {
        try {
            await fetch(`/api/notifications/chat/${chatId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({ enabled }),
            });
        } catch (e) {
            console.error(e);
        }
    }

    window.toggleNotifications = function () {
        notificationsMuted = !notificationsMuted;
        localStorage.setItem(`chat_${chatId}_notifications_muted`, notificationsMuted ? "true" : "false");
        updateMuteState(!notificationsMuted);
        const ids = [
            ["notification-icon", "notification-text"],
            ["notification-icon-mobile", "notification-text-mobile"],
        ];
        ids.forEach(([iconId, textId]) => {
            const icon = byId(iconId);
            const label = byId(textId);
            if (icon) icon.className = notificationsMuted ? "bi bi-bell-slash me-2" : "bi bi-bell me-2";
            if (label) label.textContent = notificationsMuted ? (i18n.unmute || "Stumm aus") : (i18n.mute || "Stumm");
        });
    };

    async function votePoll(messageId, optionId) {
        try {
            const response = await fetch(`/api/chats/${chatId}/messages/${messageId}/poll-vote`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({ option_id: optionId }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "Fehler");
            const existingButton = document.querySelector(`.poll-option-btn[data-message-id="${messageId}"]`);
            const messageElement = existingButton ? existingButton.closest(".chat-message") : null;
            if (messageElement && payload.message) {
                replacePollCardInMessage(messageElement, payload.message);
            }
        } catch (e) {
            alert(e.message || "Abstimmung fehlgeschlagen");
        }
    }

    document.addEventListener("click", function (event) {
        const btn = event.target.closest(".poll-option-btn");
        if (btn) {
            votePoll(btn.getAttribute("data-message-id"), btn.getAttribute("data-option-id"));
        }
        const calendarBtn = event.target.closest(".calendar-rsvp-btn");
        if (calendarBtn) {
            respondToCalendarEvent(calendarBtn.getAttribute("data-message-id"), calendarBtn.getAttribute("data-status"));
        }
    });

    function bindComposer() {
        fileChanged("file-upload", "file-name");
        fileChanged("file-upload-desktop", "file-name-desktop");

        const mobile = byId("message-form");
        if (mobile) {
            mobile.addEventListener("submit", function (e) {
                e.preventDefault();
                sendFormMessage("message-form", "message-input", "file-upload", "file-name");
            });
        }
        const desktop = byId("message-form-desktop");
        if (desktop) {
            desktop.addEventListener("submit", function (e) {
                e.preventDefault();
                sendFormMessage("message-form-desktop", "message-input-desktop", "file-upload-desktop", "file-name-desktop");
            });
        }
    }

    function bindAttachmentPopup() {
        const closeAllAttachmentPopups = () => {
            document.querySelectorAll(".attachment-popup.show").forEach((popup) => popup.classList.remove("show"));
        };

        document.querySelectorAll("[data-attachment-trigger]").forEach((btn) => {
            btn.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const container = btn.closest(".chat-input-container");
                const popup = container ? container.querySelector(".attachment-popup") : null;
                if (!popup) return;
                const shouldOpen = !popup.classList.contains("show");
                closeAllAttachmentPopups();
                if (shouldOpen) popup.classList.add("show");
            });
        });

        document.querySelectorAll("[data-attachment-action='file']").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                const container = button.closest(".chat-input-container");
                const fileInput = container ? (container.querySelector("#file-upload-desktop") || container.querySelector("#file-upload")) : null;
                closeAllAttachmentPopups();
                if (fileInput) fileInput.click();
            });
        });

        document.querySelectorAll("[data-attachment-action='folder']").forEach((button) => {
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                closeAllAttachmentPopups();
                openFolderPickerModal();
            });
        });

        document.querySelectorAll("[data-attachment-action='calendar']").forEach((button) => {
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                closeAllAttachmentPopups();
                openCalendarPickerModal();
            });
        });

        document.querySelectorAll("[data-attachment-action='poll']").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                closeAllAttachmentPopups();
                const modalEl = byId("pollCreateModal");
                if (modalEl) new bootstrap.Modal(modalEl).show();
            });
        });

        document.addEventListener("click", (event) => {
            if (!event.target.closest(".chat-input-container")) {
                closeAllAttachmentPopups();
            }
        });

        const pollForm = byId("poll-create-form");
        if (pollForm) {
            pollForm.addEventListener("submit", async function (e) {
                e.preventDefault();
                const question = byId("poll-question").value.trim();
                const description = (byId("poll-description")?.value || "").trim();
                const optionsRaw = byId("poll-options").value.trim();
                const allowMultiple = Boolean(byId("poll-allow-multiple")?.checked);
                if (!question || !optionsRaw) return;
                const options = optionsRaw
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean)
                    .slice(0, 8)
                    .map((line, index) => ({ id: `opt_${index + 1}`, text: line, votes: [] }));
                if (options.length < 2) {
                    alert("Bitte mindestens zwei Optionen angeben.");
                    return;
                }
                await sendStructuredMessage("poll", { question, description, options, allow_multiple: allowMultiple, total_votes: 0 });
                bootstrap.Modal.getInstance(byId("pollCreateModal"))?.hide();
                pollForm.reset();
            });
        }

        const folderForm = byId("folder-picker-form");
        if (folderForm) {
            folderForm.addEventListener("submit", async function (event) {
                event.preventDefault();
                const selectEl = byId("folder-picker-select");
                if (!selectEl || !selectEl.value) {
                    alert("Bitte einen Ordner auswählen.");
                    return;
                }
                const selectedOption = selectEl.options[selectEl.selectedIndex];
                const folderId = Number(selectEl.value);
                if (!Number.isFinite(folderId) || folderId <= 0) {
                    alert("Bitte einen gültigen Ordner auswählen.");
                    return;
                }
                const note = (byId("folder-picker-note")?.value || "").trim();
                await sendStructuredMessage("folder_link", {
                    folder_id: folderId,
                    folder_name: selectedOption?.dataset?.folderName || selectedOption?.textContent || `Ordner ${folderId}`,
                    folder_path: selectedOption?.dataset?.folderPath || selectedOption?.textContent || "",
                }, note);
                bootstrap.Modal.getInstance(byId("folderPickerModal"))?.hide();
                folderForm.reset();
            });
        }

        const calendarForm = byId("calendar-picker-form");
        if (calendarForm) {
            calendarForm.addEventListener("submit", async function (event) {
                event.preventDefault();
                const selectEl = byId("calendar-picker-select");
                const note = (byId("calendar-picker-note")?.value || "").trim();
                if (!selectEl || !selectEl.value) {
                    alert("Bitte einen Termin auswählen.");
                    return;
                }

                const eventId = Number(selectEl.value);
                if (!Number.isFinite(eventId) || eventId <= 0) {
                    alert("Bitte einen gültigen Termin auswählen.");
                    return;
                }

                try {
                    const response = await fetch(`/api/events/${eventId}`, {
                        headers: { "X-Requested-With": "XMLHttpRequest" },
                    });
                    const eventData = await response.json();
                    if (!response.ok) throw new Error(eventData.error || "Termin nicht gefunden");

                    const participants = Array.isArray(eventData.participants) ? eventData.participants : [];
                    const acceptedCount = participants.filter((participant) => participant.status === "accepted").length;
                    const declinedCount = participants.filter((participant) => participant.status === "declined").length;
                    const pendingCount = participants.filter((participant) => participant.status === "pending").length;
                    const currentUserParticipant = participants.find((participant) => Number(participant.user_id) === Number(currentUserId));
                    const currentStatus = currentUserParticipant ? currentUserParticipant.status : "pending";

                    await sendStructuredMessage("calendar_event", {
                        event_id: eventData.id,
                        title: eventData.title,
                        description: eventData.description || "",
                        location: eventData.location || "",
                        start_time: eventData.start_time,
                        end_time: eventData.end_time,
                        start_time_label: formatTime(eventData.start_time),
                        end_time_label: formatTime(eventData.end_time),
                        event_url: `/calendar/event/${eventData.id}`,
                        accepted_count: acceptedCount,
                        declined_count: declinedCount,
                        pending_count: pendingCount,
                        participant_count: participants.length,
                        current_user_status: currentStatus,
                    }, note);
                    bootstrap.Modal.getInstance(byId("calendarPickerModal"))?.hide();
                    calendarForm.reset();
                } catch (error) {
                    alert(error.message || "Termin konnte nicht gesendet werden");
                }
            });
        }
    }

    window.showAllMembersModal = function () {
        const modal = byId("allMembersModal");
        if (modal) new bootstrap.Modal(modal).show();
    };
    window.showMemberModal = function (element) {
        const name = element.getAttribute("data-member-name") || "";
        const email = element.getAttribute("data-member-email") || "";
        const phone = element.getAttribute("data-member-phone") || "";
        const isGuest = element.getAttribute("data-member-is-guest") === "1";
        const picture = element.getAttribute("data-member-picture") || "";

        const nameEl = byId("modal-member-name");
        if (nameEl) {
            nameEl.innerHTML = isGuest
                ? `${escapeHtml(name)} <span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle ms-1">${text.guestBadge || "Gast"}</span>`
                : escapeHtml(name);
        }
        if (byId("modal-member-email")) byId("modal-member-email").textContent = email;
        if (byId("modal-member-phone")) byId("modal-member-phone").textContent = phone;
        if (byId("modal-member-phone-container")) byId("modal-member-phone-container").style.display = phone ? "block" : "none";

        const avatar = byId("modal-member-avatar");
        const initial = byId("modal-member-initial");
        if (picture && avatar && initial) {
            avatar.src = cfg.profilePictureRoute.replace("__FILENAME__", encodeURIComponent(picture));
            avatar.style.display = "block";
            initial.style.display = "none";
        } else if (avatar && initial) {
            avatar.style.display = "none";
            initial.style.display = "flex";
            initial.textContent = name ? name[0].toUpperCase() : "?";
        }
        const modal = byId("memberModal");
        if (modal) new bootstrap.Modal(modal).show();
    };
    window.showChatInfoModal = function () {
        const modal = byId("chatInfoModal");
        if (modal) new bootstrap.Modal(modal).show();
    };
    window.deleteChat = async function (id) {
        if (!confirm("Möchten Sie diesen Chat wirklich löschen?")) return;
        const response = await fetch(`/chat/${id}/delete`, { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } });
        if (response.ok) window.location.href = "/chat/";
    };

    document.addEventListener("DOMContentLoaded", function () {
        bindComposer();
        bindAttachmentPopup();
        notificationsMuted = localStorage.getItem(`chat_${chatId}_notifications_muted`) === "true";
        if (notificationsMuted) window.toggleNotifications();
        syncMobileComposerSpacing();
        window.addEventListener("resize", syncMobileComposerSpacing);
        window.addEventListener("orientationchange", syncMobileComposerSpacing);
        if (window.visualViewport) {
            window.visualViewport.addEventListener("resize", syncMobileComposerSpacing);
        }
        setTimeout(scrollToBottom, 120);
        pollMessages();
        syncStructuredMessageUpdates();
        markRead();
    });
})();
