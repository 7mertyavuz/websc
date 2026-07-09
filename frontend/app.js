// ScrapeHub Frontend — Vanilla JS Dashboard
(function () {
    const API_BASE = window.location.origin;
    const LS_KEY = 'scrapehub_api_key';

    let currentBooksOffset = 0;
    const BOOKS_LIMIT = 25;

    // DOM helpers
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    function getApiKey() {
        return localStorage.getItem(LS_KEY) || $('#api-key').value.trim();
    }

    function setApiKey(key) {
        localStorage.setItem(LS_KEY, key);
        $('#api-key').value = key;
    }

    function showToast(title, message, type = 'info') {
        const container = $('#toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<div class="toast-title">${escapeHtml(title)}</div><div class="toast-message">${escapeHtml(message)}</div>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async function apiCall(path, options = {}) {
        const key = getApiKey();
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };
        if (key) headers['X-API-Key'] = key;

        const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.detail || `${res.status} ${res.statusText}`);
        }
        return data;
    }

    async function apiGet(path) {
        return apiCall(path, { method: 'GET' });
    }

    async function apiPost(path, body) {
        return apiCall(path, { method: 'POST', body: JSON.stringify(body) });
    }

    // Navigation
    function initNavigation() {
        $$('.nav-item').forEach((item) => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const page = item.dataset.page;
                history.pushState(null, '', `#${page}`);
                showPage(page);
            });
        });

        window.addEventListener('popstate', () => routeByHash());
        routeByHash();
    }

    function routeByHash() {
        const hash = window.location.hash.replace('#', '') || 'dashboard';
        showPage(hash);
    }

    function showPage(pageId) {
        $$('.page').forEach((p) => p.classList.remove('active'));
        $$(`.nav-item`).forEach((n) => n.classList.remove('active'));

        const page = $(`#page-${pageId}`);
        if (page) page.classList.add('active');

        const nav = $(`.nav-item[data-page="${pageId}"]`);
        if (nav) nav.classList.add('active');

        const titles = {
            dashboard: 'Dashboard',
            scrape: 'Kazıma Başlat',
            tasks: 'Görevler',
            books: 'Kitaplar',
            deadletter: 'Dead Letter',
            health: 'Sağlık',
        };
        $('#page-title').textContent = titles[pageId] || 'Dashboard';

        if (pageId === 'dashboard') loadDashboard();
        if (pageId === 'books') loadBooks(currentBooksOffset);
        if (pageId === 'deadletter') loadDeadLetter();
        if (pageId === 'health') loadHealth();
    }

    // Dashboard
    async function loadDashboard() {
        try {
            const stats = await apiGet('/stats');
            $('#stat-books').textContent = stats.books_in_db ?? '-';
        } catch (e) {
            $('#stat-books').textContent = '-';
        }

        try {
            const metricsText = await fetch(`${API_BASE}/metrics`).then((r) => r.text());
            $('#metrics-output').textContent = metricsText;

            const processed = metricsText.match(/scrapehub_pages_processed_total\s+(\d+)/);
            const failed = metricsText.match(/scrapehub_failed_fetch_total\s+(\d+)/);
            const deadletter = metricsText.match(/scrapehub_dead_letter_depth\s+(\d+)/);

            $('#stat-processed').textContent = processed ? processed[1] : '-';
            $('#stat-failed').textContent = failed ? failed[1] : '-';
            $('#stat-deadletter').textContent = deadletter ? deadletter[1] : '-';
        } catch (e) {
            $('#metrics-output').textContent = 'Metrikler alınamadı.';
        }

        renderHealth();
    }

    async function renderHealth() {
        const grid = $('#health-grid');
        try {
            const health = await apiGet('/health');
            grid.innerHTML = Object.entries(health.checks || {})
                .map(([name, ok]) => {
                    const cls = ok ? 'ok' : 'fail';
                    const label = ok ? 'Sağlıklı' : 'Hata';
                    return `<div class="health-item ${cls}"><span class="status-dot"></span><span>${escapeHtml(name)} — ${label}</span></div>`;
                })
                .join('');
        } catch (e) {
            grid.innerHTML = `<div class="health-item fail"><span class="status-dot"></span><span>Sağlık kontrolü başarısız</span></div>`;
        }
    }

    // Scrape forms
    function initScrapeForms() {
        $('#scrape-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultBox = $('#scrape-result');
            const body = {
                start_url: $('#scrape-start-url').value || null,
                max_pages: parseInt($('#scrape-max-pages').value, 10),
                chunk_size: parseInt($('#scrape-chunk-size').value, 10),
                webhook_url: $('#scrape-webhook').value || null,
            };
            try {
                const endpoint = $('#scrape-ai').checked ? '/scrape-dynamic' : '/scrape';
                const data = await apiPost(endpoint, body);
                resultBox.classList.remove('hidden', 'error');
                resultBox.textContent = `Görev kuyruğa eklendi: ${data.task_id}`;
                addRecentTask(data.task_id, 'Katalog kazıma');
                showToast('Başarılı', 'Kazıma görevi kuyruğa eklendi.', 'success');
            } catch (err) {
                resultBox.classList.remove('hidden');
                resultBox.classList.add('error');
                resultBox.textContent = `Hata: ${err.message}`;
                showToast('Hata', err.message, 'error');
            }
        });

        $('#scrape-one-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultBox = $('#scrape-one-result');
            const body = {
                url: $('#scrape-one-url').value,
                force: $('#scrape-one-force').checked,
            };
            try {
                const data = await apiPost('/scrape-one', body);
                resultBox.classList.remove('hidden', 'error');
                resultBox.textContent = `Görev kuyruğa eklendi: ${data.task_id}`;
                addRecentTask(data.task_id, 'Tek URL kazıma');
                showToast('Başarılı', 'Tek URL kazıma görevi eklendi.', 'success');
            } catch (err) {
                resultBox.classList.remove('hidden');
                resultBox.classList.add('error');
                resultBox.textContent = `Hata: ${err.message}`;
                showToast('Hata', err.message, 'error');
            }
        });
    }

    // Tasks
    function initTasks() {
        $('#task-check-btn').addEventListener('click', async () => {
            const taskId = $('#task-id-input').value.trim();
            if (!taskId) return;
            const out = $('#task-result');
            out.classList.remove('hidden');
            out.textContent = 'Sorgulanıyor...';
            try {
                const data = await apiGet(`/status/${taskId}`);
                out.textContent = JSON.stringify(data, null, 2);
            } catch (err) {
                out.textContent = `Hata: ${err.message}`;
            }
        });
    }

    function addRecentTask(taskId, type) {
        const container = $('#recent-tasks');
        if (container.classList.contains('empty-state')) {
            container.classList.remove('empty-state');
            container.innerHTML = '';
        }
        const item = document.createElement('div');
        item.className = 'task-item';
        item.innerHTML = `<div class="task-type">${escapeHtml(type)}</div><code>${escapeHtml(taskId)}</code>`;
        container.prepend(item);
    }

    // Books
    function initBooks() {
        $('#books-prev').addEventListener('click', () => {
            if (currentBooksOffset >= BOOKS_LIMIT) {
                currentBooksOffset -= BOOKS_LIMIT;
                loadBooks(currentBooksOffset);
            }
        });
        $('#books-next').addEventListener('click', () => {
            currentBooksOffset += BOOKS_LIMIT;
            loadBooks(currentBooksOffset);
        });
    }

    async function loadBooks(offset) {
        const tbody = $('#books-tbody');
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">Yükleniyor...</td></tr>';
        try {
            const data = await apiGet(`/books?limit=${BOOKS_LIMIT}&offset=${offset}`);
            const pageNum = Math.floor(offset / BOOKS_LIMIT) + 1;
            $('#books-page-info').textContent = `Sayfa ${pageNum} (${data.total} kayıt)`;
            $('#books-prev').disabled = offset === 0;
            $('#books-next').disabled = offset + BOOKS_LIMIT >= data.total;

            if (!data.books || data.books.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center">Kayıt bulunamadı.</td></tr>';
                return;
            }

            tbody.innerHTML = data.books
                .map((b) => {
                    const shortUrl = b.url.length > 50 ? b.url.slice(0, 50) + '...' : b.url;
                    return `<tr>
                        <td>${escapeHtml(b.title)}</td>
                        <td>£${b.price?.toFixed(2) || '0.00'}</td>
                        <td>${escapeHtml(b.availability || '-')}</td>
                        <td>${'★'.repeat(b.rating || 0)}${'☆'.repeat(5 - (b.rating || 0))}</td>
                        <td><a href="${escapeHtml(b.url)}" target="_blank" rel="noopener">${escapeHtml(shortUrl)}</a></td>
                    </tr>`;
                })
                .join('');
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center">Hata: ${escapeHtml(err.message)}</td></tr>`;
        }
    }

    // Dead letter
    async function loadDeadLetter() {
        const out = $('#deadletter-output');
        out.textContent = 'Yükleniyor...';
        try {
            const data = await apiGet('/dead-letter');
            out.textContent = JSON.stringify(data, null, 2);
        } catch (err) {
            out.textContent = `Hata: ${err.message}`;
        }
    }

    // Health page
    async function loadHealth() {
        const out = $('#health-output');
        out.textContent = 'Yükleniyor...';
        try {
            const data = await apiGet('/health');
            out.textContent = JSON.stringify(data, null, 2);
        } catch (err) {
            out.textContent = `Hata: ${err.message}`;
        }
    }

    // API key
    function initApiKey() {
        const saved = localStorage.getItem(LS_KEY);
        if (saved) $('#api-key').value = saved;

        $('#save-key').addEventListener('click', () => {
            const key = $('#api-key').value.trim();
            if (key) {
                setApiKey(key);
                showToast('Kaydedildi', 'API key yerel olarak saklandı.', 'success');
            }
        });
    }

    // Refresh
    function initRefresh() {
        $('#refresh-btn').addEventListener('click', () => {
            const active = $('.page.active');
            const pageId = active.id.replace('page-', '');
            showPage(pageId);
            showToast('Yenilendi', 'Sayfa içeriği güncellendi.', 'info');
        });
    }

    // Init
    document.addEventListener('DOMContentLoaded', () => {
        initApiKey();
        initNavigation();
        initScrapeForms();
        initTasks();
        initBooks();
        initRefresh();
        loadDashboard();
    });
})();
