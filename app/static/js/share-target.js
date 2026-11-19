(function () {
  'use strict';

  const DB_NAME = 'prismateams-share-target';
  const STORE_NAME = 'shares';

  const appEl = document.getElementById('shareTargetApp');
  if (!appEl) return;

  const ds = appEl.dataset;
  const csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  const alertBox = document.getElementById('shareAlertBox');
  const successBox = document.getElementById('shareSuccessBox');
  const successText = document.getElementById('shareSuccessText');
  const successLink = document.getElementById('shareSuccessLink');
  const formArea = document.getElementById('shareFormArea');

  const filesPreview = document.getElementById('shareFilesPreview');
  const filesList = document.getElementById('shareFilesList');
  const inputTitle = document.getElementById('shareInputTitle');
  const inputUrl = document.getElementById('shareInputUrl');
  const inputText = document.getElementById('shareInputText');
  const urlGroup = document.getElementById('shareUrlGroup');
  const textGroup = document.getElementById('shareTextGroup');

  const destBtnFiles = document.getElementById('destBtnFiles');
  const destBtnKanban = document.getElementById('destBtnKanban');
  const destBtnEvents = document.getElementById('destBtnEvents');
  const destBtnChat = document.getElementById('destBtnChat');
  const panelFiles = document.getElementById('panelFiles');
  const panelKanban = document.getElementById('panelKanban');
  const panelEvents = document.getElementById('panelEvents');
  const panelChat = document.getElementById('panelChat');

  const eventSelect = document.getElementById('shareEventSelect');
  const eventTodoListGroup = document.getElementById('shareEventTodoListGroup');
  const eventTodoListSelect = document.getElementById('shareEventTodoListSelect');
  const chatSelect = document.getElementById('shareChatSelect');
  const chatMessageInput = document.getElementById('shareChatMessage');

  const spaceSelect = document.getElementById('shareSpaceSelect');
  const folderSelect = document.getElementById('shareFolderSelect');
  const noteFilenameGroup = document.getElementById('shareNoteFilenameGroup');
  const noteFilenameInput = document.getElementById('shareNoteFilename');

  const boardSelect = document.getElementById('shareBoardSelect');
  const listSelect = document.getElementById('shareListSelect');
  const cardSelect = document.getElementById('shareCardSelect');
  const modeNewRadio = document.getElementById('kanbanModeNew');
  const modeExistingRadio = document.getElementById('kanbanModeExisting');
  const newCardFields = document.getElementById('kanbanNewCardFields');
  const existingCardFields = document.getElementById('kanbanExistingCardFields');
  const cardTitleInput = document.getElementById('shareCardTitle');
  const cardDescInput = document.getElementById('shareCardDesc');

  const submitBtn = document.getElementById('shareSubmitBtn');
  const submitLabel = document.getElementById('shareSubmitLabel');
  const defaultSubmitText = submitLabel ? submitLabel.textContent : '';

  let sharedFiles = [];
  let selectedDest = null; // 'files' | 'kanban'
  let fileSpaces = [];
  let filesLoaded = false;
  let kanbanBoards = [];
  let kanbanLoaded = false;
  let currentBoardData = null;
  let eventsList = [];
  let eventsLoaded = false;
  let chatsList = [];
  let chatsLoaded = false;

  function showAlert(msg) {
    if (!alertBox) return;
    alertBox.textContent = msg;
    alertBox.classList.remove('d-none');
  }

  function clearAlert() {
    if (!alertBox) return;
    alertBox.classList.add('d-none');
    alertBox.textContent = '';
  }

  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const val = bytes / Math.pow(1024, i);
    return (i === 0 ? val : val.toFixed(1)) + ' ' + units[i];
  }

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) {
        resolve(null);
        return;
      }
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: 'id' });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  async function loadShareFromDb(id) {
    if (!id) return null;
    try {
      const db = await openDb();
      if (!db) return null;
      return await new Promise(function (resolve, reject) {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const store = tx.objectStore(STORE_NAME);
        const req = store.get(id);
        req.onsuccess = function () { db.close(); resolve(req.result || null); };
        req.onerror = function () { db.close(); reject(req.error); };
      });
    } catch (_) {
      return null;
    }
  }

  async function deleteShareFromDb(id) {
    if (!id) return;
    try {
      const db = await openDb();
      if (!db) return;
      await new Promise(function (resolve) {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).delete(id);
        tx.oncomplete = function () { db.close(); resolve(); };
        tx.onerror = function () { db.close(); resolve(); };
      });
    } catch (_) {
      // ignore
    }
  }

  function extractUrlFromText(text) {
    if (!text) return null;
    const match = text.match(/https?:\/\/[^\s<>"{}|\\^`[\]]+/i);
    return match ? match[0] : null;
  }

  function sanitizeFilename(name) {
    const cleaned = (name || '')
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 80);
    return cleaned || ds.i18nDefaultNoteName || 'notiz';
  }

  function ensureAllowedNoteFilename(rawName) {
    let name = sanitizeFilename(rawName);
    const lower = name.toLowerCase();
    if (!lower.endsWith('.md') && !lower.endsWith('.txt')) {
      name += '.md';
    }
    return name;
  }

  function renderFilesPreview() {
    if (!filesPreview || !filesList) return;
    filesList.innerHTML = '';
    if (!sharedFiles.length) {
      filesPreview.classList.add('d-none');
      return;
    }
    filesPreview.classList.remove('d-none');
    sharedFiles.forEach(function (f) {
      const row = document.createElement('div');
      row.className = 'share-target-file-item';

      const icon = document.createElement('i');
      const type = (f.type || '').toLowerCase();
      if (type.startsWith('image/')) icon.className = 'bi bi-file-earmark-image fs-5 text-primary';
      else if (type.includes('pdf')) icon.className = 'bi bi-file-earmark-pdf fs-5 text-danger';
      else if (type.startsWith('video/')) icon.className = 'bi bi-file-earmark-play fs-5 text-info';
      else if (type.startsWith('audio/')) icon.className = 'bi bi-file-earmark-music fs-5 text-warning';
      else icon.className = 'bi bi-file-earmark fs-5 text-secondary';

      const info = document.createElement('div');
      info.className = 'flex-grow-1 min-w-0';

      const nameEl = document.createElement('div');
      nameEl.className = 'fw-medium text-truncate';
      nameEl.textContent = f.name;

      const sizeEl = document.createElement('div');
      sizeEl.className = 'small text-body-secondary';
      sizeEl.textContent = formatBytes(f.size);

      info.appendChild(nameEl);
      info.appendChild(sizeEl);
      row.appendChild(icon);
      row.appendChild(info);
      filesList.appendChild(row);
    });
  }

  function updateVisibilityForContent() {
    const hasFiles = sharedFiles.length > 0;
    const hasUrl = Boolean((inputUrl && inputUrl.value.trim()) || '');
    const hasText = Boolean((inputText && inputText.value.trim()) || '');

    if (urlGroup) urlGroup.classList.toggle('d-none', !hasUrl && hasFiles);
    if (textGroup) textGroup.classList.toggle('d-none', !hasText && hasFiles);

    if (noteFilenameGroup) {
      noteFilenameGroup.classList.toggle('d-none', hasFiles || selectedDest !== 'files');
    }
  }

  function prefillKanbanAndFilename() {
    const title = (inputTitle ? inputTitle.value.trim() : '');
    const url = (inputUrl ? inputUrl.value.trim() : '');
    const text = (inputText ? inputText.value.trim() : '');

    if (noteFilenameInput && !noteFilenameInput.value.trim()) {
      const base = title || (url ? (function () {
        try { return new URL(url).hostname; } catch (_) { return ''; }
      })() : '') || (text ? text.split(/\r?\n/)[0].slice(0, 40) : '');
      noteFilenameInput.value = ensureAllowedNoteFilename(base || ds.i18nDefaultNoteName || 'notiz');
    }

    if (cardTitleInput && !cardTitleInput.value.trim()) {
      let suggestedTitle = title;
      if (!suggestedTitle && sharedFiles.length) {
        suggestedTitle = sharedFiles[0].name;
      }
      if (!suggestedTitle && url) {
        suggestedTitle = url;
      }
      if (!suggestedTitle && text) {
        suggestedTitle = text.split(/\r?\n/)[0].slice(0, 80);
      }
      cardTitleInput.value = suggestedTitle || '';
    }

    if (cardDescInput && !cardDescInput.value.trim()) {
      const parts = [];
      if (text) parts.push(text);
      if (url && (!text || !text.includes(url))) parts.push(url);
      cardDescInput.value = parts.join('\n\n');
    }

    if (chatMessageInput && !chatMessageInput.value.trim()) {
      const parts = [];
      if (title) parts.push(title);
      if (text) parts.push(text);
      if (url && (!text || !text.includes(url))) parts.push(url);
      chatMessageInput.value = parts.join('\n');
    }
  }

  async function initSharedPayload() {
    if (ds.hasError === '1') {
      showAlert(ds.i18nErrorGeneric);
    }

    let payload = await loadShareFromDb(ds.shareId);
    let title = (payload && payload.title) || ds.fallbackTitle || '';
    let text = (payload && payload.text) || ds.fallbackText || '';
    let url = (payload && payload.url) || ds.fallbackUrl || '';

    if (!url && text) {
      const detected = extractUrlFromText(text);
      if (detected) {
        url = detected;
        if (text.trim() === detected) {
          text = '';
        }
      }
    }

    if (payload && Array.isArray(payload.files)) {
      sharedFiles = payload.files.filter(function (f) { return f && f.blob; });
    }

    if (inputTitle) inputTitle.value = title;
    if (inputUrl) inputUrl.value = url;
    if (inputText) inputText.value = text;

    renderFilesPreview();
    updateVisibilityForContent();
    prefillKanbanAndFilename();

    if (!sharedFiles.length && !title && !url && !text) {
      if (urlGroup) urlGroup.classList.remove('d-none');
      if (textGroup) textGroup.classList.remove('d-none');
    }
  }

  async function loadFilesDestinations() {
    if (filesLoaded || !spaceSelect || !folderSelect) return;
    spaceSelect.innerHTML = '';
    folderSelect.innerHTML = '';
    const opt = document.createElement('option');
    opt.textContent = ds.i18nLoading;
    spaceSelect.appendChild(opt);

    try {
      const res = await fetch(ds.filesDestinationsUrl, { credentials: 'same-origin' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
      fileSpaces = data.spaces || [];
      filesLoaded = true;
      renderSpaces();
    } catch (err) {
      showAlert(err.message || ds.i18nErrorGeneric);
    }
  }

  function renderSpaces() {
    if (!spaceSelect) return;
    spaceSelect.innerHTML = '';
    fileSpaces.forEach(function (sp, idx) {
      const opt = document.createElement('option');
      opt.value = String(idx);
      opt.textContent = sp.label;
      spaceSelect.appendChild(opt);
    });
    renderFoldersForSelectedSpace();
  }

  function appendFolderOptions(folders, depth) {
    if (!Array.isArray(folders)) return;
    const prefix = depth > 0 ? '\u00A0\u00A0'.repeat(depth) + '↳ ' : '';
    folders.forEach(function (folder) {
      const opt = document.createElement('option');
      opt.value = String(folder.id);
      opt.textContent = prefix + folder.name;
      folderSelect.appendChild(opt);
      if (Array.isArray(folder.children) && folder.children.length) {
        appendFolderOptions(folder.children, depth + 1);
      }
    });
  }

  function renderFoldersForSelectedSpace() {
    if (!spaceSelect || !folderSelect) return;
    folderSelect.innerHTML = '';
    const idx = parseInt(spaceSelect.value || '0', 10);
    const space = fileSpaces[idx];
    if (!space) return;

    const rootOpt = document.createElement('option');
    rootOpt.value = space.root_folder_id != null ? String(space.root_folder_id) : '';
    rootOpt.textContent = ds.i18nRootFolder;
    folderSelect.appendChild(rootOpt);

    appendFolderOptions(space.folders || [], 0);
  }

  async function loadKanbanBoards() {
    if (kanbanLoaded || !boardSelect) return;
    boardSelect.innerHTML = '';
    const loadingOpt = document.createElement('option');
    loadingOpt.textContent = ds.i18nLoading;
    boardSelect.appendChild(loadingOpt);

    try {
      const res = await fetch(ds.kanbanBoardsUrl, { credentials: 'same-origin' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
      kanbanBoards = data.boards || [];
      kanbanLoaded = true;
      renderBoards();
    } catch (err) {
      showAlert(err.message || ds.i18nErrorGeneric);
    }
  }

  function renderBoards() {
    if (!boardSelect) return;
    boardSelect.innerHTML = '';
    if (!kanbanBoards.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = ds.i18nNoBoards;
      boardSelect.appendChild(opt);
      boardSelect.disabled = true;
      if (listSelect) listSelect.disabled = true;
      if (cardSelect) cardSelect.disabled = true;
      return;
    }
    boardSelect.disabled = false;
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = ds.i18nSelectBoard;
    boardSelect.appendChild(placeholder);

    kanbanBoards.forEach(function (b) {
      const opt = document.createElement('option');
      opt.value = String(b.id);
      opt.textContent = b.team_name ? (b.title + ' (' + b.team_name + ')') : b.title;
      boardSelect.appendChild(opt);
    });
  }

  async function loadBoardDetails(boardId) {
    if (!listSelect || !cardSelect) return;
    currentBoardData = null;
    listSelect.innerHTML = '';
    cardSelect.innerHTML = '';
    listSelect.disabled = true;
    cardSelect.disabled = true;
    if (!boardId) return;

    const loadOpt = document.createElement('option');
    loadOpt.textContent = ds.i18nLoading;
    listSelect.appendChild(loadOpt);

    try {
      const url = ds.kanbanBoardApiTpl.replace('__ID__', encodeURIComponent(boardId));
      const res = await fetch(url, { credentials: 'same-origin' });
      const data = await res.json();
      if (!res.ok || !data.lists) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
      currentBoardData = data;
      renderLists();
    } catch (err) {
      showAlert(err.message || ds.i18nErrorGeneric);
    }
  }

  function renderLists() {
    if (!listSelect || !currentBoardData) return;
    listSelect.innerHTML = '';
    const lists = currentBoardData.lists || [];
    if (!lists.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = ds.i18nNoLists;
      listSelect.appendChild(opt);
      listSelect.disabled = true;
      return;
    }
    listSelect.disabled = false;
    lists.forEach(function (lst) {
      const opt = document.createElement('option');
      opt.value = String(lst.id);
      opt.textContent = lst.title;
      listSelect.appendChild(opt);
    });
    renderCardsForSelectedList();
  }

  function renderCardsForSelectedList() {
    if (!cardSelect || !listSelect || !currentBoardData) return;
    cardSelect.innerHTML = '';
    const listId = parseInt(listSelect.value || '0', 10);
    const lst = (currentBoardData.lists || []).find(function (l) { return l.id === listId; });
    const cards = (lst && lst.cards) ? lst.cards : [];
    if (!cards.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = ds.i18nNoCards;
      cardSelect.appendChild(opt);
      cardSelect.disabled = true;
      return;
    }
    cardSelect.disabled = false;
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = ds.i18nSelectCard;
    cardSelect.appendChild(placeholder);

    cards.forEach(function (c) {
      const opt = document.createElement('option');
      opt.value = String(c.id);
      opt.textContent = c.title;
      cardSelect.appendChild(opt);
    });
  }

  async function loadEvents() {
    if (eventsLoaded || !eventSelect) return;
    eventSelect.innerHTML = '';
    const loadOpt = document.createElement('option');
    loadOpt.textContent = ds.i18nLoading;
    eventSelect.appendChild(loadOpt);

    try {
      const res = await fetch(ds.eventsUrl, { credentials: 'same-origin' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
      eventsList = data.events || [];
      eventsLoaded = true;
      renderEvents();
    } catch (err) {
      showAlert(err.message || ds.i18nErrorGeneric);
    }
  }

  function renderEvents() {
    if (!eventSelect) return;
    eventSelect.innerHTML = '';
    if (!eventsList.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = ds.i18nNoEvents;
      eventSelect.appendChild(opt);
      eventSelect.disabled = true;
      if (eventTodoListGroup) eventTodoListGroup.classList.add('d-none');
      return;
    }
    eventSelect.disabled = false;
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = ds.i18nSelectEvent;
    eventSelect.appendChild(placeholder);

    eventsList.forEach(function (ev) {
      const opt = document.createElement('option');
      opt.value = String(ev.id);
      opt.textContent = ev.start_date ? (ev.title + ' (' + ev.start_date + ')') : ev.title;
      eventSelect.appendChild(opt);
    });
    renderEventTodoLists();
  }

  function renderEventTodoLists() {
    if (!eventSelect || !eventTodoListGroup || !eventTodoListSelect) return;
    const text = inputText ? inputText.value.trim() : '';
    const evId = parseInt(eventSelect.value || '0', 10);
    const ev = eventsList.find(function (item) { return item.id === evId; });
    if (!ev || !text) {
      eventTodoListGroup.classList.add('d-none');
      return;
    }
    eventTodoListGroup.classList.remove('d-none');
    eventTodoListSelect.innerHTML = '';
    const lists = ev.todo_lists || [];
    if (!lists.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = ds.i18nAutoTodoList;
      eventTodoListSelect.appendChild(opt);
      return;
    }
    lists.forEach(function (tl) {
      const opt = document.createElement('option');
      opt.value = String(tl.id);
      opt.textContent = tl.title;
      eventTodoListSelect.appendChild(opt);
    });
  }

  async function loadChats() {
    if (chatsLoaded || !chatSelect) return;
    chatSelect.innerHTML = '';
    const loadOpt = document.createElement('option');
    loadOpt.textContent = ds.i18nLoading;
    chatSelect.appendChild(loadOpt);

    try {
      const res = await fetch(ds.chatsUrl, { credentials: 'same-origin' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
      chatsList = data.chats || [];
      chatsLoaded = true;
      renderChats();
    } catch (err) {
      showAlert(err.message || ds.i18nErrorGeneric);
    }
  }

  function renderChats() {
    if (!chatSelect) return;
    chatSelect.innerHTML = '';
    if (!chatsList.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = ds.i18nNoChats;
      chatSelect.appendChild(opt);
      chatSelect.disabled = true;
      return;
    }
    chatSelect.disabled = false;
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = ds.i18nSelectChat;
    chatSelect.appendChild(placeholder);

    chatsList.forEach(function (ch) {
      const opt = document.createElement('option');
      opt.value = String(ch.id);
      opt.dataset.navId = String(ch.nav_id || ch.id);
      opt.textContent = ch.name;
      chatSelect.appendChild(opt);
    });
  }

  function selectDestination(dest) {
    selectedDest = dest;
    clearAlert();
    if (destBtnFiles) destBtnFiles.classList.toggle('is-active', dest === 'files');
    if (destBtnKanban) destBtnKanban.classList.toggle('is-active', dest === 'kanban');
    if (destBtnEvents) destBtnEvents.classList.toggle('is-active', dest === 'events');
    if (destBtnChat) destBtnChat.classList.toggle('is-active', dest === 'chat');
    if (panelFiles) panelFiles.classList.toggle('d-none', dest !== 'files');
    if (panelKanban) panelKanban.classList.toggle('d-none', dest !== 'kanban');
    if (panelEvents) panelEvents.classList.toggle('d-none', dest !== 'events');
    if (panelChat) panelChat.classList.toggle('d-none', dest !== 'chat');
    if (submitBtn) submitBtn.disabled = false;
    updateVisibilityForContent();

    if (dest === 'files') {
      loadFilesDestinations();
    } else if (dest === 'kanban') {
      loadKanbanBoards();
    } else if (dest === 'events') {
      loadEvents();
    } else if (dest === 'chat') {
      loadChats();
    }
  }

  function updateKanbanCardMode() {
    const isExisting = Boolean(modeExistingRadio && modeExistingRadio.checked);
    if (newCardFields) newCardFields.classList.toggle('d-none', isExisting);
    if (existingCardFields) existingCardFields.classList.toggle('d-none', !isExisting);
  }

  function buildFilesToUpload() {
    if (sharedFiles.length > 0) {
      return sharedFiles.map(function (f) {
        return new File([f.blob], f.name, { type: f.type || 'application/octet-stream', lastModified: f.lastModified || Date.now() });
      });
    }
    const title = inputTitle ? inputTitle.value.trim() : '';
    const url = inputUrl ? inputUrl.value.trim() : '';
    const text = inputText ? inputText.value.trim() : '';
    if (!title && !url && !text) return [];

    const lines = [];
    if (title) lines.push('# ' + title, '');
    if (url) lines.push(url, '');
    if (text) lines.push(text);
    const content = lines.join('\n').trim() + '\n';
    const filename = ensureAllowedNoteFilename(noteFilenameInput ? noteFilenameInput.value : '');
    const mime = filename.toLowerCase().endsWith('.txt') ? 'text/plain;charset=utf-8' : 'text/markdown;charset=utf-8';
    return [new File([content], filename, { type: mime })];
  }

  async function submitToFiles() {
    const idx = parseInt((spaceSelect && spaceSelect.value) || '0', 10);
    const space = fileSpaces[idx];
    if (!space) {
      throw new Error(ds.i18nErrorNoTarget);
    }
    const files = buildFilesToUpload();
    if (!files.length) {
      throw new Error(ds.i18nErrorEmpty);
    }

    const folderId = folderSelect ? folderSelect.value : '';
    const formData = new FormData();
    formData.append('view', space.view || 'ablage');
    if (space.team_id != null) {
      formData.append('team_id', String(space.team_id));
    }
    if (folderId) {
      formData.append('folder_id', folderId);
    }
    formData.append('conflict_strategy', 'rename');
    files.forEach(function (file) {
      formData.append('file', file, file.name);
    });

    const res = await fetch(ds.filesUploadUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrfToken
      },
      body: formData
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      const msg = (data.messages && data.messages[0] && data.messages[0].text) || data.error || ds.i18nErrorGeneric;
      throw new Error(msg);
    }

    const params = new URLSearchParams();
    if (space.view) params.set('view', space.view);
    if (space.team_id != null) params.set('team_id', String(space.team_id));
    if (folderId) params.set('folder_id', folderId);
    const targetUrl = ds.filesIndexUrl + '?' + params.toString();

    return { message: ds.i18nSuccessFiles, url: targetUrl };
  }

  async function attachFileToCard(cardId, fileObj) {
    const url = ds.kanbanCardAttachmentsTpl.replace('__ID__', encodeURIComponent(String(cardId)));
    const formData = new FormData();
    const file = new File([fileObj.blob], fileObj.name, { type: fileObj.type || 'application/octet-stream' });
    formData.append('file', file, file.name);

    const res = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken },
      body: formData
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || ds.i18nErrorGeneric);
    }
  }

  async function attachLinkToCard(cardId, linkUrl, linkTitle) {
    const url = ds.kanbanCardAttachmentsTpl.replace('__ID__', encodeURIComponent(String(cardId)));
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({ url: linkUrl, title: linkTitle || linkUrl })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || ds.i18nErrorGeneric);
    }
  }

  async function submitToKanban() {
    if (!currentBoardData || !listSelect || !listSelect.value) {
      throw new Error(ds.i18nErrorNoTarget);
    }
    const isExisting = Boolean(modeExistingRadio && modeExistingRadio.checked);
    const linkUrl = inputUrl ? inputUrl.value.trim() : '';
    const linkTitle = inputTitle ? inputTitle.value.trim() : '';
    const sharedText = inputText ? inputText.value.trim() : '';

    let targetCardId = null;

    if (isExisting) {
      targetCardId = cardSelect ? parseInt(cardSelect.value || '0', 10) : 0;
      if (!targetCardId) {
        throw new Error(ds.i18nErrorSelectCard);
      }
      if (sharedText) {
        const cardUrl = ds.kanbanCardApiTpl.replace('__ID__', encodeURIComponent(String(targetCardId)));
        const getRes = await fetch(cardUrl, { credentials: 'same-origin' });
        const cardData = await getRes.json();
        if (getRes.ok) {
          const existingDesc = (cardData.description || '').trim();
          const nextDesc = existingDesc ? (existingDesc + '\n\n' + sharedText) : sharedText;
          await fetch(cardUrl, {
            method: 'PATCH',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ description: nextDesc })
          });
        }
      }
    } else {
      const cardTitle = cardTitleInput ? cardTitleInput.value.trim() : '';
      if (!cardTitle) {
        throw new Error(ds.i18nErrorCardTitle);
      }
      const cardDesc = cardDescInput ? cardDescInput.value.trim() : '';
      const createUrl = ds.kanbanListCardsTpl.replace('__ID__', encodeURIComponent(listSelect.value));
      const res = await fetch(createUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ title: cardTitle, description: cardDesc })
      });
      const data = await res.json();
      if (!res.ok || !data.success || !data.card) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
      targetCardId = data.card.id;
    }

    for (let i = 0; i < sharedFiles.length; i++) {
      await attachFileToCard(targetCardId, sharedFiles[i]);
    }
    if (linkUrl) {
      await attachLinkToCard(targetCardId, linkUrl, linkTitle);
    }

    return {
      message: ds.i18nSuccessKanban,
      url: currentBoardData.url || ('/kanban/board/' + (currentBoardData.public_id || currentBoardData.id))
    };
  }

  async function submitToEvents() {
    const eventId = eventSelect ? parseInt(eventSelect.value || '0', 10) : 0;
    if (!eventId) {
      throw new Error(ds.i18nErrorNoTarget);
    }
    const linkUrl = inputUrl ? inputUrl.value.trim() : '';
    const linkTitle = inputTitle ? inputTitle.value.trim() : '';
    const todoText = inputText ? inputText.value.trim() : '';
    const todoListId = eventTodoListSelect ? eventTodoListSelect.value : '';

    if (!sharedFiles.length && !linkUrl && !todoText) {
      throw new Error(ds.i18nErrorEmpty);
    }

    if (sharedFiles.length > 0) {
      const ensureUrl = ds.eventEnsureFolderTpl.replace('__ID__', encodeURIComponent(String(eventId)));
      const ensureRes = await fetch(ensureUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrfToken }
      });
      const ensureData = await ensureRes.json();
      if (!ensureRes.ok || !ensureData.success) {
        throw new Error(ensureData.error || ds.i18nErrorGeneric);
      }

      const formData = new FormData();
      formData.append('view', ensureData.view || 'public');
      formData.append('folder_id', String(ensureData.folder_id));
      formData.append('conflict_strategy', 'rename');
      sharedFiles.forEach(function (f) {
        const file = new File([f.blob], f.name, { type: f.type || 'application/octet-stream', lastModified: f.lastModified || Date.now() });
        formData.append('file', file, file.name);
      });

      const upRes = await fetch(ds.filesUploadUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrfToken
        },
        body: formData
      });
      const upData = await upRes.json();
      if (!upRes.ok || !upData.success) {
        const msg = (upData.messages && upData.messages[0] && upData.messages[0].text) || upData.error || ds.i18nErrorGeneric;
        throw new Error(msg);
      }
    }

    if (linkUrl || todoText) {
      const addUrl = ds.eventAddTpl.replace('__ID__', encodeURIComponent(String(eventId)));
      const addRes = await fetch(addUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
          link_url: linkUrl,
          link_title: linkTitle,
          todo_text: todoText,
          todo_list_id: todoListId || null
        })
      });
      const addData = await addRes.json();
      if (!addRes.ok || !addData.success) {
        throw new Error(addData.error || ds.i18nErrorGeneric);
      }
    }

    return {
      message: ds.i18nSuccessEvents,
      url: ds.eventViewTpl.replace('__ID__', encodeURIComponent(String(eventId)))
    };
  }

  async function submitToChat() {
    const chatId = chatSelect ? parseInt(chatSelect.value || '0', 10) : 0;
    if (!chatId) {
      throw new Error(ds.i18nErrorNoTarget);
    }
    const selectedOption = chatSelect.options[chatSelect.selectedIndex];
    const navId = (selectedOption && selectedOption.dataset.navId) || String(chatId);
    const sendUrl = ds.chatSendTpl.replace('__ID__', encodeURIComponent(String(chatId)));
    const messageText = chatMessageInput ? chatMessageInput.value.trim() : '';

    if (!sharedFiles.length && !messageText) {
      throw new Error(ds.i18nErrorEmpty);
    }

    if (sharedFiles.length > 0) {
      for (let i = 0; i < sharedFiles.length; i++) {
        const f = sharedFiles[i];
        const formData = new FormData();
        const file = new File([f.blob], f.name, { type: f.type || 'application/octet-stream', lastModified: f.lastModified || Date.now() });
        formData.append('file', file, file.name);
        if (i === 0 && messageText) {
          formData.append('content', messageText);
        }
        const res = await fetch(sendUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRFToken': csrfToken },
          body: formData
        });
        const data = await res.json();
        if (!res.ok || data.error) {
          throw new Error(data.error || ds.i18nErrorGeneric);
        }
      }
    } else {
      const formData = new FormData();
      formData.append('content', messageText);
      const res = await fetch(sendUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrfToken },
        body: formData
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        throw new Error(data.error || ds.i18nErrorGeneric);
      }
    }

    return {
      message: ds.i18nSuccessChat,
      url: ds.chatViewTpl.replace('__ID__', encodeURIComponent(navId))
    };
  }

  async function handleSubmit() {
    clearAlert();
    if (!selectedDest) {
      showAlert(ds.i18nErrorNoTarget);
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    if (submitLabel) submitLabel.textContent = ds.i18nSaving;

    try {
      let result;
      if (selectedDest === 'files') result = await submitToFiles();
      else if (selectedDest === 'kanban') result = await submitToKanban();
      else if (selectedDest === 'events') result = await submitToEvents();
      else if (selectedDest === 'chat') result = await submitToChat();
      else throw new Error(ds.i18nErrorNoTarget);
      await deleteShareFromDb(ds.shareId);
      if (formArea) formArea.classList.add('d-none');
      if (successBox && successText && successLink) {
        successText.textContent = result.message;
        successLink.href = result.url;
        successBox.classList.remove('d-none');
      }
    } catch (err) {
      showAlert(err.message || ds.i18nErrorGeneric);
      if (submitBtn) submitBtn.disabled = false;
      if (submitLabel) submitLabel.textContent = defaultSubmitText;
    }
  }

  if (destBtnFiles) {
    destBtnFiles.addEventListener('click', function () { selectDestination('files'); });
  }
  if (destBtnKanban) {
    destBtnKanban.addEventListener('click', function () { selectDestination('kanban'); });
  }
  if (destBtnEvents) {
    destBtnEvents.addEventListener('click', function () { selectDestination('events'); });
  }
  if (destBtnChat) {
    destBtnChat.addEventListener('click', function () { selectDestination('chat'); });
  }
  if (eventSelect) {
    eventSelect.addEventListener('change', renderEventTodoLists);
  }
  if (inputText) {
    inputText.addEventListener('input', renderEventTodoLists);
  }
  if (spaceSelect) {
    spaceSelect.addEventListener('change', renderFoldersForSelectedSpace);
  }
  if (boardSelect) {
    boardSelect.addEventListener('change', function () { loadBoardDetails(boardSelect.value); });
  }
  if (listSelect) {
    listSelect.addEventListener('change', renderCardsForSelectedList);
  }
  if (modeNewRadio) {
    modeNewRadio.addEventListener('change', updateKanbanCardMode);
  }
  if (modeExistingRadio) {
    modeExistingRadio.addEventListener('change', updateKanbanCardMode);
  }
  if (submitBtn) {
    submitBtn.addEventListener('click', handleSubmit);
  }

  initSharedPayload();
})();
