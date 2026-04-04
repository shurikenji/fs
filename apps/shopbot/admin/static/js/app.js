/* admin/static/js/app.js — Admin panel JavaScript */

// Confirm dialog trước khi xóa
function confirmDelete(message) {
    return confirm(message || 'Bạn có chắc chắn muốn xóa?');
}

// Auto-hide alerts sau 5 giây
document.addEventListener('DOMContentLoaded', function () {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
});

// Highlight active sidebar link
document.addEventListener('DOMContentLoaded', function () {
    const path = window.location.pathname;
    document.querySelectorAll('.sidebar .nav-link').forEach(function (link) {
        const href = link.getAttribute('href');
        if (href && path.startsWith(href) && href !== '/') {
            link.classList.add('active');
        } else if (href === '/' && path === '/') {
            link.classList.add('active');
        }
    });
});

window.AdminRemoteModal = (function () {
    let activeRemoteModal = null;

    function setTriggerLoading(trigger, isLoading) {
        if (!trigger) return;
        trigger.dataset.loading = isLoading ? 'true' : 'false';
        trigger.style.pointerEvents = isLoading ? 'none' : '';
        trigger.style.opacity = isLoading ? '0.7' : '';
        trigger.setAttribute('aria-busy', isLoading ? 'true' : 'false');
    }

    function removeActiveRemoteModal() {
        if (!activeRemoteModal) return;
        const modal = bootstrap.Modal.getInstance(activeRemoteModal);
        if (modal) {
            modal.dispose();
        }
        activeRemoteModal.remove();
        activeRemoteModal = null;
    }

    function showExisting(modalEl, options) {
        if (!modalEl) return null;

        const onReady = options?.onReady;
        const onHiddenNavigate = options?.onHiddenNavigate;
        const removeOnHidden = Boolean(options?.removeOnHidden || modalEl.dataset.remoteEditModal === 'true');

        if (typeof onReady === 'function') {
            onReady(modalEl);
        }

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        const handleHidden = function () {
            modalEl.removeEventListener('hidden.bs.modal', handleHidden);
            modal.dispose();

            if (removeOnHidden) {
                if (activeRemoteModal === modalEl) {
                    activeRemoteModal = null;
                }
                modalEl.remove();
            }

            if (onHiddenNavigate) {
                window.location.href = onHiddenNavigate;
            }
        };

        modalEl.addEventListener('hidden.bs.modal', handleHidden);
        modal.show();
        return modal;
    }

    async function loadFromUrl(url, options) {
        const trigger = options?.trigger;
        const onReady = options?.onReady;

        setTriggerLoading(trigger, true);
        try {
            const response = await fetch(url, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            if (!response.ok) {
                throw new Error('Failed to load edit dialog');
            }

            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const modalEl = doc.getElementById('editModal') || doc.querySelector('.modal');
            if (!modalEl) {
                throw new Error('Edit dialog markup missing');
            }

            removeActiveRemoteModal();

            modalEl.dataset.remoteEditModal = 'true';
            document.body.appendChild(modalEl);
            activeRemoteModal = modalEl;
            showExisting(modalEl, { onReady, removeOnHidden: true });
        } finally {
            setTriggerLoading(trigger, false);
        }
    }

    document.addEventListener('click', async function (event) {
        const trigger = event.target.closest('[data-edit-modal-url]');
        if (!trigger) return;

        event.preventDefault();

        const modalUrl = trigger.getAttribute('data-edit-modal-url');
        const fallbackUrl = trigger.getAttribute('href') || modalUrl;
        const initializerName = trigger.getAttribute('data-edit-modal-init');
        const onReady = initializerName && typeof window[initializerName] === 'function'
            ? window[initializerName]
            : null;

        try {
            await loadFromUrl(modalUrl, { trigger, onReady });
        } catch (error) {
            console.error('Remote edit modal failed:', error);
            window.location.href = fallbackUrl;
        }
    });

    return {
        loadFromUrl,
        showExisting,
    };
})();
